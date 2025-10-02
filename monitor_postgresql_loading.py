#!/usr/bin/env python3
"""Real-time PostgreSQL loading statistics monitor for Cowrie Processor.

This script monitors database activity during bulk loading operations,
providing insights into loading performance, table growth, and system metrics.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.engine import Engine

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings, load_database_settings


class PostgreSQLLoadingMonitor:
    """Monitor PostgreSQL loading statistics in real-time."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.last_stats = {}
        self.start_time = datetime.now(timezone.utc)

    def get_table_stats(self) -> Dict[str, Any]:
        """Get current table statistics."""
        with self.engine.connect() as conn:
            # Get table sizes and row counts
            query = text("""
                SELECT 
                    schemaname,
                    tablename,
                    n_tup_ins as inserts,
                    n_tup_upd as updates,
                    n_tup_del as deletes,
                    n_live_tup as live_tuples,
                    n_dead_tup as dead_tuples,
                    last_vacuum,
                    last_autovacuum,
                    last_analyze,
                    last_autoanalyze
                FROM pg_stat_user_tables 
                WHERE schemaname = 'public'
                ORDER BY tablename
            """)

            result = conn.execute(query)
            table_stats = {}

            for row in result:
                table_name = row.tablename
                table_stats[table_name] = {
                    'inserts': row.inserts or 0,
                    'updates': row.updates or 0,
                    'deletes': row.deletes or 0,
                    'live_tuples': row.live_tuples or 0,
                    'dead_tuples': row.dead_tuples or 0,
                    'last_vacuum': row.last_vacuum.isoformat() if row.last_vacuum else None,
                    'last_autovacuum': row.last_autovacuum.isoformat() if row.last_autovacuum else None,
                    'last_analyze': row.last_analyze.isoformat() if row.last_analyze else None,
                    'last_autoanalyze': row.last_autoanalyze.isoformat() if row.last_autoanalyze else None,
                }

            return table_stats

    def get_database_size(self) -> Dict[str, Any]:
        """Get database size information."""
        with self.engine.connect() as conn:
            # Database size
            size_query = text("""
                SELECT 
                    pg_size_pretty(pg_database_size(current_database())) as size_pretty,
                    pg_database_size(current_database()) as size_bytes
            """)

            result = conn.execute(size_query)
            size_row = result.fetchone()

            # Table sizes
            table_size_query = text("""
                SELECT 
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as size_pretty,
                    pg_total_relation_size(schemaname||'.'||tablename) as size_bytes
                FROM pg_tables 
                WHERE schemaname = 'public'
                ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            """)

            result = conn.execute(table_size_query)
            table_sizes = {}

            for row in result:
                table_sizes[row.tablename] = {'size_pretty': row.size_pretty, 'size_bytes': row.size_bytes or 0}

            return {
                'database_size_pretty': size_row.size_pretty,
                'database_size_bytes': size_row.size_bytes,
                'table_sizes': table_sizes,
            }

    def get_loading_performance(self) -> Dict[str, Any]:
        """Calculate loading performance metrics."""
        current_stats = self.get_table_stats()

        if not self.last_stats:
            self.last_stats = current_stats
            return {'status': 'initializing', 'tuples_per_second': 0}

        # Calculate deltas
        deltas = {}
        total_inserts_per_second = 0

        for table_name, current in current_stats.items():
            if table_name in self.last_stats:
                last = self.last_stats[table_name]
                inserts_delta = current['inserts'] - last['inserts']
                live_tuples_delta = current['live_tuples'] - last['live_tuples']

                deltas[table_name] = {
                    'inserts_delta': inserts_delta,
                    'live_tuples_delta': live_tuples_delta,
                    'current_live_tuples': current['live_tuples'],
                }

                total_inserts_per_second += inserts_delta

        self.last_stats = current_stats

        return {
            'table_deltas': deltas,
            'total_inserts_per_second': total_inserts_per_second,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    def get_active_connections(self) -> Dict[str, Any]:
        """Get active connection information."""
        with self.engine.connect() as conn:
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
                'total_connections': row.total_connections,
                'active_connections': row.active_connections,
                'idle_connections': row.idle_connections,
                'idle_in_transaction': row.idle_in_transaction,
            }

    def get_current_queries(self) -> list[Dict[str, Any]]:
        """Get currently running queries."""
        with self.engine.connect() as conn:
            query = text("""
                SELECT 
                    pid,
                    state,
                    query_start,
                    now() - query_start as duration,
                    left(query, 100) as query_preview
                FROM pg_stat_activity 
                WHERE datname = current_database() 
                AND state = 'active'
                AND query NOT LIKE '%pg_stat_activity%'
                ORDER BY query_start
            """)

            result = conn.execute(query)
            queries = []

            for row in result:
                queries.append(
                    {
                        'pid': row.pid,
                        'state': row.state,
                        'query_start': row.query_start.isoformat() if row.query_start else None,
                        'duration': str(row.duration) if row.duration else None,
                        'query_preview': row.query_preview,
                    }
                )

            return queries

    def get_system_stats(self) -> Dict[str, Any]:
        """Get system-level statistics."""
        with self.engine.connect() as conn:
            # Checkpoint stats
            checkpoint_query = text("""
                SELECT 
                    checkpoints_timed,
                    checkpoints_req,
                    checkpoint_write_time,
                    checkpoint_sync_time,
                    buffers_checkpoint,
                    buffers_clean,
                    buffers_backend
                FROM pg_stat_bgwriter
            """)

            result = conn.execute(checkpoint_query)
            checkpoint_row = result.fetchone()

            # WAL stats
            wal_query = text("""
                SELECT 
                    wal_records,
                    wal_fpi,
                    wal_bytes,
                    wal_buffers_full,
                    wal_write,
                    wal_sync,
                    wal_write_time,
                    wal_sync_time
                FROM pg_stat_wal
            """)

            result = conn.execute(wal_query)
            wal_row = result.fetchone()

            return {
                'checkpoints': {
                    'timed': checkpoint_row.checkpoints_timed,
                    'requested': checkpoint_row.checkpoints_req,
                    'write_time_ms': checkpoint_row.checkpoint_write_time,
                    'sync_time_ms': checkpoint_row.checkpoint_sync_time,
                    'buffers_checkpoint': checkpoint_row.buffers_checkpoint,
                    'buffers_clean': checkpoint_row.buffers_clean,
                    'buffers_backend': checkpoint_row.buffers_backend,
                },
                'wal': {
                    'records': wal_row.wal_records,
                    'fpi': wal_row.wal_fpi,
                    'bytes': wal_row.wal_bytes,
                    'buffers_full': wal_row.wal_buffers_full,
                    'write': wal_row.wal_write,
                    'sync': wal_row.wal_sync,
                    'write_time_ms': wal_row.wal_write_time,
                    'sync_time_ms': wal_row.wal_sync_time,
                },
            }

    def print_stats(self, interval: int = 5):
        """Print statistics in a loop."""
        print(f"🚀 PostgreSQL Loading Monitor Started at {self.start_time.isoformat()}")
        print(f"📊 Monitoring every {interval} seconds...")
        print("=" * 80)

        try:
            while True:
                print(f"\n⏰ {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

                # Performance metrics
                perf = self.get_loading_performance()
                if perf.get('status') != 'initializing':
                    print(f"📈 Loading Rate: {perf['total_inserts_per_second']:,} tuples/second")

                    # Show per-table deltas
                    for table, delta in perf['table_deltas'].items():
                        if delta['inserts_delta'] > 0:
                            print(
                                f"   {table}: +{delta['inserts_delta']:,} inserts, {delta['current_live_tuples']:,} total"
                            )

                # Database size
                size_info = self.get_database_size()
                print(f"💾 Database Size: {size_info['database_size_pretty']}")

                # Active connections
                conn_info = self.get_active_connections()
                print(f"🔗 Connections: {conn_info['active_connections']} active, {conn_info['idle_connections']} idle")

                # Current queries
                queries = self.get_current_queries()
                if queries:
                    print(f"🔄 Active Queries: {len(queries)}")
                    for query in queries[:3]:  # Show first 3
                        print(f"   PID {query['pid']}: {query['duration']} - {query['query_preview']}")

                print("-" * 80)
                time.sleep(interval)

        except KeyboardInterrupt:
            print(f"\n🛑 Monitoring stopped at {datetime.now(timezone.utc).isoformat()}")

    def save_stats_to_file(self, filename: str):
        """Save comprehensive statistics to JSON file."""
        stats = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'monitoring_duration': str(datetime.now(timezone.utc) - self.start_time),
            'table_stats': self.get_table_stats(),
            'database_size': self.get_database_size(),
            'loading_performance': self.get_loading_performance(),
            'active_connections': self.get_active_connections(),
            'current_queries': self.get_current_queries(),
            'system_stats': self.get_system_stats(),
        }

        with open(filename, 'w') as f:
            json.dump(stats, f, indent=2, default=str)

        print(f"📄 Statistics saved to {filename}")


def main():
    parser = argparse.ArgumentParser(
        description='Monitor PostgreSQL loading statistics in real-time',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Monitor with default 5-second intervals
  python monitor_postgresql_loading.py --db-url postgresql://user:pass@host:port/db

  # Monitor every 2 seconds
  python monitor_postgresql_loading.py --db-url postgresql://user:pass@host:port/db --interval 2

  # Save one-time snapshot to file
  python monitor_postgresql_loading.py --db-url postgresql://user:pass@host:port/db --snapshot stats.json

  # Use sensors.toml configuration
  python monitor_postgresql_loading.py
        """,
    )

    parser.add_argument('--db-url', help='PostgreSQL connection URL. If omitted, loads from sensors.toml [global].db')

    parser.add_argument('--interval', type=int, default=5, help='Monitoring interval in seconds (default: 5)')

    parser.add_argument(
        '--snapshot', help='Save one-time statistics snapshot to JSON file instead of continuous monitoring'
    )

    args = parser.parse_args()

    # Load database settings
    if args.db_url:
        settings = DatabaseSettings(url=args.db_url)
    else:
        settings = load_database_settings()

    # Create engine
    engine = create_engine_from_settings(settings)

    # Create monitor
    monitor = PostgreSQLLoadingMonitor(engine)

    if args.snapshot:
        # Save one-time snapshot
        monitor.save_stats_to_file(args.snapshot)
    else:
        # Start continuous monitoring
        monitor.print_stats(args.interval)


if __name__ == '__main__':
    main()
