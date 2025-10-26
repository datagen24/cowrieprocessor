#!/usr/bin/env python3
"""Refresh indicator cache (VT/IP) and reindex recent reports via the ORM pipeline.

This script:
 - Refreshes indicator_cache entries and seeds missing ones from the DB
 - Respects TTLs for known vs. unknown VT hashes and IP lookups
 - Applies request timeouts, retries with exponential backoff, and simple rate limits
 - Re-generates recent daily/weekly/monthly reports within the configured hot windows

Credentials for services are provided via CLI flags. Elasticsearch credentials are
picked up by the reporting CLI via environment variables or flags (not handled here).
"""

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta
from typing import Any, Optional

import requests
from secrets_resolver import is_reference, resolve_secret


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for cache/report refresh."""
    ap = argparse.ArgumentParser(description="Refresh indicator cache and recent ES reports")
    ap.add_argument('--db', required=True, help='Path to central SQLite database')

    # Services
    ap.add_argument('--vtapi', help='VirusTotal API key')
    ap.add_argument('--email', help='Email for DShield')
    ap.add_argument('--urlhausapi', help='URLhaus API key')
    ap.add_argument('--spurapi', help='SPUR.us API key')

    # Request behavior
    ap.add_argument('--api-timeout', type=int, default=15)
    ap.add_argument('--api-retries', type=int, default=3)
    ap.add_argument('--api-backoff', type=float, default=2.0)
    ap.add_argument('--rate-vt', type=int, default=4)
    ap.add_argument('--rate-dshield', type=int, default=30)
    ap.add_argument('--rate-urlhaus', type=int, default=30)
    ap.add_argument('--rate-spur', type=int, default=30)

    # TTLs
    ap.add_argument('--hash-ttl-days', type=int, default=30)
    ap.add_argument('--hash-unknown-ttl-hours', type=int, default=12)
    ap.add_argument('--ip-ttl-hours', type=int, default=12)

    # What to refresh
    ap.add_argument('--refresh-indicators', choices=['all', 'vt', 'ips', 'none'], default='all')
    ap.add_argument('--refresh-reports', choices=['all', 'daily', 'weekly', 'monthly', 'none'], default='all')

    # Hot windows (matches ILM)
    ap.add_argument('--hot-daily-days', type=int, default=7)
    ap.add_argument('--hot-weekly-days', type=int, default=30)
    ap.add_argument('--hot-monthly-days', type=int, default=90)

    return ap.parse_args()


def setup_db(db_path: str) -> sqlite3.Connection:
    """Open SQLite connection with busy timeout and Row factory."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=5000')
    return conn


def ensure_indicator_table(conn: sqlite3.Connection) -> None:
    """Ensure indicator_cache table exists."""
    conn.execute(
        'CREATE TABLE IF NOT EXISTS indicator_cache('
        ' service text, key text, last_fetched int, data text, PRIMARY KEY (service, key))'
    )
    conn.commit()


class Refresher:
    """Service refresher for indicator cache with rate limiting and retries."""

    def __init__(self, args: argparse.Namespace, conn: sqlite3.Connection) -> None:
        """Initialize refresher with args and SQLite connection."""
        self.args = args
        self.conn = conn
        self.vt = requests.Session()
        self.dshield = requests.Session()
        self.uh = requests.Session()
        self.spur = requests.Session()
        self.last_req = {'vt': 0.0, 'dshield': 0.0, 'urlhaus': 0.0, 'spur': 0.0}

    def rate_limit(self, service: str) -> None:
        """Enforce per-service requests-per-minute limits."""
        now = time.time()
        per_min = getattr(self.args, f'rate_{service}')
        if per_min <= 0:
            return
        min_interval = 60.0 / float(per_min)
        elapsed = now - self.last_req.get(service, 0.0)
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        self.last_req[service] = time.time()

    def cache_get(self, service: str, key: str) -> Optional[Any]:
        """Get cache row (last_fetched, data) for service/key."""
        cur = self.conn.cursor()
        cur.execute('SELECT last_fetched, data FROM indicator_cache WHERE service=? AND key=?', (service, key))
        return cur.fetchone()

    def cache_upsert(self, service: str, key: str, data: str) -> None:
        """Upsert cache row for service/key with data and current timestamp."""
        cur = self.conn.cursor()
        cur.execute(
            'INSERT INTO indicator_cache(service, key, last_fetched, data) VALUES (?,?,?,?) '
            'ON CONFLICT(service, key) DO UPDATE SET last_fetched=excluded.last_fetched, data=excluded.data',
            (service, key, int(time.time()), data),
        )
        self.conn.commit()

    def should_refresh_vt(self, key: str, row: Optional[Any]) -> bool:
        """Decide if VT record should be refreshed based on TTL and unknown state."""
        if not row:
            return True
        last, data = row
        ttl = self.args.hash_ttl_days * 86400
        try:
            js = json.loads(data) if data else {}
            is_unknown = (not isinstance(js, dict)) or ('data' not in js) or ('error' in js)
            if is_unknown:
                ttl = self.args.hash_unknown_ttl_hours * 3600
        except Exception:
            ttl = self.args.hash_unknown_ttl_hours * 3600
        return bool((time.time() - last) >= ttl)

    def should_refresh_ip(self, row: Optional[Any]) -> bool:
        """Decide if IP-based record should be refreshed based on TTL."""
        if not row:
            return True
        last, _ = row
        ttl = self.args.ip_ttl_hours * 3600
        return bool((time.time() - last) >= ttl)

    def refresh_vt(self, hash_: str) -> None:
        """Refresh VT cache entry for a file hash."""
        if not self.args.vtapi:
            return
        url = f"https://www.virustotal.com/api/v3/files/{hash_}"
        self.vt.headers.update({'X-Apikey': self.args.vtapi})
        attempt = 0
        while attempt < self.args.api_retries:
            attempt += 1
            try:
                self.rate_limit('vt')
                r = self.vt.get(url, timeout=self.args.api_timeout)
                if r.status_code == 429:
                    time.sleep(self.args.api_backoff * attempt)
                    continue
                if r.status_code == 404:
                    self.cache_upsert('vt_file', hash_, json.dumps({"error": "not_found"}))
                    return
                r.raise_for_status()
                self.cache_upsert('vt_file', hash_, r.text)
                return
            except Exception:
                time.sleep(self.args.api_backoff * attempt)

    def refresh_dshield(self, ip: str) -> None:
        """Refresh DShield cache entry for an IP."""
        if not self.args.email:
            return
        base_url = f"https://isc.sans.edu/api/ip/{ip}?json"
        if self.args.email:
            url = f"{base_url}&email={self.args.email}"
        else:
            url = base_url
        attempt = 0
        while attempt < self.args.api_retries:
            attempt += 1
            try:
                self.rate_limit('dshield')
                headers = {"User-Agent": f"DShield Research Query by {self.args.email}"}
                r = self.dshield.get(url, headers=headers, timeout=self.args.api_timeout)
                if r.status_code == 429:
                    time.sleep(self.args.api_backoff * attempt)
                    continue
                r.raise_for_status()
                self.cache_upsert('dshield_ip', ip, r.text)
                return
            except Exception:
                time.sleep(self.args.api_backoff * attempt)

    def refresh_urlhaus(self, host: str) -> None:
        """Refresh URLhaus cache entry for a host/IP."""
        if not self.args.urlhausapi:
            return
        url = "https://urlhaus-api.abuse.ch/v1/host/"
        attempt = 0
        while attempt < self.args.api_retries:
            attempt += 1
            try:
                self.rate_limit('urlhaus')
                r = self.uh.post(
                    url,
                    headers={'Auth-Key': self.args.urlhausapi},
                    data={'host': host},
                    timeout=self.args.api_timeout,
                )
                if r.status_code == 429:
                    time.sleep(self.args.api_backoff * attempt)
                    continue
                r.raise_for_status()
                self.cache_upsert('urlhaus_ip', host, r.text)
                return
            except Exception:
                time.sleep(self.args.api_backoff * attempt)

    def refresh_spur(self, ip: str) -> None:
        """Refresh SPUR cache entry for an IP."""
        if not self.args.spurapi:
            return
        url = f"https://api.spur.us/v2/context/{ip}"
        self.spur.headers.update({'Token': self.args.spurapi})
        attempt = 0
        while attempt < self.args.api_retries:
            attempt += 1
            try:
                self.rate_limit('spur')
                r = self.spur.get(url, timeout=self.args.api_timeout)
                if r.status_code == 429:
                    time.sleep(self.args.api_backoff * attempt)
                    continue
                r.raise_for_status()
                self.cache_upsert('spur_ip', ip, r.text)
                return
            except Exception:
                time.sleep(self.args.api_backoff * attempt)

    def seed_missing(self) -> None:
        """Seed cache with DB-observed hashes and IPs missing from cache."""
        # Seed missing VT hashes from files table
        cur = self.conn.cursor()
        cur.execute('''SELECT DISTINCT hash FROM files WHERE hash IS NOT NULL AND hash != '' ''')
        hashes = [row['hash'] for row in cur.fetchall()]
        for h in hashes:
            if not self.cache_get('vt_file', h):
                self.refresh_vt(h)

        # Seed IPs from sessions/files
        cur.execute("SELECT DISTINCT source_ip as ip FROM sessions WHERE source_ip IS NOT NULL AND source_ip != ''")
        ips = {row['ip'] for row in cur.fetchall()}
        cur.execute("SELECT DISTINCT src_ip as ip FROM files WHERE src_ip IS NOT NULL AND src_ip != ''")
        ips |= {row['ip'] for row in cur.fetchall()}
        for ip in ips:
            if not self.cache_get('dshield_ip', ip):
                self.refresh_dshield(ip)
            if not self.cache_get('urlhaus_ip', ip):
                self.refresh_urlhaus(ip)
            if not self.cache_get('spur_ip', ip):
                self.refresh_spur(ip)

    def refresh_stale(self) -> None:
        """Refresh any cache entries that are stale by TTL."""
        # VT
        if self.args.refresh_indicators in ('all', 'vt'):
            cur = self.conn.cursor()
            cur.execute("SELECT key, last_fetched, data FROM indicator_cache WHERE service='vt_file'")
            for row in cur.fetchall():
                key = row['key']
                if self.should_refresh_vt(key, (row['last_fetched'], row['data'])):
                    self.refresh_vt(key)

        # IPs
        if self.args.refresh_indicators in ('all', 'ips'):
            for svc in ('dshield_ip', 'urlhaus_ip', 'spur_ip'):
                cur = self.conn.cursor()
                cur.execute("SELECT key, last_fetched FROM indicator_cache WHERE service=?", (svc,))
                for row in cur.fetchall():
                    key = row['key']
                    stale = self.should_refresh_ip((row['last_fetched'], None))
                    if not stale:
                        continue
                    if svc == 'dshield_ip':
                        self.refresh_dshield(key)
                    elif svc == 'urlhaus_ip':
                        self.refresh_urlhaus(key)
                    elif svc == 'spur_ip':
                        self.refresh_spur(key)


def refresh_reports(db_path: str, args: argparse.Namespace) -> None:
    """Rebuild recent daily/weekly/monthly reports within hot windows."""
    # Daily for last N days
    if args.refresh_reports in ('all', 'daily'):
        for i in range(args.hot_daily_days):
            date_str = (datetime.utcnow() - timedelta(days=i)).strftime('%Y-%m-%d')
            subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'cowrieprocessor.cli.report',
                    'daily',
                    date_str,
                    '--all-sensors',
                    '--db',
                    db_path,
                    '--publish',
                ],
                check=False,
            )

    # Weekly covering last hot_weekly_days
    if args.refresh_reports in ('all', 'weekly'):
        start = datetime.utcnow() - timedelta(days=args.hot_weekly_days - 1)
        end = datetime.utcnow()
        curr = start
        seen = set()
        while curr <= end:
            iso_year, iso_week, _ = curr.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
            if key not in seen:
                subprocess.run(
                    [
                        sys.executable,
                        '-m',
                        'cowrieprocessor.cli.report',
                        'weekly',
                        key,
                        '--db',
                        db_path,
                        '--publish',
                    ],
                    check=False,
                )
                seen.add(key)
            curr += timedelta(days=1)

    # Monthly covering last hot_monthly_days
    if args.refresh_reports in ('all', 'monthly'):
        start = datetime.utcnow() - timedelta(days=args.hot_monthly_days - 1)
        months = set()
        for i in range(args.hot_monthly_days):
            d = datetime.utcnow() - timedelta(days=i)
            months.add(d.strftime('%Y-%m'))
        for ym in sorted(months):
            subprocess.run(
                [
                    sys.executable,
                    '-m',
                    'cowrieprocessor.cli.report',
                    'monthly',
                    ym,
                    '--db',
                    db_path,
                    '--publish',
                ],
                check=False,
            )


def main() -> None:
    """Module entrypoint."""
    args = parse_args()
    # Secrets: allow environment fallbacks
    args.vtapi = args.vtapi or os.getenv('VT_API_KEY')
    args.email = args.email or os.getenv('DSHIELD_EMAIL')
    args.urlhausapi = args.urlhausapi or os.getenv('URLHAUS_API_KEY')
    args.spurapi = args.spurapi or os.getenv('SPUR_API_KEY')
    # Resolve secret references if provided directly
    try:
        for k in ("vtapi", "email", "urlhausapi", "spurapi"):
            v = getattr(args, k)
            if is_reference(v):
                setattr(args, k, resolve_secret(v))
    except Exception:
        pass
    conn = setup_db(args.db)
    ensure_indicator_table(conn)

    refresher = Refresher(args, conn)

    if args.refresh_indicators != 'none':
        refresher.seed_missing()
        refresher.refresh_stale()

    if args.refresh_reports != 'none':
        refresh_reports(args.db, args)

    print("Refresh complete")


if __name__ == '__main__':
    main()
