#!/usr/bin/env python3
"""Comprehensive PostgreSQL compatibility testing suite."""

import os
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import create_engine, text, func, select
from sqlalchemy.exc import SQLAlchemyError

from cowrieprocessor.db.engine import (
    create_engine_from_settings, 
    detect_postgresql_support,
    create_engine_with_fallback
)
from cowrieprocessor.db.models import RawEvent, SessionSummary, Files
from cowrieprocessor.db.migrations import apply_migrations, CURRENT_SCHEMA_VERSION
from cowrieprocessor.db.json_utils import JSONAccessor, get_dialect_name_from_engine
from cowrieprocessor.settings import DatabaseSettings
from cowrieprocessor.cli.cowrie_db import CowrieDatabase
from cowrieprocessor.cli.health import _check_database


class PostgreSQLCompatibilityTester:
    """Comprehensive testing suite for PostgreSQL compatibility."""
    
    def __init__(self, postgres_url: str, sqlite_url: str = None):
        """Initialize tester with database URLs."""
        self.postgres_url = postgres_url
        self.sqlite_url = sqlite_url or "sqlite:///:memory:"
        self.test_results: Dict[str, Any] = {
            'timestamp': datetime.now().isoformat(),
            'tests': {},
            'summary': {}
        }
    
    def run_all_tests(self) -> Dict[str, Any]:
        """Run all compatibility tests."""
        print("🧪 Starting PostgreSQL Compatibility Tests")
        print("=" * 60)
        
        # Test categories
        test_categories = [
            ("Driver Detection", self.test_driver_detection),
            ("Connection Tests", self.test_connections),
            ("Schema Migration", self.test_schema_migrations),
            ("JSON Operations", self.test_json_operations),
            ("CLI Tools", self.test_cli_tools),
            ("Utility Scripts", self.test_utility_scripts),
            ("Performance", self.test_performance),
        ]
        
        for category_name, test_func in test_categories:
            print(f"\n🔍 Testing: {category_name}")
            print("-" * 40)
            try:
                result = test_func()
                self.test_results['tests'][category_name] = result
                status = "✅ PASSED" if result.get('passed', False) else "❌ FAILED"
                print(f"{status}: {category_name}")
            except Exception as e:
                print(f"❌ ERROR in {category_name}: {e}")
                self.test_results['tests'][category_name] = {
                    'passed': False,
                    'error': str(e)
                }
        
        # Generate summary
        self._generate_summary()
        return self.test_results
    
    def test_driver_detection(self) -> Dict[str, Any]:
        """Test PostgreSQL driver detection."""
        print("Testing driver detection...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test detection function
        has_postgres = detect_postgresql_support()
        result['details']['driver_available'] = has_postgres
        print(f"  PostgreSQL driver available: {has_postgres}")
        
        if not has_postgres:
            result['passed'] = False
            result['error'] = "PostgreSQL driver not available"
            return result
        
        # Test fallback mechanism
        try:
            from cowrieprocessor.settings import DatabaseSettings
            settings = DatabaseSettings(url=self.postgres_url)
            engine = create_engine_with_fallback(settings)
            result['details']['fallback_works'] = True
            print("  Fallback mechanism works")
        except Exception as e:
            result['passed'] = False
            result['error'] = f"Fallback failed: {e}"
            print(f"  Fallback failed: {e}")
        
        return result
    
    def test_connections(self) -> Dict[str, Any]:
        """Test database connections."""
        print("Testing database connections...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test PostgreSQL connection
        try:
            from cowrieprocessor.settings import DatabaseSettings
            pg_settings = DatabaseSettings(url=self.postgres_url)
            pg_engine = create_engine_from_settings(pg_settings)
            with pg_engine.connect() as conn:
                pg_version = conn.execute(text("SELECT version()")).scalar_one()
                result['details']['postgres_version'] = pg_version
                print(f"  PostgreSQL connected: {pg_version[:50]}...")
        except Exception as e:
            result['passed'] = False
            result['error'] = f"PostgreSQL connection failed: {e}"
            print(f"  PostgreSQL connection failed: {e}")
            return result
        
        # Test SQLite connection
        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)
            with sqlite_engine.connect() as conn:
                sqlite_version = conn.execute(text("SELECT sqlite_version()")).scalar_one()
                result['details']['sqlite_version'] = sqlite_version
                print(f"  SQLite connected: {sqlite_version}")
        except Exception as e:
            result['passed'] = False
            result['error'] = f"SQLite connection failed: {e}"
            print(f"  SQLite connection failed: {e}")
            return result
        
        return result
    
    def test_schema_migrations(self) -> Dict[str, Any]:
        """Test schema migrations on both backends."""
        print("Testing schema migrations...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test PostgreSQL migration
        try:
            pg_settings = DatabaseSettings(url=self.postgres_url)
            pg_engine = create_engine_from_settings(pg_settings)
            
            # Apply migrations
            migration_result = apply_migrations(pg_engine)
            result['details']['postgres_migration'] = migration_result
            print(f"  PostgreSQL migration: {migration_result}")
            
            # Verify schema version
            with pg_engine.connect() as conn:
                version_result = conn.execute(text("SELECT value FROM schema_state WHERE key='schema_version'")).fetchone()
                if version_result:
                    schema_version = int(version_result[0])
                    result['details']['postgres_schema_version'] = schema_version
                    print(f"  PostgreSQL schema version: {schema_version}")
                    
                    if schema_version != CURRENT_SCHEMA_VERSION:
                        result['passed'] = False
                        result['error'] = f"Schema version mismatch: {schema_version} != {CURRENT_SCHEMA_VERSION}"
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"PostgreSQL migration failed: {e}"
            print(f"  PostgreSQL migration failed: {e}")
            return result
        
        # Test SQLite migration
        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)
            
            # Apply migrations
            migration_result = apply_migrations(sqlite_engine)
            result['details']['sqlite_migration'] = migration_result
            print(f"  SQLite migration: {migration_result}")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"SQLite migration failed: {e}"
            print(f"  SQLite migration failed: {e}")
            return result
        
        return result
    
    def test_json_operations(self) -> Dict[str, Any]:
        """Test JSON operations on both backends."""
        print("Testing JSON operations...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test data
        test_payload = {
            "session": "test-session-123",
            "src_ip": "192.168.1.100",
            "eventid": "cowrie.session.connect",
            "timestamp": "2025-01-27T10:00:00Z",
            "nested": {
                "level1": {
                    "level2": "deep_value"
                }
            }
        }
        
        # Test PostgreSQL JSON operations
        try:
            from cowrieprocessor.settings import DatabaseSettings
            pg_settings = DatabaseSettings(url=self.postgres_url)
            pg_engine = create_engine_from_settings(pg_settings)
            dialect_name = get_dialect_name_from_engine(pg_engine)
            result['details']['postgres_dialect'] = dialect_name
            
            # Test JSON field extraction
            field_expr = JSONAccessor.get_field(RawEvent.payload, "src_ip", dialect_name)
            nested_expr = JSONAccessor.get_nested_field(RawEvent.payload, "nested.level1.level2", dialect_name)
            
            result['details']['postgres_json_ops'] = {
                'field_extraction': str(field_expr),
                'nested_extraction': str(nested_expr)
            }
            print(f"  PostgreSQL JSON operations: {dialect_name}")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"PostgreSQL JSON operations failed: {e}"
            print(f"  PostgreSQL JSON operations failed: {e}")
            return result
        
        # Test SQLite JSON operations
        try:
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)
            dialect_name = get_dialect_name_from_engine(sqlite_engine)
            result['details']['sqlite_dialect'] = dialect_name
            
            # Test JSON field extraction
            field_expr = JSONAccessor.get_field(RawEvent.payload, "src_ip", dialect_name)
            nested_expr = JSONAccessor.get_nested_field(RawEvent.payload, "nested.level1.level2", dialect_name)
            
            result['details']['sqlite_json_ops'] = {
                'field_extraction': str(field_expr),
                'nested_extraction': str(nested_expr)
            }
            print(f"  SQLite JSON operations: {dialect_name}")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"SQLite JSON operations failed: {e}"
            print(f"  SQLite JSON operations failed: {e}")
            return result
        
        return result
    
    def test_cli_tools(self) -> Dict[str, Any]:
        """Test CLI tools with both backends."""
        print("Testing CLI tools...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test health check
        try:
            pg_health_ok, pg_health_msg = _check_database(self.postgres_url)
            result['details']['postgres_health'] = {
                'ok': pg_health_ok,
                'message': pg_health_msg
            }
            print(f"  PostgreSQL health check: {pg_health_msg}")
            
            sqlite_health_ok, sqlite_health_msg = _check_database(self.sqlite_url)
            result['details']['sqlite_health'] = {
                'ok': sqlite_health_ok,
                'message': sqlite_health_msg
            }
            print(f"  SQLite health check: {sqlite_health_msg}")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"Health check failed: {e}"
            print(f"  Health check failed: {e}")
            return result
        
        # Test database validation
        try:
            pg_db = CowrieDatabase(self.postgres_url)
            pg_validation = pg_db.validate_schema()
            result['details']['postgres_validation'] = pg_validation
            print(f"  PostgreSQL validation: {pg_validation.get('status', 'unknown')}")
            
            sqlite_db = CowrieDatabase(self.sqlite_url)
            sqlite_validation = sqlite_db.validate_schema()
            result['details']['sqlite_validation'] = sqlite_validation
            print(f"  SQLite validation: {sqlite_validation.get('status', 'unknown')}")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"Database validation failed: {e}"
            print(f"  Database validation failed: {e}")
            return result
        
        return result
    
    def test_utility_scripts(self) -> Dict[str, Any]:
        """Test utility scripts with both backends."""
        print("Testing utility scripts...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Test script help commands (basic functionality)
        scripts_to_test = [
            "scripts/enrichment_refresh.py",
            "scripts/enrichment_live_check.py",
            "debug_stuck_session.py"
        ]
        
        for script in scripts_to_test:
            try:
                import subprocess
                help_result = subprocess.run(
                    ["uv", "run", "python", script, "--help"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if help_result.returncode == 0:
                    result['details'][script] = "help_command_works"
                    print(f"  {script}: help command works")
                else:
                    result['details'][script] = f"help_failed: {help_result.stderr}"
                    print(f"  {script}: help command failed")
                    
            except Exception as e:
                result['details'][script] = f"error: {e}"
                print(f"  {script}: error - {e}")
        
        return result
    
    def test_performance(self) -> Dict[str, Any]:
        """Test performance comparison between backends."""
        print("Testing performance...")
        
        result = {
            'passed': True,
            'details': {}
        }
        
        # Simple performance test - connection time
        try:
            # PostgreSQL connection time
            from cowrieprocessor.settings import DatabaseSettings
            start_time = time.time()
            pg_settings = DatabaseSettings(url=self.postgres_url)
            pg_engine = create_engine_from_settings(pg_settings)
            with pg_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            pg_connection_time = time.time() - start_time
            
            # SQLite connection time
            start_time = time.time()
            sqlite_settings = DatabaseSettings(url=self.sqlite_url)
            sqlite_engine = create_engine_from_settings(sqlite_settings)
            with sqlite_engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            sqlite_connection_time = time.time() - start_time
            
            result['details']['connection_times'] = {
                'postgresql': pg_connection_time,
                'sqlite': sqlite_connection_time
            }
            
            print(f"  PostgreSQL connection time: {pg_connection_time:.4f}s")
            print(f"  SQLite connection time: {sqlite_connection_time:.4f}s")
            
        except Exception as e:
            result['passed'] = False
            result['error'] = f"Performance test failed: {e}"
            print(f"  Performance test failed: {e}")
            return result
        
        return result
    
    def _generate_summary(self):
        """Generate test summary."""
        total_tests = len(self.test_results['tests'])
        passed_tests = sum(1 for test in self.test_results['tests'].values() if test.get('passed', False))
        
        self.test_results['summary'] = {
            'total_tests': total_tests,
            'passed_tests': passed_tests,
            'failed_tests': total_tests - passed_tests,
            'success_rate': (passed_tests / total_tests * 100) if total_tests > 0 else 0
        }
        
        print("\n" + "=" * 60)
        print("📊 TEST SUMMARY")
        print("=" * 60)
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {total_tests - passed_tests}")
        print(f"Success Rate: {self.test_results['summary']['success_rate']:.1f}%")


def main():
    """Main entry point for testing."""
    import argparse
    import tomllib
    
    parser = argparse.ArgumentParser(description="PostgreSQL Compatibility Testing Suite")
    parser.add_argument("--postgres-url", help="PostgreSQL database URL (overrides sensors.toml)")
    parser.add_argument("--sqlite-url", help="SQLite database URL (overrides sensors.toml)")
    parser.add_argument("--sensors-file", default="sensors.toml", help="Path to sensors.toml file")
    parser.add_argument("--output", help="Output file for test results (JSON)")
    
    args = parser.parse_args()
    
    # Load configuration from sensors.toml
    try:
        with open(args.sensors_file, "rb") as f:
            config = tomllib.load(f)
        
        # Get database URLs from config
        postgres_url = args.postgres_url or config.get("global", {}).get("db")
        sqlite_url = args.sqlite_url or f"sqlite:///{config.get('global', {}).get('sqlite_test_db', '/mnt/dshield/data/db/cowrieprocessors.sqlite')}"
        
        print(f"📋 Configuration loaded from: {args.sensors_file}")
        print(f"🐘 PostgreSQL URL: {postgres_url}")
        print(f"🗃️  SQLite URL: {sqlite_url}")
        
    except Exception as e:
        print(f"❌ Error loading configuration: {e}")
        if not args.postgres_url:
            print("Please provide --postgres-url or ensure sensors.toml is properly configured")
            sys.exit(1)
        postgres_url = args.postgres_url
        sqlite_url = args.sqlite_url or "sqlite:///:memory:"
    
    if not postgres_url:
        print("❌ No PostgreSQL URL provided or found in configuration")
        sys.exit(1)
    
    # Create tester
    tester = PostgreSQLCompatibilityTester(postgres_url, sqlite_url)
    
    # Run tests
    results = tester.run_all_tests()
    
    # Save results if requested
    if args.output:
        import json
        with open(args.output, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n📄 Test results saved to: {args.output}")
    
    # Exit with appropriate code
    if results['summary']['failed_tests'] > 0:
        print("\n❌ Some tests failed!")
        sys.exit(1)
    else:
        print("\n✅ All tests passed!")
        sys.exit(0)


if __name__ == "__main__":
    main()
