#!/usr/bin/env python3
"""Production-Ready SQLite to PostgreSQL Migration Script."""

import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import inspect, text

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.migrations import CURRENT_SCHEMA_VERSION, apply_migrations
from cowrieprocessor.settings import DatabaseSettings


class ProductionMigrator:
    """Production-ready SQLite to PostgreSQL migration script."""

    def __init__(self, sqlite_url: str, postgres_url: str, batch_size: int = 10000):
        """Initialize migrator with database URLs and batch size."""
        self.sqlite_url = sqlite_url
        self.postgres_url = postgres_url
        self.batch_size = batch_size
        self.migration_results: Dict[str, Any] = {
            'timestamp': datetime.now().isoformat(),
            'migration_steps': {},
            'data_comparison': {},
            'performance_comparison': {},
            'summary': {},
        }

    def run_production_migration(self) -> Dict[str, Any]:
        """Run production migration with proper error handling."""
        print("🔄 Starting Production SQLite to PostgreSQL Migration")
        print("=" * 70)
        print(f"📊 Batch size: {self.batch_size:,} records")
        print(f"🗃️  SQLite: {self.sqlite_url}")
        print(f"🐘 PostgreSQL: {self.postgres_url}")
        print("=" * 70)

        # Migration steps
        migration_steps = [
            ("Pre-Migration Analysis", self.analyze_source_database),
            ("PostgreSQL Setup", self.setup_postgresql_database),
            ("Schema Migration", self.migrate_schema),
            ("Data Migration", self.migrate_data_production),
            ("Data Validation", self.validate_migrated_data),
            ("Query Compatibility", self.test_query_compatibility),
            ("Performance Comparison", self.compare_performance),
        ]

        for step_name, step_func in migration_steps:
            print(f"\n🔍 Step: {step_name}")
            print("-" * 50)
            try:
                result = step_func()
                self.migration_results['migration_steps'][step_name] = result
                status = "✅ PASSED" if result.get('success', False) else "❌ FAILED"
                print(f"{status}: {step_name}")
            except Exception as e:
                print(f"❌ ERROR in {step_name}: {e}")
                self.migration_results['migration_steps'][step_name] = {'success': False, 'error': str(e)}

        # Generate summary
        self._generate_migration_summary()
        return self.migration_results

    def analyze_source_database(self) -> Dict[str, Any]:
        """Analyze the source SQLite database."""
        print("Analyzing source SQLite database...")

        result = {'success': True, 'analysis': {}}

        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)

            with sqlite_engine.connect() as conn:
                # Get database info
                inspector = inspect(sqlite_engine)
                tables = inspector.get_table_names()

                result['analysis']['tables'] = tables
                result['analysis']['table_counts'] = {}

                # Count records in each table
                total_records = 0
                for table_name in tables:
                    try:
                        count_result = conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
                        count = count_result[0] if count_result else 0
                        result['analysis']['table_counts'][table_name] = count
                        total_records += count
                        print(f"  {table_name}: {count:,} records")
                    except Exception as e:
                        print(f"  {table_name}: Error counting - {e}")
                        result['analysis']['table_counts'][table_name] = f"Error: {e}"

                result['analysis']['total_records'] = total_records
                print(f"  Total records: {total_records:,}")

                # Get database size
                if self.sqlite_url.startswith("sqlite:///"):
                    db_path = self.sqlite_url.replace("sqlite:///", "")
                    if os.path.exists(db_path):
                        size_bytes = os.path.getsize(db_path)
                        size_mb = size_bytes / (1024 * 1024)
                        size_gb = size_mb / 1024
                        result['analysis']['database_size_mb'] = round(size_mb, 2)
                        result['analysis']['database_size_gb'] = round(size_gb, 2)
                        print(f"  Database size: {size_mb:.2f} MB ({size_gb:.2f} GB)")

                # Check schema version
                try:
                    schema_result = conn.execute(
                        text("SELECT value FROM schema_state WHERE key='schema_version'")
                    ).fetchone()
                    if schema_result:
                        schema_version = int(schema_result[0])
                        result['analysis']['schema_version'] = schema_version
                        print(f"  Schema version: {schema_version}")
                except Exception:
                    result['analysis']['schema_version'] = "Unknown"
                    print("  Schema version: Unknown")

            sqlite_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error analyzing source database: {e}")

        return result

    def setup_postgresql_database(self) -> Dict[str, Any]:
        """Setup PostgreSQL database for migration."""
        print("Setting up PostgreSQL database...")

        result = {'success': True, 'setup_info': {}}

        try:
            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            # Test connection
            with postgres_engine.connect() as conn:
                version_result = conn.execute(text("SELECT version()")).fetchone()
                version = version_result[0] if version_result else "Unknown"
                result['setup_info']['postgres_version'] = version
                print(f"  PostgreSQL version: {version[:50]}...")

                # Check if database is empty
                inspector = inspect(postgres_engine)
                existing_tables = inspector.get_table_names()
                result['setup_info']['existing_tables'] = existing_tables

                if existing_tables:
                    print(f"  Warning: Database has {len(existing_tables)} existing tables")
                    print(f"  Existing tables: {', '.join(existing_tables)}")
                else:
                    print("  Database is empty - ready for migration")

            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error setting up PostgreSQL database: {e}")

        return result

    def migrate_schema(self) -> Dict[str, Any]:
        """Migrate schema to PostgreSQL."""
        print("Migrating schema to PostgreSQL...")

        result = {'success': True, 'migration_info': {}}

        try:
            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            # Apply migrations
            migration_result = apply_migrations(postgres_engine)
            result['migration_info']['migration_result'] = migration_result
            print(f"  Migration result: {migration_result}")

            # Verify schema version
            with postgres_engine.connect() as conn:
                schema_result = conn.execute(
                    text("SELECT value FROM schema_state WHERE key='schema_version'")
                ).fetchone()
                if schema_result:
                    schema_version = int(schema_result[0])
                    result['migration_info']['schema_version'] = schema_version
                    print(f"  Schema version: {schema_version}")

                    if schema_version != CURRENT_SCHEMA_VERSION:
                        result['success'] = False
                        result['error'] = f"Schema version mismatch: {schema_version} != {CURRENT_SCHEMA_VERSION}"

            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error migrating schema: {e}")

        return result

    def migrate_data_production(self) -> Dict[str, Any]:
        """Migrate data with production-ready error handling."""
        print("Migrating data with production error handling...")

        result = {'success': True, 'migration_info': {}}

        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)

            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            migration_stats = {}

            with sqlite_engine.connect() as sqlite_conn, postgres_engine.connect() as postgres_conn:
                inspector = inspect(sqlite_engine)
                tables = inspector.get_table_names()

                # Define migration order (tables with dependencies first)
                migration_order = [
                    'schema_state',
                    'ingest_cursors',
                    'raw_events',
                    'session_summaries',
                    'files',
                    'command_stats',
                    'dead_letter_events',
                ]

                # Filter to only include tables that exist
                tables_to_migrate = [t for t in migration_order if t in tables]

                for table_name in tables_to_migrate:
                    print(f"  Migrating {table_name}...")

                    # Get total count
                    count_result = sqlite_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).fetchone()
                    total_count = count_result[0] if count_result else 0

                    if total_count == 0:
                        print(f"    Skipping {table_name} (no data)")
                        migration_stats[table_name] = {'total': 0, 'migrated': 0, 'errors': 0}
                        continue

                    # Get table structure
                    columns = inspector.get_columns(table_name)
                    column_names = [col['name'] for col in columns]

                    # Migrate in batches
                    migrated_count = 0
                    error_count = 0
                    offset = 0

                    while offset < total_count:
                        batch_size = min(self.batch_size, total_count - offset)

                        # Get batch data
                        query = text(f"SELECT * FROM {table_name} LIMIT {batch_size} OFFSET {offset}")
                        rows = sqlite_conn.execute(query).fetchall()

                        if not rows:
                            break

                        # Prepare INSERT statement with ON CONFLICT handling
                        placeholders = ', '.join([f':{col}' for col in column_names])
                        insert_sql = f"""
                            INSERT INTO {table_name} ({', '.join(column_names)}) 
                            VALUES ({placeholders})
                            ON CONFLICT DO NOTHING
                        """

                        # Insert batch
                        batch_data = [dict(row._mapping) for row in rows]
                        try:
                            postgres_conn.execute(text(insert_sql), batch_data)
                            postgres_conn.commit()
                            migrated_count += len(batch_data)
                            print(f"    Batch {offset // self.batch_size + 1}: {len(batch_data):,} records")
                        except Exception as e:
                            print(f"    Batch {offset // self.batch_size + 1}: Error - {e}")
                            error_count += len(batch_data)

                        offset += batch_size

                        # Progress update
                        if offset % (self.batch_size * 10) == 0:
                            progress = (offset / total_count) * 100
                            print(f"    Progress: {progress:.1f}% ({offset:,}/{total_count:,})")

                    migration_stats[table_name] = {
                        'total': total_count,
                        'migrated': migrated_count,
                        'errors': error_count,
                    }

                    print(f"    Completed: {migrated_count:,}/{total_count:,} records")
                    if error_count > 0:
                        print(f"    Errors: {error_count:,} records")

            result['migration_info']['migration_stats'] = migration_stats
            result['migration_info']['total_migrated'] = sum(stats['migrated'] for stats in migration_stats.values())
            result['migration_info']['total_errors'] = sum(stats['errors'] for stats in migration_stats.values())

            sqlite_engine.dispose()
            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error migrating data: {e}")

        return result

    def validate_migrated_data(self) -> Dict[str, Any]:
        """Validate migrated data integrity."""
        print("Validating migrated data...")

        result = {'success': True, 'validation_info': {}}

        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)

            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            validation_results = {}

            with sqlite_engine.connect() as sqlite_conn, postgres_engine.connect() as postgres_conn:
                inspector = inspect(sqlite_engine)
                tables = inspector.get_table_names()

                for table_name in tables:
                    print(f"  Validating {table_name}...")

                    # Get counts
                    sqlite_count = sqlite_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()

                    try:
                        postgres_count = postgres_conn.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
                    except Exception as e:
                        print(f"    Error counting PostgreSQL {table_name}: {e}")
                        postgres_count = 0

                    validation_results[table_name] = {
                        'sqlite_count': sqlite_count,
                        'postgres_count': postgres_count,
                        'match': sqlite_count == postgres_count,
                    }

                    status = "✅" if sqlite_count == postgres_count else "❌"
                    print(f"    {status} SQLite: {sqlite_count:,}, PostgreSQL: {postgres_count:,}")

            result['validation_info']['table_validation'] = validation_results
            result['validation_info']['all_match'] = all(v['match'] for v in validation_results.values())

            sqlite_engine.dispose()
            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error validating data: {e}")

        return result

    def test_query_compatibility(self) -> Dict[str, Any]:
        """Test query compatibility on migrated data."""
        print("Testing query compatibility...")

        result = {'success': True, 'query_tests': {}}

        try:
            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            query_tests = [
                ("Basic Count Query", "SELECT COUNT(*) FROM raw_events"),
                ("JSON Field Extraction", "SELECT COUNT(*) FROM raw_events WHERE payload->>'src_ip' IS NOT NULL"),
                ("Session Summary Query", "SELECT COUNT(*) FROM session_summaries"),
                ("Files Query", "SELECT COUNT(*) FROM files"),
                ("Command Stats Query", "SELECT COUNT(*) FROM command_stats"),
                ("Dead Letter Query", "SELECT COUNT(*) FROM dead_letter_events"),
            ]

            with postgres_engine.connect() as conn:
                for test_name, query in query_tests:
                    try:
                        result_val = conn.execute(text(query)).scalar_one()
                        result['query_tests'][test_name] = {'success': True, 'result': result_val, 'query': query}
                        print(f"  ✅ {test_name}: {result_val:,}")
                    except Exception as e:
                        result['query_tests'][test_name] = {'success': False, 'error': str(e), 'query': query}
                        print(f"  ❌ {test_name}: {e}")

            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error testing queries: {e}")

        return result

    def compare_performance(self) -> Dict[str, Any]:
        """Compare performance between SQLite and PostgreSQL."""
        print("Comparing performance...")

        result = {'success': True, 'performance_comparison': {}}

        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)

            postgres_settings = DatabaseSettings(url=self.postgres_url)
            postgres_engine = create_engine_from_settings(postgres_settings)

            performance_tests = [
                ("Simple Count", "SELECT COUNT(*) FROM raw_events"),
                ("JSON Field Count", "SELECT COUNT(*) FROM raw_events WHERE payload->>'src_ip' IS NOT NULL"),
                ("Session Count", "SELECT COUNT(*) FROM session_summaries"),
                ("Dead Letter Count", "SELECT COUNT(*) FROM dead_letter_events"),
            ]

            performance_results = {}

            for test_name, query in performance_tests:
                print(f"  Testing {test_name}...")

                # SQLite performance
                start_time = time.time()
                with sqlite_engine.connect() as conn:
                    sqlite_result = conn.execute(text(query)).scalar_one()
                sqlite_time = time.time() - start_time

                # PostgreSQL performance
                start_time = time.time()
                with postgres_engine.connect() as conn:
                    postgres_result = conn.execute(text(query)).scalar_one()
                postgres_time = time.time() - start_time

                performance_results[test_name] = {
                    'sqlite_time': sqlite_time,
                    'postgres_time': postgres_time,
                    'sqlite_result': sqlite_result,
                    'postgres_result': postgres_result,
                    'speed_ratio': postgres_time / sqlite_time if sqlite_time > 0 else float('inf'),
                }

                print(f"    SQLite: {sqlite_time:.4f}s ({sqlite_result:,})")
                print(f"    PostgreSQL: {postgres_time:.4f}s ({postgres_result:,})")
                print(f"    Speed ratio: {performance_results[test_name]['speed_ratio']:.2f}x")

            result['performance_comparison'] = performance_results

            sqlite_engine.dispose()
            postgres_engine.dispose()

        except Exception as e:
            result['success'] = False
            result['error'] = str(e)
            print(f"  Error comparing performance: {e}")

        return result

    def _generate_migration_summary(self):
        """Generate migration summary."""
        steps = self.migration_results['migration_steps']
        successful_steps = sum(1 for step in steps.values() if step.get('success', False))
        total_steps = len(steps)

        self.migration_results['summary'] = {
            'total_steps': total_steps,
            'successful_steps': successful_steps,
            'failed_steps': total_steps - successful_steps,
            'success_rate': (successful_steps / total_steps * 100) if total_steps > 0 else 0,
            'migration_successful': successful_steps == total_steps,
        }

        print("\n" + "=" * 70)
        print("📊 MIGRATION SUMMARY")
        print("=" * 70)
        print(f"Total Steps: {total_steps}")
        print(f"Successful: {successful_steps}")
        print(f"Failed: {total_steps - successful_steps}")
        print(f"Success Rate: {self.migration_results['summary']['success_rate']:.1f}%")

        if self.migration_results['summary']['migration_successful']:
            print("\n🎉 Production migration completed successfully!")
        else:
            print("\n⚠️  Production migration completed with some issues")


def main():
    """Main entry point for production migration."""
    import argparse
    import tomllib

    parser = argparse.ArgumentParser(description="Production SQLite to PostgreSQL Migration Script")
    parser.add_argument("--sqlite-url", help="SQLite database URL (overrides sensors.toml)")
    parser.add_argument("--postgres-url", help="PostgreSQL database URL (overrides sensors.toml)")
    parser.add_argument("--sensors-file", default="sensors.toml", help="Path to sensors.toml file")
    parser.add_argument("--batch-size", type=int, default=10000, help="Batch size for migration")
    parser.add_argument("--output", help="Output file for migration results (JSON)")

    args = parser.parse_args()

    # Load configuration from sensors.toml
    try:
        with open(args.sensors_file, "rb") as f:
            config = tomllib.load(f)

        # Get database URLs from config
        postgres_url = args.postgres_url or config.get("global", {}).get("db")
        default_sqlite_path = config.get('global', {}).get(
            'sqlite_test_db', '/mnt/dshield/data/db/cowrieprocessors.sqlite'
        )
        sqlite_url = args.sqlite_url or f"sqlite:///{default_sqlite_path}"

        print(f"📋 Configuration loaded from: {args.sensors_file}")
        print(f"🗃️  SQLite URL: {sqlite_url}")
        print(f"🐘 PostgreSQL URL: {postgres_url}")

    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        if not args.postgres_url or not args.sqlite_url:
            print("Please provide --postgres-url and --sqlite-url or ensure sensors.toml is properly configured")
            sys.exit(1)
        postgres_url = args.postgres_url
        sqlite_url = args.sqlite_url

    if not postgres_url or not sqlite_url:
        print("❌ Both PostgreSQL and SQLite URLs are required")
        sys.exit(1)

    # Create migrator
    migrator = ProductionMigrator(sqlite_url, postgres_url, args.batch_size)

    # Run migration
    results = migrator.run_production_migration()

    # Save results if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        print(f"\n📄 Migration results saved to: {args.output}")

    # Exit with appropriate code
    if results['summary']['migration_successful']:
        print("\n✅ Production migration completed successfully!")
        sys.exit(0)
    else:
        print("\n❌ Production migration completed with issues!")
        sys.exit(1)


if __name__ == "__main__":
    main()
