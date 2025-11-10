# IP Classification Data Source Updates

## Overview

The IP classification module requires periodic updates to external data sources to maintain classification accuracy. This document describes the data sources, update frequencies, and recommended automation setup.

## Data Sources

### 1. TOR Exit Nodes
**Provider**: The Tor Project
**URL**: https://check.torproject.org/torbulkexitlist
**Format**: Plain text, one IPv4/IPv6 per line
**Update Frequency**: **Hourly** (TOR exit nodes change frequently)
**Criticality**: High (95% confidence classification)

### 2. Cloud Provider IP Ranges
**Provider**: rezmoss/cloud-provider-ip-addresses (GitHub)
**Base URL**: https://raw.githubusercontent.com/rezmoss/cloud-provider-ip-addresses/main
**Providers**:
- AWS: `aws/aws_ips_v4.txt`
- Azure: `azure/azure_ips_v4.txt`
- GCP: `gcp/gcp_ips_v4.txt`
- Cloudflare: `cloudflare/cloudflare_ips_v4.txt`

**Format**: Plain text, one CIDR per line
**Update Frequency**: **Daily** (cloud providers publish IP range changes daily)
**Criticality**: High (99% confidence classification)

### 3. Datacenter IP Ranges
**Provider**: jhassine/server-ip-addresses (GitHub)
**URL**: https://raw.githubusercontent.com/jhassine/server-ip-addresses/main/data/datacenters.csv
**Providers**: DigitalOcean, Linode, OVH, Hetzner, Vultr
**Format**: CSV with `provider,cidr` columns
**Update Frequency**: **Weekly** (datacenter ranges relatively stable)
**Criticality**: Medium (75% confidence classification)

## Automation Setup

### Cron Job Configuration

Create `/etc/cron.d/ip-classification-updates`:

```bash
# IP Classification Data Source Updates
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
PYTHONPATH=/mnt/dshield/cowrieprocessor

# TOR exit nodes - Hourly updates (at minute 15)
15 * * * * dshield cd /mnt/dshield/cowrieprocessor && /usr/local/bin/uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; classifier = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); classifier.tor_matcher._download_data()" >> /var/log/ip-classification/tor-update.log 2>&1

# Cloud provider ranges - Daily updates (at 3:00 AM)
0 3 * * * dshield cd /mnt/dshield/cowrieprocessor && /usr/local/bin/uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; classifier = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); classifier.cloud_matcher._download_data()" >> /var/log/ip-classification/cloud-update.log 2>&1

# Datacenter ranges - Weekly updates (Sunday at 4:00 AM)
0 4 * * 0 dshield cd /mnt/dshield/cowrieprocessor && /usr/local/bin/uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; classifier = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); classifier.datacenter_matcher._download_data()" >> /var/log/ip-classification/datacenter-update.log 2>&1

# Full update (all sources) - Monthly (1st day at 5:00 AM)
0 5 1 * * dshield cd /mnt/dshield/cowrieprocessor && /usr/local/bin/uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; classifier = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); classifier.update_all_sources()" >> /var/log/ip-classification/full-update.log 2>&1
```

### Alternative: Python Script Automation

Create `/mnt/dshield/scripts/update_ip_classification_data.py`:

```python
#!/usr/bin/env python3
"""Update IP classification data sources.

Usage:
    python update_ip_classification_data.py --source tor
    python update_ip_classification_data.py --source cloud
    python update_ip_classification_data.py --source datacenter
    python update_ip_classification_data.py --source all
"""
import argparse
import logging
import sys
from pathlib import Path

from cowrieprocessor.db.engine import get_engine
from cowrieprocessor.enrichment.ip_classification import create_ip_classifier

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
)
logger = logging.getLogger(__name__)


def update_tor(classifier):
    """Update TOR exit node list."""
    logger.info("Updating TOR exit node list...")
    try:
        classifier.tor_matcher._download_data()
        stats = classifier.tor_matcher.get_stats()
        logger.info(f"TOR update complete: {stats['total_ips']} exit nodes loaded")
    except Exception as e:
        logger.error(f"TOR update failed: {e}")
        return False
    return True


def update_cloud(classifier):
    """Update cloud provider IP ranges."""
    logger.info("Updating cloud provider IP ranges...")
    try:
        classifier.cloud_matcher._download_data()
        stats = classifier.cloud_matcher.get_stats()
        logger.info(f"Cloud update complete: {sum(stats['ranges_per_provider'].values())} ranges loaded")
    except Exception as e:
        logger.error(f"Cloud update failed: {e}")
        return False
    return True


def update_datacenter(classifier):
    """Update datacenter IP ranges."""
    logger.info("Updating datacenter IP ranges...")
    try:
        classifier.datacenter_matcher._download_data()
        stats = classifier.datacenter_matcher.get_stats()
        logger.info(f"Datacenter update complete: {sum(stats['ranges_per_provider'].values())} ranges loaded")
    except Exception as e:
        logger.error(f"Datacenter update failed: {e}")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description='Update IP classification data sources')
    parser.add_argument(
        '--source',
        choices=['tor', 'cloud', 'datacenter', 'all'],
        required=True,
        help='Data source to update',
    )
    parser.add_argument(
        '--cache-dir',
        type=Path,
        default=Path('/mnt/dshield/data/cache'),
        help='Cache directory for IP classification data',
    )
    parser.add_argument(
        '--database',
        default='postgresql://cowrieprocessor:password@localhost:5432/cowrieprocessor',  # pragma: allowlist secret
        help='Database connection string',
    )
    args = parser.parse_args()

    # Create classifier
    engine = get_engine(args.database)
    classifier = create_ip_classifier(
        cache_dir=args.cache_dir,
        db_engine=engine,
        enable_redis=False,  # Don't need Redis for data updates
    )

    # Update specified source(s)
    success = True
    if args.source == 'all':
        success &= update_tor(classifier)
        success &= update_cloud(classifier)
        success &= update_datacenter(classifier)
    elif args.source == 'tor':
        success = update_tor(classifier)
    elif args.source == 'cloud':
        success = update_cloud(classifier)
    elif args.source == 'datacenter':
        success = update_datacenter(classifier)

    classifier.close()
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
```

### Cron Jobs Using Python Script

```bash
# TOR - Hourly
15 * * * * dshield /usr/local/bin/uv run python /mnt/dshield/scripts/update_ip_classification_data.py --source tor >> /var/log/ip-classification/tor-update.log 2>&1

# Cloud - Daily at 3 AM
0 3 * * * dshield /usr/local/bin/uv run python /mnt/dshield/scripts/update_ip_classification_data.py --source cloud >> /var/log/ip-classification/cloud-update.log 2>&1

# Datacenter - Weekly (Sunday 4 AM)
0 4 * * 0 dshield /usr/local/bin/uv run python /mnt/dshield/scripts/update_ip_classification_data.py --source datacenter >> /var/log/ip-classification/datacenter-update.log 2>&1

# Full update - Monthly (1st at 5 AM)
0 5 1 * * dshield /usr/local/bin/uv run python /mnt/dshield/scripts/update_ip_classification_data.py --source all >> /var/log/ip-classification/full-update.log 2>&1
```

## Log Management

Create log rotation configuration `/etc/logrotate.d/ip-classification`:

```
/var/log/ip-classification/*.log {
    daily
    rotate 30
    compress
    delaycompress
    missingok
    notifempty
    create 0644 dshield dshield
    sharedscripts
    postrotate
        systemctl reload rsyslog > /dev/null 2>&1 || true
    endscript
}
```

## Monitoring

### Health Check Script

Create `/mnt/dshield/scripts/check_ip_classification_health.py`:

```python
#!/usr/bin/env python3
"""Health check for IP classification data sources."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cowrieprocessor.db.engine import get_engine
from cowrieprocessor.enrichment.ip_classification import create_ip_classifier


def check_data_freshness(classifier, cache_dir: Path):
    """Check if data sources are fresh enough."""
    issues = []

    # Check TOR (should be <2 hours old)
    tor_cache = cache_dir / "ip_classification" / "tor_exit_nodes.txt"
    if tor_cache.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            tor_cache.stat().st_mtime, tz=timezone.utc
        )
        if age > timedelta(hours=2):
            issues.append(f"TOR data is {age.total_seconds() / 3600:.1f} hours old (expected <2 hours)")
    else:
        issues.append("TOR data file not found")

    # Check Cloud (should be <2 days old)
    cloud_cache = cache_dir / "ip_classification" / "cloud_aws.txt"
    if cloud_cache.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            cloud_cache.stat().st_mtime, tz=timezone.utc
        )
        if age > timedelta(days=2):
            issues.append(f"Cloud data is {age.days} days old (expected <2 days)")
    else:
        issues.append("Cloud data files not found")

    # Check Datacenter (should be <14 days old)
    datacenter_cache = cache_dir / "ip_classification" / "datacenters.csv"
    if datacenter_cache.exists():
        age = datetime.now(timezone.utc) - datetime.fromtimestamp(
            datacenter_cache.stat().st_mtime, tz=timezone.utc
        )
        if age > timedelta(days=14):
            issues.append(f"Datacenter data is {age.days} days old (expected <14 days)")
    else:
        issues.append("Datacenter data file not found")

    return issues


def main():
    cache_dir = Path('/mnt/dshield/data/cache')
    engine = get_engine('postgresql://cowrieprocessor:password@localhost:5432/cowrieprocessor')  # pragma: allowlist secret
    classifier = create_ip_classifier(cache_dir=cache_dir, db_engine=engine, enable_redis=False)

    issues = check_data_freshness(classifier, cache_dir)

    if issues:
        print("❌ IP Classification Health Check FAILED:")
        for issue in issues:
            print(f"  - {issue}")
        classifier.close()
        return 1
    else:
        print("✅ IP Classification Health Check PASSED")
        classifier.close()
        return 0


if __name__ == '__main__':
    sys.exit(main())
```

### Monitoring Cron Job

```bash
# Health check every 6 hours
0 */6 * * * dshield /usr/local/bin/uv run python /mnt/dshield/scripts/check_ip_classification_health.py || echo "IP Classification health check failed" | mail -s "Alert: IP Classification Health Check Failed" admin@example.com
```

## Error Handling

### Network Failures
All data source updates include retry logic with exponential backoff. If downloads fail:
1. **First failure**: Log warning, keep using cached data
2. **Second failure**: Log error, alert if data >24 hours old
3. **Third failure**: Classify as UNKNOWN with 0% confidence

### Stale Data Handling
- **TOR**: Data >4 hours old triggers warning, >24 hours triggers error
- **Cloud**: Data >3 days old triggers warning, >7 days triggers error
- **Datacenter**: Data >30 days old triggers warning, >90 days triggers error

### Disk Space Management
Data files are relatively small:
- TOR exit nodes: ~100 KB (1,000-2,000 IPs)
- Cloud ranges (all providers): ~2 MB (20,000-30,000 CIDRs)
- Datacenter ranges: ~500 KB (5,000-10,000 CIDRs)

Total disk usage: **~3 MB** per version, **~100 MB** with 30-day retention.

## Manual Updates

To manually update data sources:

```bash
# Update TOR only
uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; c = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); c.tor_matcher._download_data()"

# Update all sources
uv run python -c "from cowrieprocessor.enrichment.ip_classification import create_ip_classifier; from pathlib import Path; from cowrieprocessor.db.engine import get_engine; c = create_ip_classifier(cache_dir=Path('/mnt/dshield/data/cache'), db_engine=get_engine('postgresql://...')); c.update_all_sources()"

# Using Python script
uv run python /mnt/dshield/scripts/update_ip_classification_data.py --source all
```

## Rollback Procedure

If a data update causes classification issues:

```bash
# Restore previous version from disk cache
cd /mnt/dshield/data/cache/ip_classification
cp tor_exit_nodes.txt.backup tor_exit_nodes.txt
cp cloud_*.txt.backup cloud_*.txt
cp datacenters.csv.backup datacenters.csv

# Restart classifier to reload data
systemctl restart cowrieprocessor  # Or equivalent service
```

## Performance Impact

Data source updates are designed to be non-blocking:
- **Download time**: 5-30 seconds depending on network
- **Parse time**: <1 second for all sources combined
- **Memory impact**: ~50 MB additional during update
- **Classifier availability**: 100% (no downtime during updates)

Updates use atomic file replacement to ensure the classifier never sees partially downloaded data.

## References

- **ADR-008**: IP Classification Architecture
- **ADR-007**: Three-Tier Enrichment
- [TOR Project Exit List](https://check.torproject.org/torbulkexitlist)
- [Cloud Provider IP Addresses](https://github.com/rezmoss/cloud-provider-ip-addresses)
- [Server IP Addresses](https://github.com/jhassine/server-ip-addresses)
