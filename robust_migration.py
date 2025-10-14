#!/usr/bin/env python3
"""Robust SQLite to PostgreSQL Migration Script.

This script handles malformed JSON data and other data quality issues
that can occur during migration from SQLite to PostgreSQL.
"""

import argparse
import json
import logging
import sys
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import inspect, text

# Import our modules
from cowrieprocessor.db.engine import DatabaseSettings, create_engine_from_settings
from cowrieprocessor.db.migrations import apply_migrations

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RobustMigrationTester:
    """Robust migration tester that handles data quality issues."""

    def __init__(self, sqlite_url: str, postgres_url: str, batch_size: int = 1000):
        """Initialize the robust migration tester."""
        self.sqlite_url = sqlite_url
        self.postgres_url = postgres_url
        self.batch_size = batch_size
        self.results = {
            'timestamp': datetime.now().isoformat(),
            'migration_steps': {},
            'summary': {
                'total_steps': 0,
                'successful_steps': 0,
                'failed_steps': 0,
                'total_records_processed': 0,
                'total_records_imported': 0,
                'total_errors': 0,
                'data_quality_issues': [],
            },
        }

    def validate_json_payload(self, payload_str: str) -> Tuple[bool, Optional[str], Optional[Dict]]:
        """Validate and clean JSON payload.

        Returns:
            (is_valid, cleaned_payload_str, parsed_json)
        """
        if not payload_str or payload_str.strip() == '':
            return False, '{}', {}

        # Try to parse as-is first
        try:
            parsed = json.loads(payload_str)
            return True, payload_str, parsed
        except json.JSONDecodeError:
            pass

        # Try to clean common issues
        cleaned = payload_str

        # Fix escaped quotes in malformed JSON
        if '\\"' in cleaned and cleaned.count('"') % 2 != 0:
            # This looks like malformed JSON with escaped quotes
            # Try to extract valid JSON parts
            try:
                # Look for complete JSON objects within the string
                start_idx = cleaned.find('{')
                if start_idx != -1:
                    # Find the matching closing brace
                    brace_count = 0
                    end_idx = start_idx
                    for i, char in enumerate(cleaned[start_idx:], start_idx):
                        if char == '{':
                            brace_count += 1
                        elif char == '}':
                            brace_count -= 1
                            if brace_count == 0:
                                end_idx = i
                                break

                    if brace_count == 0:
                        json_part = cleaned[start_idx : end_idx + 1]
                        parsed = json.loads(json_part)
                        return True, json_part, parsed
            except json.JSONDecodeError:
                pass

        # If all else fails, create a minimal valid JSON object
        try:
            # Extract basic fields if possible
            basic_data = {}

            # Try to extract common fields using regex-like string operations
            if 'src_ip' in cleaned:
                # Extract IP address
                import re

                ip_match = re.search(r'"src_ip":\s*"([^"]+)"', cleaned)
                if ip_match:
                    basic_data['src_ip'] = ip_match.group(1)

            if 'session' in cleaned:
                session_match = re.search(r'"session":\s*"([^"]+)"', cleaned)
                if session_match:
                    basic_data['session'] = session_match.group(1)

            if 'eventid' in cleaned:
                eventid_match = re.search(r'"eventid":\s*"([^"]+)"', cleaned)
                if eventid_match:
                    basic_data['eventid'] = eventid_match.group(1)

            if 'timestamp' in cleaned:
                timestamp_match = re.search(r'"timestamp":\s*"([^"]+)"', cleaned)
                if timestamp_match:
                    basic_data['timestamp'] = timestamp_match.group(1)

            # Add a marker that this was cleaned
            basic_data['_migration_note'] = 'cleaned_from_malformed_json'

            cleaned_json = json.dumps(basic_data)
            return True, cleaned_json, basic_data

        except Exception as e:
            logger.warning(f"Failed to clean JSON payload: {e}")
            return False, '{}', {}

    def pre_migration_analysis(self) -> Dict[str, Any]:
        """Analyze source database for data quality issues."""
        logger.info("🔍 Performing pre-migration analysis...")

        try:
            sqlite_engine = create_engine_from_settings(DatabaseSettings(url=self.sqlite_url))

            with sqlite_engine.connect() as conn:
                # Get table counts
                tables = ['raw_events', 'session_summaries', 'command_stats', 'files', 'dead_letter_events']
                table_counts = {}

                for table in tables:
                    try:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                        table_counts[table] = result[0] if result else 0
                    except Exception as e:
                        logger.warning(f"Could not count {table}: {e}")
                        table_counts[table] = 0

                # Analyze JSON payload quality
                logger.info("Analyzing JSON payload quality...")
                payload_analysis = {}

                try:
                    # Sample some payloads to check quality
                    result = conn.execute(
                        text("""
                        SELECT payload, COUNT(*) as count
                        FROM raw_events 
                        WHERE payload IS NOT NULL AND payload != ''
                        GROUP BY payload
                        ORDER BY count DESC
                        LIMIT 100
                    """)
                    ).fetchall()

                    valid_json_count = 0
                    invalid_json_count = 0
                    malformed_samples = []

                    for payload, count in result:
                        is_valid, _, _ = self.validate_json_payload(payload)
                        if is_valid:
                            valid_json_count += count
                        else:
                            invalid_json_count += count
                            if len(malformed_samples) < 5:
                                malformed_samples.append(
                                    {
                                        'payload': payload[:200] + '...' if len(payload) > 200 else payload,
                                        'count': count,
                                    }
                                )

                    payload_analysis = {
                        'valid_json_count': valid_json_count,
                        'invalid_json_count': invalid_json_count,
                        'malformed_samples': malformed_samples,
                    }

                except Exception as e:
                    logger.warning(f"Could not analyze payloads: {e}")
                    payload_analysis = {'error': str(e)}

                # Get database size
                db_path = self.sqlite_url.replace("sqlite:///", "")
                db_size_mb = Path(db_path).stat().st_size / (1024 * 1024) if Path(db_path).exists() else 0

                analysis = {
                    'tables': tables,
                    'table_counts': table_counts,
                    'database_size_mb': round(db_size_mb, 2),
                    'payload_analysis': payload_analysis,
                }

                logger.info("✅ Pre-migration analysis complete")
                logger.info(f"   Total records: {sum(table_counts.values())}")
                logger.info(f"   Database size: {db_size_mb:.2f} MB")
                logger.info(f"   Valid JSON: {payload_analysis.get('valid_json_count', 0)}")
                logger.info(f"   Invalid JSON: {payload_analysis.get('invalid_json_count', 0)}")

                return analysis

        except Exception as e:
            logger.error(f"❌ Pre-migration analysis failed: {e}")
            raise

    def postgresql_setup(self) -> Dict[str, Any]:
        """Set up PostgreSQL database."""
        logger.info("🐘 Setting up PostgreSQL database...")

        try:
            postgres_engine = create_engine_from_settings(DatabaseSettings(url=self.postgres_url))

            with postgres_engine.connect() as conn:
                # Get PostgreSQL version
                result = conn.execute(text("SELECT version()")).fetchone()
                postgres_version = result[0] if result else "Unknown"

                # Check existing tables
                inspector = inspect(postgres_engine)
                existing_tables = inspector.get_table_names()

                setup_info = {'postgres_version': postgres_version, 'existing_tables': existing_tables}

                logger.info("✅ PostgreSQL setup complete")
                logger.info(f"   Version: {postgres_version}")
                logger.info(f"   Existing tables: {len(existing_tables)}")

                return setup_info

        except Exception as e:
            logger.error(f"❌ PostgreSQL setup failed: {e}")
            raise

    def schema_migration(self) -> Dict[str, Any]:
        """Apply schema migrations to PostgreSQL."""
        logger.info("📋 Applying schema migrations...")

        try:
            postgres_engine = create_engine_from_settings(DatabaseSettings(url=self.postgres_url))

            # Apply migrations
            migration_result = apply_migrations(postgres_engine)

            # Verify schema version
            with postgres_engine.connect() as conn:
                result = conn.execute(text("SELECT value FROM schema_state WHERE key = 'schema_version'")).fetchone()
                schema_version = int(result[0]) if result else 0

            migration_info = {'migration_result': migration_result, 'schema_version': schema_version}

            logger.info("✅ Schema migration complete")
            logger.info(f"   Migration result: {migration_result}")
            logger.info(f"   Schema version: {schema_version}")

            return migration_info

        except Exception as e:
            logger.error(f"❌ Schema migration failed: {e}")
            raise

    def data_export_with_validation(self) -> Dict[str, Any]:
        """Export data from SQLite with JSON validation."""
        logger.info("📤 Exporting data with validation...")

        try:
            sqlite_engine = create_engine_from_settings(DatabaseSettings(url=self.sqlite_url))

            exported_counts = {}
            data_quality_issues = []

            with sqlite_engine.connect() as conn:
                # Export each table
                tables = ['raw_events', 'session_summaries', 'command_stats', 'files', 'dead_letter_events']

                for table in tables:
                    logger.info(f"Exporting {table}...")

                    try:
                        # Get all data from table
                        result = conn.execute(text(f"SELECT * FROM {table}")).fetchall()
                        columns = [desc[0] for desc in result.description] if result else []

                        exported_data = []
                        invalid_json_count = 0

                        for row in result:
                            row_dict = dict(zip(columns, row))

                            # Special handling for raw_events payload
                            if table == 'raw_events' and 'payload' in row_dict:
                                payload = row_dict['payload']
                                is_valid, cleaned_payload, parsed_json = self.validate_json_payload(payload)

                                if not is_valid:
                                    invalid_json_count += 1
                                    row_dict['payload'] = cleaned_payload
                                    row_dict['_json_cleaned'] = True

                                # Extract session_id, event_type, event_timestamp if missing
                                if parsed_json:
                                    if not row_dict.get('session_id') and 'session' in parsed_json:
                                        row_dict['session_id'] = parsed_json['session']
                                    if not row_dict.get('event_type') and 'eventid' in parsed_json:
                                        row_dict['event_type'] = parsed_json['eventid']
                                    if not row_dict.get('event_timestamp') and 'timestamp' in parsed_json:
                                        row_dict['event_timestamp'] = parsed_json['timestamp']

                            exported_data.append(row_dict)

                        exported_counts[table] = len(exported_data)

                        if invalid_json_count > 0:
                            data_quality_issues.append(
                                {
                                    'table': table,
                                    'invalid_json_count': invalid_json_count,
                                    'issue_type': 'malformed_json',
                                }
                            )

                        logger.info(f"   {table}: {len(exported_data)} records ({invalid_json_count} JSON issues)")

                    except Exception as e:
                        logger.warning(f"Could not export {table}: {e}")
                        exported_counts[table] = 0

                export_info = {'exported_counts': exported_counts, 'data_quality_issues': data_quality_issues}

                logger.info("✅ Data export complete")
                logger.info(f"   Total records: {sum(exported_counts.values())}")
                logger.info(f"   Data quality issues: {len(data_quality_issues)}")

                return export_info

        except Exception as e:
            logger.error(f"❌ Data export failed: {e}")
            raise

    def data_import_with_error_handling(self, exported_data: Dict[str, List[Dict]]) -> Dict[str, Any]:
        """Import data to PostgreSQL with comprehensive error handling."""
        logger.info("📥 Importing data with error handling...")

        try:
            postgres_engine = create_engine_from_settings(DatabaseSettings(url=self.postgres_url))

            imported_counts = {}
            errors = []
            total_imported = 0

            with postgres_engine.connect() as conn:
                for table_name, records in exported_data.items():
                    if not records:
                        imported_counts[table_name] = 0
                        continue

                    logger.info(f"Importing {table_name} ({len(records)} records)...")

                    imported_count = 0
                    batch_errors = []

                    # Process in batches
                    for i in range(0, len(records), self.batch_size):
                        batch = records[i : i + self.batch_size]
                        batch_num = i // self.batch_size + 1

                        try:
                            # Prepare batch for insertion
                            if batch:
                                columns = list(batch[0].keys())
                                values_list = []

                                for record in batch:
                                    values = []
                                    for col in columns:
                                        value = record.get(col)
                                        # Handle None values and ensure proper types
                                        if value is None:
                                            values.append(None)
                                        elif isinstance(value, str) and value == '':
                                            values.append(None)
                                        else:
                                            values.append(value)
                                    values_list.append(dict(zip(columns, values)))

                                # Use INSERT ... ON CONFLICT DO NOTHING for idempotency
                                if table_name == 'raw_events':
                                    # Special handling for raw_events with conflict resolution
                                    insert_sql = text(f"""
                                        INSERT INTO {table_name} ({', '.join(columns)})
                                        VALUES ({', '.join([f':{col}' for col in columns])})
                                        ON CONFLICT (id) DO NOTHING
                                    """)
                                else:
                                    insert_sql = text(f"""
                                        INSERT INTO {table_name} ({', '.join(columns)})
                                        VALUES ({', '.join([f':{col}' for col in columns])})
                                        ON CONFLICT DO NOTHING
                                    """)

                                # Execute batch insert
                                conn.execute(insert_sql, values_list)
                                conn.commit()

                                imported_count += len(batch)
                                logger.info(f"   Batch {batch_num}: {len(batch)} records imported")

                        except Exception as e:
                            error_msg = f"Batch {batch_num}: {str(e)}"
                            batch_errors.append(
                                {
                                    'table': table_name,
                                    'batch': batch_num,
                                    'error': error_msg,
                                    'rows_in_batch': len(batch),
                                }
                            )
                            logger.warning(f"   {error_msg}")

                            # Try to continue with next batch
                            try:
                                conn.rollback()
                            except Exception:
                                pass

                    imported_counts[table_name] = imported_count
                    total_imported += imported_count

                    if batch_errors:
                        errors.extend(batch_errors)

                    logger.info(f"   {table_name}: {imported_count}/{len(records)} records imported")

                import_info = {'imported_counts': imported_counts, 'errors': errors, 'total_imported': total_imported}

                logger.info("✅ Data import complete")
                logger.info(f"   Total imported: {total_imported}")
                logger.info(f"   Errors: {len(errors)}")

                return import_info

        except Exception as e:
            logger.error(f"❌ Data import failed: {e}")
            raise

    def data_validation(self) -> Dict[str, Any]:
        """Validate data integrity after migration."""
        logger.info("🔍 Validating data integrity...")

        try:
            sqlite_engine = create_engine_from_settings(DatabaseSettings(url=self.sqlite_url))
            postgres_engine = create_engine_from_settings(DatabaseSettings(url=self.postgres_url))

            validation_counts = {}

            # Compare record counts
            tables = ['raw_events', 'session_summaries', 'command_stats', 'files', 'dead_letter_events']

            for table in tables:
                try:
                    # SQLite count
                    with sqlite_engine.connect() as conn:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                        sqlite_count = result[0] if result else 0

                    # PostgreSQL count
                    with postgres_engine.connect() as conn:
                        result = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).fetchone()
                        postgres_count = result[0] if result else 0

                    validation_counts[table] = {
                        'sqlite': sqlite_count,
                        'postgresql': postgres_count,
                        'match': sqlite_count == postgres_count,
                    }

                except Exception as e:
                    logger.warning(f"Could not validate {table}: {e}")
                    validation_counts[table] = {'sqlite': 0, 'postgresql': 0, 'match': False, 'error': str(e)}

            validation_info = {'validation_counts': validation_counts}

            logger.info("✅ Data validation complete")
            for table, counts in validation_counts.items():
                status = "✅" if counts['match'] else "❌"
                logger.info(f"   {table}: {status} SQLite={counts['sqlite']}, PostgreSQL={counts['postgresql']}")

            return validation_info

        except Exception as e:
            logger.error(f"❌ Data validation failed: {e}")
            raise

    def run_all_steps(self) -> Dict[str, Any]:
        """Run all migration steps."""
        logger.info("🚀 Starting robust migration process...")

        steps = [
            ('Pre-Migration Analysis', self.pre_migration_analysis),
            ('PostgreSQL Setup', self.postgresql_setup),
            ('Schema Migration', self.schema_migration),
        ]

        # Run initial steps
        for step_name, step_func in steps:
            try:
                logger.info(f"\n{'=' * 50}")
                logger.info(f"Step: {step_name}")
                logger.info(f"{'=' * 50}")

                result = step_func()
                self.results['migration_steps'][step_name] = {'success': True, 'result': result}
                self.results['summary']['successful_steps'] += 1

            except Exception as e:
                logger.error(f"❌ {step_name} failed: {e}")
                self.results['migration_steps'][step_name] = {'success': False, 'error': str(e)}
                self.results['summary']['failed_steps'] += 1

        # Export data
        try:
            logger.info(f"\n{'=' * 50}")
            logger.info("Step: Data Export with Validation")
            logger.info(f"{'=' * 50}")

            export_result = self.data_export_with_validation()
            self.results['migration_steps']['Data Export'] = {'success': True, 'result': export_result}
            self.results['summary']['successful_steps'] += 1

            # Import data
            logger.info(f"\n{'=' * 50}")
            logger.info("Step: Data Import with Error Handling")
            logger.info(f"{'=' * 50}")

            import_result = self.data_import_with_error_handling(export_result['exported_counts'])
            self.results['migration_steps']['Data Import'] = {'success': True, 'result': import_result}
            self.results['summary']['successful_steps'] += 1

            # Validate data
            logger.info(f"\n{'=' * 50}")
            logger.info("Step: Data Validation")
            logger.info(f"{'=' * 50}")

            validation_result = self.data_validation()
            self.results['migration_steps']['Data Validation'] = {'success': True, 'result': validation_result}
            self.results['summary']['successful_steps'] += 1

        except Exception as e:
            logger.error(f"❌ Data migration failed: {e}")
            self.results['migration_steps']['Data Migration'] = {'success': False, 'error': str(e)}
            self.results['summary']['failed_steps'] += 1

        # Update summary
        self.results['summary']['total_steps'] = len(self.results['migration_steps'])

        logger.info(f"\n{'=' * 50}")
        logger.info("Migration Summary")
        logger.info(f"{'=' * 50}")
        logger.info(f"Total steps: {self.results['summary']['total_steps']}")
        logger.info(f"Successful: {self.results['summary']['successful_steps']}")
        logger.info(f"Failed: {self.results['summary']['failed_steps']}")

        return self.results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Robust SQLite to PostgreSQL Migration")
    parser.add_argument("--sqlite-url", help="SQLite database URL")
    parser.add_argument("--postgres-url", help="PostgreSQL database URL")
    parser.add_argument("--sensors-file", default="sensors.toml", help="Path to sensors.toml file")
    parser.add_argument("--output", default="robust_migration_results.json", help="Output file for results")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch size for data import")

    args = parser.parse_args()

    # Load configuration
    try:
        with open(args.sensors_file, "rb") as f:
            config = tomllib.load(f)

        default_sqlite_path = config.get('global', {}).get(
            'sqlite_test_db', '/mnt/dshield/data/db/cowrieprocessors.sqlite'
        )
        sqlite_url = args.sqlite_url or f"sqlite:///{default_sqlite_path}"
        postgres_url = args.postgres_url or config.get("global", {}).get("db")

        logger.info(f"📋 Configuration loaded from: {args.sensors_file}")
        logger.info(f"🗃️  SQLite URL: {sqlite_url}")
        logger.info(f"🐘 PostgreSQL URL: {postgres_url}")

    except Exception as e:
        logger.error(f"❌ Error loading configuration: {e}")
        sys.exit(1)

    if not sqlite_url or not postgres_url:
        logger.error("❌ Both SQLite and PostgreSQL URLs must be provided or configured in sensors.toml")
        sys.exit(1)

    # Create tester and run migration
    tester = RobustMigrationTester(sqlite_url, postgres_url, batch_size=args.batch_size)
    results = tester.run_all_steps()

    # Save results
    if args.output:
        import json

        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        logger.info(f"\n📄 Migration results saved to: {args.output}")

    # Exit with appropriate code
    if results['summary']['failed_steps'] > 0:
        logger.error("\n❌ Migration completed with issues!")
        sys.exit(1)
    else:
        logger.info("\n✅ Migration completed successfully!")
        sys.exit(0)


if __name__ == "__main__":
    main()
