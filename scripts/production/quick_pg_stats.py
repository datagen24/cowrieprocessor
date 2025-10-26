#!/usr/bin/env python3
"""Quick PostgreSQL loading stats - shows tuples/second and key metrics."""

import argparse
import time
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings, load_database_settings


def get_loading_stats(engine: Engine) -> dict:
    """Get current loading statistics."""
    with engine.connect() as conn:
        # Get table stats with deltas
        query = text("""
            SELECT 
                tablename,
                n_tup_ins as total_inserts,
                n_live_tup as live_tuples
            FROM pg_stat_user_tables 
            WHERE schemaname = 'public'
            ORDER BY n_tup_ins DESC
        """)

        result = conn.execute(query)
        table_stats = {}
        total_inserts = 0

        for row in result:
            table_stats[row.tablename] = {'total_inserts': row.total_inserts or 0, 'live_tuples': row.live_tuples or 0}
            total_inserts += row.total_inserts or 0

        # Get database size
        size_query = text("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
        size_result = conn.execute(size_query)
        size_row = size_result.fetchone()
        db_size = size_row.size if size_row else 'Unknown'

        # Get active connections
        conn_query = text("""
            SELECT 
                count(*) FILTER (WHERE state = 'active') as active,
                count(*) as total
            FROM pg_stat_activity 
            WHERE datname = current_database()
        """)
        conn_result = conn.execute(conn_query)
        conn_row = conn_result.fetchone()

        return {
            'timestamp': datetime.now(timezone.utc),
            'total_inserts': total_inserts,
            'database_size': db_size,
            'active_connections': conn_row.active if conn_row else 0,
            'total_connections': conn_row.total if conn_row else 0,
            'table_stats': table_stats,
        }


def monitor_loading(engine: Engine, interval: int = 5) -> None:
    """Monitor loading with simple output."""
    last_stats = None
    start_time = datetime.now(timezone.utc)

    print(f"🚀 PostgreSQL Loading Monitor - Started at {start_time.strftime('%H:%M:%S')}")
    print(f"📊 Checking every {interval} seconds...")
    print("=" * 60)

    try:
        while True:
            current_stats = get_loading_stats(engine)

            if last_stats:
                # Calculate tuples per second
                inserts_delta = current_stats['total_inserts'] - last_stats['total_inserts']  # type: ignore[unreachable]
                time_delta = (current_stats['timestamp'] - last_stats['timestamp']).total_seconds()

                if time_delta > 0:
                    tuples_per_second = inserts_delta / time_delta

                    print(f"\n⏰ {current_stats['timestamp'].strftime('%H:%M:%S')}")
                    print(f"📈 Loading Rate: {tuples_per_second:,.0f} tuples/second")
                    print(f"💾 Database Size: {current_stats['database_size']}")
                    print(f"🔗 Connections: {current_stats['active_connections']}/{current_stats['total_connections']}")

                    # Show top tables by activity
                    print("📋 Top Tables:")
                    for table, stats in current_stats['table_stats'].items():
                        if stats['total_inserts'] > 0:
                            print(f"   {table}: {stats['live_tuples']:,} tuples")

                    print("-" * 60)

            last_stats = current_stats
            time.sleep(interval)

    except KeyboardInterrupt:
        duration = datetime.now(timezone.utc) - start_time
        print(f"\n🛑 Monitoring stopped after {duration}")


def main() -> None:
    """Main entry point for the quick PostgreSQL stats viewer."""
    parser = argparse.ArgumentParser(description='Quick PostgreSQL loading monitor')
    parser.add_argument('--db-url', help='PostgreSQL connection URL')
    parser.add_argument('--interval', type=int, default=5, help='Check interval in seconds')

    args = parser.parse_args()

    # Load database settings
    if args.db_url:
        settings = DatabaseSettings(url=args.db_url)
    else:
        settings = load_database_settings()

    # Create engine and start monitoring
    engine = create_engine_from_settings(settings)
    monitor_loading(engine, args.interval)


if __name__ == '__main__':
    main()
