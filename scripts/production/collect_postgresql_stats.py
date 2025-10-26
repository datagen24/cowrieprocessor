#!/usr/bin/env python3
"""PostgreSQL stats collector that integrates with the existing status emitter system.

This collects database performance metrics and writes them to the same status files.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import SQLAlchemyError

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings, load_database_settings


class PostgreSQLStatsCollector:
    """Collect PostgreSQL statistics and integrate with status emitter."""

    def __init__(self, engine: Engine, status_file: Optional[Path] = None):
        """Initialize the PostgreSQL stats collector."""
        self.engine = engine
        self.status_file = status_file or Path("postgresql_stats.json")
        self.last_stats: Dict[str, Any] = {}

    def get_postgresql_stats(self) -> Dict[str, Any]:
        """Get comprehensive PostgreSQL statistics."""
        try:
            with self.engine.connect() as conn:
                stats = {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'database_size': self._get_database_size(conn),
                    'table_stats': self._get_table_stats(conn),
                    'connections': self._get_connection_stats(conn),
                    'loading_performance': self._get_loading_performance(conn),
                    'system_stats': self._get_system_stats(conn),
                }
                return stats
        except SQLAlchemyError as e:
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e),
                'database_size': None,
                'table_stats': {},
                'connections': {},
                'loading_performance': {},
                'system_stats': {},
            }

    def _get_database_size(self, conn: Connection) -> Dict[str, Any]:
        """Get database size information."""
        try:
            query = text("""
                SELECT 
                    pg_size_pretty(pg_database_size(current_database())) as size_pretty,
                    pg_database_size(current_database()) as size_bytes
            """)
            result = conn.execute(query)
            row = result.fetchone()
            if row:
                return {'size_pretty': row.size_pretty, 'size_bytes': row.size_bytes}
            return {'size_pretty': 'Unknown', 'size_bytes': 0}
        except Exception:
            return {'size_pretty': 'Unknown', 'size_bytes': 0}

    def _get_table_stats(self, conn: Connection) -> Dict[str, Any]:
        """Get table statistics."""
        try:
            query = text("""
                SELECT 
                    tablename,
                    n_tup_ins as total_inserts,
                    n_tup_upd as total_updates,
                    n_tup_del as total_deletes,
                    n_live_tup as live_tuples,
                    n_dead_tup as dead_tuples
                FROM pg_stat_user_tables 
                WHERE schemaname = 'public'
                ORDER BY n_tup_ins DESC
            """)

            result = conn.execute(query)
            table_stats = {}
            total_inserts = 0

            for row in result:
                table_stats[row.tablename] = {
                    'total_inserts': row.total_inserts or 0,
                    'total_updates': row.total_updates or 0,
                    'total_deletes': row.total_deletes or 0,
                    'live_tuples': row.live_tuples or 0,
                    'dead_tuples': row.dead_tuples or 0,
                }
                total_inserts += row.total_inserts or 0

            return {'tables': table_stats, 'total_inserts': total_inserts}
        except Exception:
            return {'tables': {}, 'total_inserts': 0}

    def _get_connection_stats(self, conn: Connection) -> Dict[str, Any]:
        """Get connection statistics."""
        try:
            query = text("""
                SELECT 
                    count(*) as total_connections,
                    count(*) FILTER (WHERE state = 'active') as active_connections,
                    count(*) FILTER (WHERE state = 'idle') as idle_connections,
                    count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
                FROM pg_stat_activity 
                WHERE datname = current_database()
            """)

            result = conn.execute(query)
            row = result.fetchone()

            return {
                'total': row.total_connections if row else 0,
                'active': row.active_connections if row else 0,
                'idle': row.idle_connections if row else 0,
                'idle_in_transaction': row.idle_in_transaction if row else 0,
            }
        except Exception:
            return {'total': 0, 'active': 0, 'idle': 0, 'idle_in_transaction': 0}

    def _get_loading_performance(self, conn: Connection) -> Dict[str, Any]:
        """Calculate loading performance metrics."""
        current_stats = self._get_table_stats(conn)

        if not self.last_stats:
            self.last_stats = current_stats
            return {'tuples_per_second': 0, 'status': 'initializing'}

        # Calculate deltas
        inserts_delta = current_stats['total_inserts'] - self.last_stats['total_inserts']
        time_delta = 5.0  # Assume 5-second intervals

        tuples_per_second = inserts_delta / time_delta if time_delta > 0 else 0

        self.last_stats = current_stats

        return {'tuples_per_second': tuples_per_second, 'inserts_delta': inserts_delta, 'status': 'active'}

    def _get_system_stats(self, conn: Connection) -> Dict[str, Any]:
        """Get system-level statistics."""
        try:
            # WAL stats
            wal_query = text("""
                SELECT 
                    wal_records,
                    wal_bytes,
                    wal_write,
                    wal_sync
                FROM pg_stat_wal
            """)

            result = conn.execute(wal_query)
            wal_row = result.fetchone()

            return {
                'wal': {
                    'records': wal_row.wal_records if wal_row else 0,
                    'bytes': wal_row.wal_bytes if wal_row else 0,
                    'write': wal_row.wal_write if wal_row else 0,
                    'sync': wal_row.wal_sync if wal_row else 0,
                }
            }
        except Exception:
            return {'wal': {'records': 0, 'bytes': 0, 'write': 0, 'sync': 0}}

    def write_stats_to_file(self, stats: Dict[str, Any]) -> None:
        """Write stats to the status file."""
        try:
            with self.status_file.open('w') as f:
                json.dump(stats, f, indent=2, default=str)
        except Exception as e:
            print(f"Error writing stats: {e}")

    def collect_and_write(self) -> Dict[str, Any]:
        """Collect stats and write to file."""
        stats = self.get_postgresql_stats()
        self.write_stats_to_file(stats)
        return stats


def monitor_postgresql_stats(engine: Engine, interval: int = 5, status_file: Optional[Path] = None) -> None:
    """Monitor PostgreSQL stats and write to status file."""
    collector = PostgreSQLStatsCollector(engine, status_file)

    print("🚀 PostgreSQL Stats Collector Started")
    print(f"📊 Collecting stats every {interval} seconds")
    print(f"📄 Writing to: {collector.status_file}")
    print("=" * 60)

    try:
        while True:
            stats = collector.collect_and_write()

            # Print key metrics
            perf = stats.get('loading_performance', {})
            db_size = stats.get('database_size', {})
            conns = stats.get('connections', {})

            print(f"\n⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')}")

            if perf.get('status') != 'initializing':
                print(f"📈 Loading Rate: {perf.get('tuples_per_second', 0):,.0f} tuples/second")

            print(f"💾 Database Size: {db_size.get('size_pretty', 'Unknown')}")
            print(f"🔗 Connections: {conns.get('active', 0)}/{conns.get('total', 0)}")

            # Show top tables
            table_stats = stats.get('table_stats', {}).get('tables', {})
            if table_stats:
                print("📋 Top Tables:")
                for table, data in list(table_stats.items())[:3]:
                    print(f"   {table}: {data.get('live_tuples', 0):,} tuples")

            print("-" * 60)
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n🛑 Stats collection stopped at {datetime.now(timezone.utc).isoformat()}")


def main() -> None:
    """Main entry point for the PostgreSQL stats collector."""
    parser = argparse.ArgumentParser(
        description='Collect PostgreSQL statistics and integrate with status emitter',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor with default 5-second intervals
  python collect_postgresql_stats.py

  # Monitor every 2 seconds
  python collect_postgresql_stats.py --interval 2

  # Use specific status file
  python collect_postgresql_stats.py --status-file /path/to/stats.json

  # Use specific database URL
  python collect_postgresql_stats.py --db-url postgresql://user:pass@host:port/db
        """,
    )

    parser.add_argument('--db-url', help='PostgreSQL connection URL. If omitted, loads from sensors.toml [global].db')

    parser.add_argument('--interval', type=int, default=5, help='Collection interval in seconds (default: 5)')

    parser.add_argument('--status-file', type=Path, help='Status file path (default: postgresql_stats.json)')

    args = parser.parse_args()

    # Load database settings
    if args.db_url:
        settings = DatabaseSettings(url=args.db_url)
    else:
        settings = load_database_settings()

    # Create engine
    engine = create_engine_from_settings(settings)

    # Start monitoring
    monitor_postgresql_stats(engine, args.interval, args.status_file)


if __name__ == '__main__':
    main()
