# Enrichment Operations Runbook

## Overview

This runbook provides operational procedures for managing the multi-source enrichment cascade in production environments.

## Daily Operations

### Morning Health Check

```bash
#!/bin/bash
# Daily enrichment health check

echo "=== Enrichment Health Check ==="
echo "Date: $(date)"
echo

# 1. Check MaxMind database age
python3 << 'EOF'
from pathlib import Path
from datetime import datetime, timedelta
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient

client = MaxMindClient(db_path=Path("/mnt/dshield/data/cache/maxmind"))
age = client.get_database_age()
print(f"MaxMind DB age: {age.days} days")

if age > timedelta(days=14):
    print("⚠️  WARNING: MaxMind database >14 days old!")
elif age > timedelta(days=7):
    print("⚠️  INFO: MaxMind database needs update soon")
else:
    print("✅ MaxMind database fresh")
EOF

# 2. Check GreyNoise quota
python3 << 'EOF'
from pathlib import Path
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
client = GreyNoiseClient(
    api_key="$GREYNOISE_API_KEY",
    cache=cache,
    ttl_days=7
)

remaining = client.get_remaining_quota()
print(f"GreyNoise quota: {remaining:,}/10,000 ({remaining/100:.0f}%)")

if remaining < 1000:
    print("🚨 CRITICAL: GreyNoise quota <1000!")
elif remaining < 2000:
    print("⚠️  WARNING: GreyNoise quota <2000!")
else:
    print("✅ GreyNoise quota sufficient")
EOF

# 3. Check enrichment coverage
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" << 'SQL'
WITH coverage AS (
    SELECT
        COUNT(*) as total_ips,
        COUNT(asn_number) as enriched_ips,
        COUNT(asn_number) * 100.0 / COUNT(*) as coverage_pct
    FROM ip_inventory
)
SELECT
    total_ips,
    enriched_ips,
    ROUND(coverage_pct, 2) || '%' as coverage
FROM coverage;

-- Stale data check
SELECT
    'Cymru stale' as category,
    COUNT(*) as count
FROM ip_inventory
WHERE asn_source = 'cymru'
  AND enrichment_ts < NOW() - INTERVAL '90 days'
UNION ALL
SELECT
    'GreyNoise stale' as category,
    COUNT(*) as count
FROM ip_inventory
WHERE scanner_ts < NOW() - INTERVAL '7 days';
SQL

echo
echo "=== Health Check Complete ==="
```

### Quota Monitoring

Monitor GreyNoise API usage throughout the day:

```bash
# Check quota every 4 hours
*/240 * * * * /opt/cowrieprocessor/scripts/check_greynoise_quota.sh

# Script: /opt/cowrieprocessor/scripts/check_greynoise_quota.sh
#!/bin/bash
remaining=$(python3 -c "
from pathlib import Path
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
cache = EnrichmentCacheManager(cache_dir=Path('/mnt/dshield/data/cache'))
client = GreyNoiseClient(api_key='$GREYNOISE_API_KEY', cache=cache, ttl_days=7)
print(client.get_remaining_quota())
")

echo "[$(date)] GreyNoise quota: $remaining/10000"

if [ "$remaining" -lt 1000 ]; then
    echo "🚨 ALERT: GreyNoise quota critical!" | mail -s "GreyNoise Quota Alert" ops@example.com
fi
```

## Weekly Maintenance

### MaxMind Database Update

```bash
#!/bin/bash
# Weekly MaxMind database update
# Cron: 0 2 * * 0 (Sunday 2 AM)

echo "=== MaxMind Database Update ==="
date

cd /mnt/dshield/data/cache/maxmind

# Download new databases
wget -q "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=$MAXMIND_LICENSE_KEY&suffix=tar.gz" -O GeoLite2-City.tar.gz
wget -q "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-ASN&license_key=$MAXMIND_LICENSE_KEY&suffix=tar.gz" -O GeoLite2-ASN.tar.gz

# Backup old databases
cp GeoLite2-City.mmdb GeoLite2-City.mmdb.backup
cp GeoLite2-ASN.mmdb GeoLite2-ASN.mmdb.backup

# Extract new databases
tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"
tar -xzf GeoLite2-ASN.tar.gz --strip-components=1 "*/GeoLite2-ASN.mmdb"

# Verify new databases
python3 << 'EOF'
from pathlib import Path
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient

try:
    client = MaxMindClient(db_path=Path("/mnt/dshield/data/cache/maxmind"))
    result = client.lookup_ip("8.8.8.8")
    if result and result.asn == 15169:
        print("✅ Database update successful")
        exit(0)
    else:
        print("❌ Database verification failed")
        exit(1)
except Exception as e:
    print(f"❌ Database update failed: {e}")
    exit(1)
EOF

if [ $? -eq 0 ]; then
    # Cleanup
    rm -f GeoLite2-City.tar.gz GeoLite2-ASN.tar.gz
    rm -f GeoLite2-City.mmdb.backup GeoLite2-ASN.mmdb.backup
    echo "Update complete"
else
    # Rollback
    mv GeoLite2-City.mmdb.backup GeoLite2-City.mmdb
    mv GeoLite2-ASN.mmdb.backup GeoLite2-ASN.mmdb
    echo "Update failed, rolled back"
    exit 1
fi
```

### Refresh Stale Data

```bash
#!/bin/bash
# Weekly stale data refresh
# Cron: 0 3 * * 0 (Sunday 3 AM)

echo "=== Stale Data Refresh ==="
date

# Refresh stale Cymru ASN data (>90 days)
python3 << 'EOF'
from pathlib import Path
from cowrieprocessor.db.engine import create_engine_from_settings, create_session_maker
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient
from cowrieprocessor.enrichment.cymru_client import CymruClient
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

# Initialize
settings = DatabaseSettings(url="postgresql://user:pass@host/db")
engine = create_engine_from_settings(settings)
SessionMaker = create_session_maker(engine)

cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
maxmind = MaxMindClient(db_path=Path("/mnt/dshield/data/cache/maxmind"))
cymru = CymruClient(cache=cache, ttl_days=90)
greynoise = GreyNoiseClient(api_key="$GREYNOISE_API_KEY", cache=cache, ttl_days=7)

# Refresh in batches
with SessionMaker() as session:
    cascade = CascadeEnricher(maxmind, cymru, greynoise, session)

    # Cymru refresh
    total_cymru = 0
    while True:
        stats = cascade.refresh_stale_data(source="cymru", limit=1000)
        count = stats['cymru_refreshed']
        total_cymru += count
        print(f"Cymru: {count} refreshed (total: {total_cymru})")
        session.commit()

        if count < 1000:
            break

    # GreyNoise refresh
    total_gn = 0
    while True:
        stats = cascade.refresh_stale_data(source="greynoise", limit=500)
        count = stats['greynoise_refreshed']
        total_gn += count
        print(f"GreyNoise: {count} refreshed (total: {total_gn})")
        session.commit()

        if count < 500:
            break

    print(f"Total refreshed: Cymru={total_cymru}, GreyNoise={total_gn}")
EOF
```

## Monthly Reports

### Enrichment Coverage Report

```bash
#!/bin/bash
# Monthly enrichment coverage report
# Cron: 0 9 1 * * (1st day of month, 9 AM)

echo "=== Monthly Enrichment Report ==="
echo "Period: $(date -d '1 month ago' +'%B %Y')"
echo

psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" << 'SQL'
-- Overall coverage
WITH coverage AS (
    SELECT
        COUNT(*) as total_ips,
        COUNT(asn_number) as with_asn,
        COUNT(geo_country) as with_geo,
        COUNT(CASE WHEN is_scanner THEN 1 END) as scanners,
        COUNT(CASE WHEN enrichment->>'greynoise'->>'riot' = 'true' THEN 1 END) as riot
    FROM ip_inventory
)
SELECT
    total_ips as "Total IPs",
    with_asn as "With ASN",
    ROUND(with_asn * 100.0 / total_ips, 2) || '%' as "ASN Coverage",
    with_geo as "With Geo",
    ROUND(with_geo * 100.0 / total_ips, 2) || '%' as "Geo Coverage",
    scanners as "Scanners",
    riot as "RIOT Services"
FROM coverage;

-- Source breakdown
SELECT
    asn_source as "ASN Source",
    COUNT(*) as "Count",
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM ip_inventory WHERE asn_number IS NOT NULL), 2) || '%' as "Percentage"
FROM ip_inventory
WHERE asn_number IS NOT NULL
GROUP BY asn_source
ORDER BY COUNT(*) DESC;

-- Top countries
SELECT
    geo_country as "Country",
    COUNT(*) as "Count"
FROM ip_inventory
WHERE geo_country IS NOT NULL
GROUP BY geo_country
ORDER BY COUNT(*) DESC
LIMIT 10;

-- Top ASNs
SELECT
    asn_number as "ASN",
    asn_org as "Organization",
    COUNT(*) as "IPs"
FROM ip_inventory
WHERE asn_number IS NOT NULL
GROUP BY asn_number, asn_org
ORDER BY COUNT(*) DESC
LIMIT 10;
SQL
```

## Incident Response

### MaxMind Database Corruption

**Symptoms**:
- `geoip2.errors.InvalidDatabaseError` exceptions
- Lookup failures returning None for all IPs

**Resolution**:
```bash
# 1. Restore from backup
cd /mnt/dshield/data/cache/maxmind
cp GeoLite2-City.mmdb.backup GeoLite2-City.mmdb
cp GeoLite2-ASN.mmdb.backup GeoLite2-ASN.mmdb

# 2. If no backup, re-download
rm -f GeoLite2-*.mmdb
wget "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-City&license_key=$MAXMIND_LICENSE_KEY&suffix=tar.gz" -O GeoLite2-City.tar.gz
tar -xzf GeoLite2-City.tar.gz --strip-components=1 "*/GeoLite2-City.mmdb"

# 3. Verify
python3 -c "
from pathlib import Path
from cowrieprocessor.enrichment.maxmind_client import MaxMindClient
client = MaxMindClient(db_path=Path('/mnt/dshield/data/cache/maxmind'))
result = client.lookup_ip('8.8.8.8')
print(f'✅ Verified: {result.country_name}' if result else '❌ Failed')
"
```

### Team Cymru Null-Routing

**Symptoms**:
- All Cymru queries timing out
- No ASN data for IPs missing MaxMind ASN

**Cause**: Abuse of HTTP API (we use netcat, but verify)

**Resolution**:
```bash
# 1. Verify netcat interface usage
grep -r "requests.post.*cymru" cowrieprocessor/enrichment/
# Should return nothing (we use socket, not requests)

# 2. Test netcat connectivity
echo -e "begin\nverbose\n8.8.8.8\nend" | nc whois.cymru.com 43
# Should return ASN data

# 3. If null-routed, contact Team Cymru
# Email: team-cymru-admin@cymru.com
# Subject: "IP Null-Routing - Request Review"
# Explain: Using official netcat interface, not HTTP abuse
```

### GreyNoise Quota Exceeded Early

**Symptoms**:
- GreyNoise quota 0 before midnight UTC
- No scanner classifications for new IPs

**Cause**: Unexpected traffic spike or incorrect quota tracking

**Resolution**:
```bash
# 1. Check quota tracking
python3 << 'EOF'
from pathlib import Path
from cowrieprocessor.enrichment.greynoise_client import GreyNoiseClient
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager

cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
client = GreyNoiseClient(api_key="$GREYNOISE_API_KEY", cache=cache, ttl_days=7)

remaining = client.get_remaining_quota()
print(f"Remaining: {remaining}/10000")

# Check when it resets
import datetime
now = datetime.datetime.now(datetime.timezone.utc)
midnight = now.replace(hour=0, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)
print(f"Resets in: {(midnight - now).seconds // 3600} hours")
EOF

# 2. If incorrect, reset quota counter
python3 << 'EOF'
from pathlib import Path
from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
cache = EnrichmentCacheManager(cache_dir=Path("/mnt/dshield/data/cache"))
# Reset quota (stored in cache with date key)
# Counter will reset automatically at midnight UTC
EOF

# 3. System continues to function (cascade degrades gracefully)
# GreyNoise is optional, MaxMind + Cymru still provide core enrichment
```

## Performance Tuning

### Slow Enrichment

**Diagnosis**:
```python
# Profile cascade performance
import time
from cowrieprocessor.enrichment.cascade_enricher import CascadeEnricher

start = time.time()
inventory = cascade.enrich_ip("8.8.8.8")
elapsed = time.time() - start

print(f"Total time: {elapsed*1000:.1f}ms")
print(f"MaxMind: {maxmind.get_stats()['avg_latency']*1000:.1f}ms")
print(f"Cymru: {cymru.get_stats()['avg_latency']*1000:.1f}ms")
print(f"GreyNoise: {greynoise.get_stats()['avg_latency']*1000:.1f}ms")
```

**Common Issues**:
1. **MaxMind database not cached in memory**: First lookup slow (~50ms), subsequent fast (<5ms)
2. **Cymru DNS timeout**: Increase timeout from 30s to 60s
3. **GreyNoise API slow**: Check network latency to `api.greynoise.io`
4. **Database locks**: PostgreSQL row-level locks during concurrent enrichment

**Optimization**:
```python
# Use connection pooling
from cowrieprocessor.db.engine import create_engine_from_settings
engine = create_engine_from_settings(settings)
# Pool size = CPU count * 2
engine.pool_size = 20

# Batch process
for session_id in session_ids:
    cascade.enrich_session_ips(session_id)
    session.commit()
```

### High Memory Usage

**Diagnosis**:
```bash
# Check MaxMind memory usage
ps aux | grep python | awk '{print $6/1024 "MB\t" $11}'

# Expected: ~250MB (both MaxMind databases + Python overhead)
```

**Optimization**:
```python
# Close MaxMind readers when not in use
with MaxMindClient(db_path=Path("/mnt/dshield/data/cache/maxmind")) as client:
    result = client.lookup_ip("8.8.8.8")
# Readers closed automatically
```

## Backup and Recovery

### Backup Enrichment Data

```bash
#!/bin/bash
# Daily enrichment database backup
# Cron: 0 1 * * * (1 AM daily)

BACKUP_DIR="/mnt/dshield/backups/enrichment"
DATE=$(date +%Y%m%d)

mkdir -p "$BACKUP_DIR"

# Backup ip_inventory table
pg_dump -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" \
    -t ip_inventory \
    -f "$BACKUP_DIR/ip_inventory_$DATE.sql"

# Backup MaxMind databases
tar -czf "$BACKUP_DIR/maxmind_$DATE.tar.gz" \
    -C /mnt/dshield/data/cache/maxmind \
    GeoLite2-City.mmdb GeoLite2-ASN.mmdb

# Cleanup old backups (keep 7 days)
find "$BACKUP_DIR" -name "*.sql" -mtime +7 -delete
find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete

echo "Backup complete: $DATE"
```

### Restore from Backup

```bash
#!/bin/bash
# Restore enrichment data from backup

BACKUP_DATE=${1:-$(date +%Y%m%d)}
BACKUP_DIR="/mnt/dshield/backups/enrichment"

echo "Restoring from backup: $BACKUP_DATE"

# Restore ip_inventory table
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" << SQL
BEGIN;
TRUNCATE TABLE ip_inventory CASCADE;
\i $BACKUP_DIR/ip_inventory_$BACKUP_DATE.sql
COMMIT;
SQL

# Restore MaxMind databases
tar -xzf "$BACKUP_DIR/maxmind_$BACKUP_DATE.tar.gz" \
    -C /mnt/dshield/data/cache/maxmind

echo "Restore complete"
```

## Contact Information

**On-Call Engineer**: ops@example.com
**Team Cymru Support**: team-cymru-admin@cymru.com
**MaxMind Support**: https://support.maxmind.com
**GreyNoise Support**: support@greynoise.io

## Related Documentation

- [Multi-Source Cascade Guide](../enrichment/multi-source-cascade-guide.md)
- [ADR-008: Multi-Source Enrichment Fallback](../ADR/008-multi-source-enrichment-fallback.md)
- [Monitoring and Alerting](./monitoring.md)
