# Cowrie Elasticsearch Reporting - Quick Implementation Guide

## Setup Steps

### 1. Install Dependencies
```bash
pip install elasticsearch>=8.0.0
```

### 2. Deploy CLI & Templates
- Install or copy the `cowrieprocessor` package onto the reporting host (the CLI entrypoint is `cowrie-report`)
- Save index templates under `scripts/` (daily/weekly/monthly JSON files)

### 3. Create Index Templates & ILM Policies (no delete)
```bash
# ILM: Daily hot 7d -> cold (no delete)
curl -X PUT "localhost:9200/_ilm/policy/cowrie.reports.daily" -H "Content-Type: application/json" \
  -d '{"policy":{"phases":{"hot":{"min_age":"0ms","actions":{"set_priority":{"priority":100}}},"cold":{"min_age":"7d","actions":{"set_priority":{"priority":0}}}}}}'

# ILM: Weekly hot 30d -> cold (no delete)
curl -X PUT "localhost:9200/_ilm/policy/cowrie.reports.weekly" -H "Content-Type: application/json" \
  -d '{"policy":{"phases":{"hot":{"min_age":"0ms","actions":{"set_priority":{"priority":100}}},"cold":{"min_age":"30d","actions":{"set_priority":{"priority":0}}}}}}'

# ILM: Monthly hot 90d -> cold (no delete)
curl -X PUT "localhost:9200/_ilm/policy/cowrie.reports.monthly" -H "Content-Type: application/json" \
  -d '{"policy":{"phases":{"hot":{"min_age":"0ms","actions":{"set_priority":{"priority":100}}},"cold":{"min_age":"90d","actions":{"set_priority":{"priority":0}}}}}}'

# Index templates per type
curl -X PUT "localhost:9200/_index_template/cowrie.reports.daily" -H "Content-Type: application/json" \
  -d @scripts/cowrie.reports.daily-index.json
curl -X PUT "localhost:9200/_index_template/cowrie.reports.weekly" -H "Content-Type: application/json" \
  -d @scripts/cowrie.reports.weekly-index.json
curl -X PUT "localhost:9200/_index_template/cowrie.reports.monthly" -H "Content-Type: application/json" \
  -d @scripts/cowrie.reports.monthly-index.json
```

### 4. Set Environment Variables
```bash
export ES_HOST=localhost:9200
export ES_USERNAME=elastic
# Secrets can reference env/file/1Password/AWS SM/etc. and will be resolved automatically
export ES_PASSWORD=file:/run/secrets/es_password
# alternatively
# export ES_API_KEY=op://Elastic/cowrie-reporting/api_key
```

### 5. Test Report Generation
```bash
# Daily aggregate (prints JSON)
cowrie-report daily 2024-12-20 --db /path/to/cowrieprocessor.sqlite

# Daily per-sensor set with Elasticsearch publishing enabled
cowrie-report daily 2024-12-20 --db /path/to/cowrieprocessor.sqlite --all-sensors --publish

# Weekly rollup (ISO week string supported)
cowrie-report weekly 2024-W50 --db /path/to/cowrieprocessor.sqlite --publish
```

> **Backfill note:** the new CLI does not yet include a standalone `backfill` subcommand. Loop over the desired dates and invoke `cowrie-report daily <date> --all-sensors --publish` until the range is covered.

### 6. Schedule with Cron
```bash
crontab -e
# Add:
30 4 * * * cd /home/cowrie/dshield && cowrie-report daily "$(date -u +\\%F)" --db /home/cowrie/dshield/cowrieprocessor.sqlite --all-sensors --publish
0 5 * * 1 cowrie-report weekly "$(date -u +\\%G-W\\%V)" --db /home/cowrie/dshield/cowrieprocessor.sqlite --publish
30 5 1 * * cowrie-report monthly "$(date -u +\\%Y-\\%m)" --db /home/cowrie/dshield/cowrieprocessor.sqlite --publish
```

## Key Features Implemented

### Daily Reports (Per-sensor + Aggregate)
- **Session Metrics**: Total sessions, command totals, file downloads, login attempts, VT/DShield flags, unique IP counts
- **Command Statistics**: Top command inputs (`input_safe`) ranked by frequency
- **File Activity**: Most common download URLs per window

### Weekly & Monthly Rollups (Aggregate)
- Reuse session metrics to surface trends over 7-day and month windows
- Focus on aggregate view; sensor-specific weekly/monthly cuts are planned but not yet implemented

### Alert Thresholds
- **IP Spike**: >50% increase from 7-day average
- **New VT Classification**: Not seen in past 30 days
- **High Tunnel Usage**: >30% of sessions

### Multi-Sensor Support
- Individual reports per sensor (honeypot1, honeypot2)
- Aggregate report combining all sensors
- Sensor name from hostname or override with `--sensor`

### Data Structure
```
cowrie.reports.daily-write (alias -> cowrie.reports.daily-000001, ...)
  └── sensor:daily:date (e.g., "honeypot1:daily:2024-12-20")
      ├── sessions (metrics)
      ├── commands (top commands)
      └── files (top download URLs)

cowrie.reports.weekly-write
  └── aggregate:weekly:YYYY-Www (e.g., "aggregate:weekly:2024-W51")
      └── Aggregated session metrics

cowrie.reports.monthly-write
  └── aggregate:monthly:YYYY-MM (e.g., "aggregate:monthly:2024-12")
      └── Aggregated session metrics
```

## Usage Examples

### Daily Operations
```bash
# Generate all reports for today (UTC)
cowrie-report daily "$(date -u +%F)" --db /path/to/cowrieprocessor.sqlite --all-sensors --publish

# Generate for specific date
cowrie-report daily 2024-12-19 --db /path/to/cowrieprocessor.sqlite --all-sensors --publish

# Single sensor only
cowrie-report daily 2024-12-19 --db /path/to/cowrieprocessor.sqlite --sensor honeypot1 --publish
```

### Backfilling
```bash
# Backfill date range (loop over dates)
for day in $(seq 0 29); do
  cowrie-report daily "$(date -u -d "2024-12-20 - ${day} day" +%F)" \
    --db /path/to/cowrieprocessor.sqlite --all-sensors --publish
done
```

### Rollups
```bash
# Weekly rollup (current week)
cowrie-report weekly "$(date -u +%G-W%V)" --db /path/to/cowrieprocessor.sqlite --publish

# Specific week
cowrie-report weekly 2024-W50 --db /path/to/cowrieprocessor.sqlite --publish

# Monthly rollup
cowrie-report monthly 2024-11 --db /path/to/cowrieprocessor.sqlite --publish
```

## Kibana Queries

### View Latest Daily Report
```
GET cowrie.reports.daily-*/_search
{
  "size": 1,
  "sort": [{"@timestamp": "desc"}],
  "query": {"term": {"sensor.keyword": "aggregate"}}
}
```

### Session Trend (Last 30 Days)
```
GET cowrie.reports.daily-*/_search
{
  "size": 0,
  "query": {
    "bool": {
      "filter": [
        {"term": {"sensor.keyword": "aggregate"}},
        {"range": {"date": {"gte": "now-30d/d"}}}
      ]
    }
  },
  "aggs": {
    "daily_sessions": {
      "date_histogram": {
        "field": "date",
        "calendar_interval": "day"
      },
      "aggs": {
        "sessions": {"sum": {"field": "sessions.total"}}
      }
    }
  }
}
```

## Monitoring

### Check Report Generation
```bash
# View last 5 reports
curl -s "localhost:9200/cowrie.reports.daily-*/_search?size=5&sort=@timestamp:desc" | jq '.hits.hits[]._source | {date: .date, sensor: .sensor, sessions: .sessions.total}'

# Check for missing days
python3 -c "
from datetime import datetime, timedelta
import requests
for i in range(7):
    date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
    r = requests.get(f'http://localhost:9200/cowrie.reports.daily-*/_count?q=date:{date}')
    print(f'{date}: {r.json()[\"count\"]} reports')
"
```

## Troubleshooting

### Common Issues

1. **No data in reports**
   - Check SQLite has data: `sqlite3 cowrieprocessor.sqlite "SELECT COUNT(*) FROM session_summaries"`
   - Verify date range has sessions

2. **Connection errors**
   - Test ES connection: `curl localhost:9200`
   - Check credentials in environment

3. **Missing enrichments**
   - The ORM rewrite currently publishes core metrics only; enrichment fields will return in a later phase

4. **Slow queries**
   - Add index on timestamp: `CREATE INDEX idx_session_summaries_first_event ON session_summaries(first_event_at)`
   - Limit date ranges for backfill loops

### Debug Mode
```bash
# Enable debug logging
python3 -c "import logging; logging.basicConfig(level=logging.DEBUG)" -m cowrieprocessor.cli.report daily 2024-12-20 --db /path/to/cowrieprocessor.sqlite --publish
```

## Next Steps

1. **Create Kibana Dashboard**
   - Import visualizations for trends
   - Set up alert watchers
   
2. **Tune Alert Thresholds**
   - Adjust percentages based on your environment
   - Add custom alerts for specific threats

3. **Extend Metrics**
   - Add GeoIP aggregations
   - Include command sequence analysis
   - Track persistence indicators

4. **Integration**
   - Forward high-severity alerts to SIEM
   - Create Slack/email notifications
   - Build executive reports from monthly rollups
