#!/usr/bin/env python3
"""Enhance existing status files with PostgreSQL statistics.
This reads the current status files and adds database performance metrics.
"""

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.settings import DatabaseSettings


class StatusEnhancer:
    """Enhance existing status files with PostgreSQL statistics."""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.last_stats = {}

    def get_postgresql_stats(self) -> Dict[str, Any]:
        """Get PostgreSQL statistics."""
        try:
            with self.engine.connect() as conn:
                # Get table stats
                query = text("""
                    SELECT 
                        relname as tablename,
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

                # Calculate performance
                tuples_per_second = 0
                if self.last_stats:
                    inserts_delta = total_inserts - self.last_stats.get('total_inserts', 0)
                    tuples_per_second = inserts_delta / 5.0  # Assume 5-second intervals

                self.last_stats = {'total_inserts': total_inserts}

                return {
                    'timestamp': datetime.now(timezone.utc).isoformat(),
                    'database_size': db_size,
                    'total_inserts': total_inserts,
                    'tuples_per_second': tuples_per_second,
                    'active_connections': conn_row.active,
                    'total_connections': conn_row.total,
                    'table_stats': table_stats,
                }

        except SQLAlchemyError as e:
            return {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'error': str(e),
                'database_size': 'Unknown',
                'total_inserts': 0,
                'tuples_per_second': 0,
                'active_connections': 0,
                'total_connections': 0,
                'table_stats': {},
            }

    def enhance_status_file(self, status_file: Path):
        """Enhance a status file with PostgreSQL stats."""
        try:
            # Read existing status
            with status_file.open('r') as f:
                status_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            status_data = {}

        # Add PostgreSQL stats
        pg_stats = self.get_postgresql_stats()
        status_data['postgresql_stats'] = pg_stats
        status_data['last_updated'] = datetime.now(timezone.utc).isoformat()

        # Write enhanced status
        with status_file.open('w') as f:
            json.dump(status_data, f, indent=2, default=str)

        return status_data

    def enhance_all_status_files(self, status_dir: Path = Path(".")):
        """Enhance all status files in a directory."""
        status_files = list(status_dir.glob("*.json"))

        for status_file in status_files:
            if status_file.name.startswith('.'):
                continue

            try:
                enhanced = self.enhance_status_file(status_file)
                print(f"✅ Enhanced {status_file.name}")

                # Print key metrics
                pg_stats = enhanced.get('postgresql_stats', {})
                if pg_stats.get('tuples_per_second', 0) > 0:
                    print(f"   📈 {pg_stats['tuples_per_second']:,.0f} tuples/second")
                print(f"   💾 {pg_stats.get('database_size', 'Unknown')}")

            except Exception as e:
                print(f"❌ Error enhancing {status_file.name}: {e}")


def monitor_status_files(engine: Engine, status_dir: Path = Path("."), interval: int = 5):
    """Monitor and enhance status files continuously."""
    enhancer = StatusEnhancer(engine)

    print("🚀 Status File Enhancer Started")
    print(f"📊 Enhancing files every {interval} seconds")
    print(f"📁 Monitoring directory: {status_dir.absolute()}")
    print("=" * 60)

    try:
        while True:
            print(f"\n⏰ {datetime.now(timezone.utc).strftime('%H:%M:%S')}")
            enhancer.enhance_all_status_files(status_dir)
            print("-" * 60)
            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n🛑 Status enhancement stopped at {datetime.now(timezone.utc).isoformat()}")


def main():
    parser = argparse.ArgumentParser(
        description='Enhance existing status files with PostgreSQL statistics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Enhance all JSON files in current directory
  python enhance_status_files.py

  # Monitor and enhance continuously
  python enhance_status_files.py --monitor

  # Enhance specific file
  python enhance_status_files.py --file status.json

  # Use specific database URL
  python enhance_status_files.py --db-url postgresql://user:pass@host:port/db
        """,
    )

    parser.add_argument('--db-url', help='PostgreSQL connection URL. If omitted, loads from sensors.toml [global].db')

    parser.add_argument('--file', type=Path, help='Specific status file to enhance')

    parser.add_argument('--monitor', action='store_true', help='Monitor and enhance files continuously')

    parser.add_argument('--interval', type=int, default=5, help='Monitoring interval in seconds (default: 5)')

    args = parser.parse_args()

    # Load database settings
    if args.db_url:
        settings = DatabaseSettings(url=args.db_url)
    else:
        # Load from sensors.toml
        config = _load_sensors_config()
        if config:
            settings = DatabaseSettings(url=config['url'])
        else:
            print("❌ No database configuration found. Use --db-url or ensure sensors.toml exists with [global].db")
            return

    # Create engine
    engine = create_engine_from_settings(settings)
    enhancer = StatusEnhancer(engine)

    if args.file:
        # Enhance specific file
        enhanced = enhancer.enhance_status_file(args.file)
        print(f"✅ Enhanced {args.file}")

        pg_stats = enhanced.get('postgresql_stats', {})
        print(f"📈 {pg_stats.get('tuples_per_second', 0):,.0f} tuples/second")
        print(f"💾 {pg_stats.get('database_size', 'Unknown')}")

    elif args.monitor:
        # Monitor continuously
        monitor_status_files(engine, interval=args.interval)

    else:
        # Enhance all files once
        enhancer.enhance_all_status_files()


def _load_sensors_config() -> dict[str, str] | None:
    """Load database configuration from sensors.toml if available."""
    sensors_file = Path("sensors.toml")
    if not sensors_file.exists():
        return None

    try:
        # Try tomllib first (Python 3.11+)
        try:
            import tomllib
        except ImportError:
            # Fall back to tomli for older Python versions
            import tomli as tomllib

        with sensors_file.open("rb") as handle:
            data = tomllib.load(handle)

        # Check for global database configuration
        global_config = data.get("global", {})
        db_url = global_config.get("db")
        if db_url:
            return {"url": db_url}

    except Exception:
        # If sensors.toml doesn't exist or can't be parsed, fall back to default
        pass

    return None


if __name__ == '__main__':
    main()
