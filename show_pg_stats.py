#!/usr/bin/env python3
"""Simple PostgreSQL stats viewer - shows current database performance metrics.
"""

import argparse
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings, load_database_settings


def get_postgresql_stats(engine: Engine) -> dict:
    """Get current PostgreSQL statistics."""
    try:
        with engine.connect() as conn:
            # Get table stats
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
                table_stats[row.tablename] = {
                    'total_inserts': row.total_inserts or 0,
                    'live_tuples': row.live_tuples or 0,
                }
                total_inserts += row.total_inserts or 0

            # Get database size
            size_query = text("SELECT pg_size_pretty(pg_database_size(current_database())) as size")
            size_result = conn.execute(size_query)
            db_size = size_result.fetchone().size

            # Get connections
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
                'database_size': db_size,
                'total_inserts': total_inserts,
                'active_connections': conn_row.active,
                'total_connections': conn_row.total,
                'table_stats': table_stats,
            }

    except SQLAlchemyError as e:
        return {
            'timestamp': datetime.now(timezone.utc),
            'error': str(e),
            'database_size': 'Unknown',
            'total_inserts': 0,
            'active_connections': 0,
            'total_connections': 0,
            'table_stats': {},
        }


def print_stats(stats: dict):
    """Print statistics in a nice format."""
    print(f"⏰ {stats['timestamp'].strftime('%Y-%m-%d %H:%M:%S UTC')}")

    if 'error' in stats:
        print(f"❌ Error: {stats['error']}")
        return

    print(f"💾 Database Size: {stats['database_size']}")
    print(f"🔗 Connections: {stats['active_connections']}/{stats['total_connections']}")
    print(f"📊 Total Inserts: {stats['total_inserts']:,}")

    print("\n📋 Table Statistics:")
    for table, data in stats['table_stats'].items():
        print(f"   {table}: {data['live_tuples']:,} tuples ({data['total_inserts']:,} total inserts)")


def main():
    parser = argparse.ArgumentParser(description='Show current PostgreSQL statistics')
    parser.add_argument('--db-url', help='PostgreSQL connection URL')

    args = parser.parse_args()

    # Load database settings
    if args.db_url:
        settings = DatabaseSettings(url=args.db_url)
    else:
        settings = load_database_settings()

    # Create engine and get stats
    engine = create_engine_from_settings(settings)
    stats = get_postgresql_stats(engine)
    print_stats(stats)


if __name__ == '__main__':
    main()
