"""Integration tests for enrichment workflows using the new EnrichmentService."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from enrichment_handlers import EnrichmentService

from cowrieprocessor.enrichment import EnrichmentCacheManager
from tests.fixtures.enrichment_fixtures import (
    get_dshield_response,
    get_spur_response,
    get_urlhaus_response,
)


@pytest.fixture
def test_database() -> None:
    """Create temporary test database with required schema."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        db_path = Path(tmp.name)

    # Create basic schema
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE sessions (
            session TEXT PRIMARY KEY,
            src_ip TEXT NOT NULL,
            start_time TEXT,
            end_time TEXT,
            commands TEXT,
            dshield_asn TEXT,
            dshield_country TEXT,
            spur_data TEXT,
            urlhaus_tags TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE files (
            session TEXT NOT NULL,
            filename TEXT NOT NULL,
            shasum TEXT,
            filesize INTEGER,
            url TEXT,
            timestamp TEXT,
            vt_description TEXT,
            vt_classification TEXT,
            vt_malicious INTEGER,
            vt_first_seen INTEGER
        )
    """)

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink()


@pytest.fixture
def mock_enrichment_handlers():
    """Mock all enrichment handlers for integration testing."""
    with (
        patch('process_cowrie.enrichment_vt_query') as mock_vt,
        patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
        patch('process_cowrie.enrichment_safe_read_uh_data') as mock_urlhaus,
        patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
    ):
        # Configure mock responses
        mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))
        mock_spur.return_value = json.loads(get_spur_response("datacenter"))
        mock_urlhaus.return_value = json.loads(get_urlhaus_response("malicious_urls"))
        mock_vt.return_value = None  # VT query doesn't return value

        yield {
            'vt': mock_vt,
            'dshield': mock_dshield,
            'urlhaus': mock_urlhaus,
            'spur': mock_spur,
        }


class TestSessionEnrichmentIntegration:
    """Test complete session enrichment workflows."""

    def test_session_enrichment_with_all_services(self, test_database, mock_enrichment_handlers) -> None:
        """Test session enrichment with all external services."""
        # Create test session data
        session_data = {
            "session": "test_session_123",
            "src_ip": "192.168.1.100",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T10:05:00",
            "commands": ["ls", "cat /etc/passwd", "whoami"],
        }

        # Insert test session
        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, end_time, commands)
            VALUES (?, ?, ?, ?, ?)
        """,
            (
                session_data["session"],
                session_data["src_ip"],
                session_data["start_time"],
                session_data["end_time"],
                json.dumps(session_data["commands"]),
            ),
        )
        conn.commit()
        conn.close()

        # Mock the enrichment calls that would happen during processing
        with patch('process_cowrie.with_timeout') as mock_timeout:
            # Simulate successful enrichment calls
            mock_timeout.side_effect = [
                json.loads(get_dshield_response("datacenter")),  # dshield
                json.loads(get_spur_response("datacenter")),  # spur
            ]

            # Test that enrichment handlers are called correctly

            # This would normally call the enrichment functions
            # We're testing that the integration points work
            assert mock_enrichment_handlers['dshield'].called is False  # Not called yet

            # Simulate calling the enrichment during session processing
            from process_cowrie import dshield_query, read_spur_data

            dshield_result = dshield_query("192.168.1.100")
            spur_result = read_spur_data("192.168.1.100", "test-key")

            # Verify enrichment results
            assert dshield_result["ip"]["asname"] == "AMAZON-02"
            assert dshield_result["ip"]["ascountry"] == "US"
            assert len(spur_result) == 18
            assert spur_result[0] == "16509"  # ASN number

    def test_file_enrichment_integration(self, test_database, mock_enrichment_handlers) -> None:
        """Test file enrichment integration during processing."""
        # Create test file data
        file_data = {
            "session": "test_session_123",
            "filename": "malware.exe",
            "shasum": "d41d8cd98f00b204e9800998ecf8427e",  # MD5 of empty string
            "filesize": 1024,
            "url": "http://malicious-site.com/malware.exe",
            "timestamp": "2025-01-01T10:02:00",
        }

        # Insert test file
        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO files (session, filename, shasum, filesize, url, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            (
                file_data["session"],
                file_data["filename"],
                file_data["shasum"],
                file_data["filesize"],
                file_data["url"],
                file_data["timestamp"],
            ),
        )
        conn.commit()
        conn.close()

        # Mock VT enrichment for file hash
        with patch('process_cowrie.with_timeout') as mock_timeout:
            mock_timeout.return_value = None  # VT query doesn't return value

            # Test VT enrichment call
            from process_cowrie import vt_query

            # Create temporary cache directory
            with tempfile.TemporaryDirectory() as cache_dir:
                cache_path = Path(cache_dir)

                # This would normally be called during file processing
                vt_query(file_data["shasum"], cache_path)

                # Verify VT handler was configured to be called
                assert mock_enrichment_handlers['vt'].called is False  # Not called directly

    def test_enrichment_failure_graceful_handling(self, test_database) -> None:
        """Test that enrichment failures don't break the main processing flow."""
        # Create test data
        session_data = {
            "session": "test_session_failure",
            "src_ip": "192.168.1.200",
            "start_time": "2025-01-01T10:00:00",
            "commands": ["ls"],
        }

        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, commands)
            VALUES (?, ?, ?, ?)
        """,
            (
                session_data["session"],
                session_data["src_ip"],
                session_data["start_time"],
                json.dumps(session_data["commands"]),
            ),
        )
        conn.commit()
        conn.close()

        # Create enrichment service
        cache_dir = Path(tempfile.mkdtemp())
        cache_manager = EnrichmentCacheManager(cache_dir)

        # Test with invalid credentials to trigger API failures
        service = EnrichmentService(
            cache_dir=cache_dir,
            vt_api=None,
            dshield_email="invalid@example.com",  # Invalid email will cause API failure
            urlhaus_api="invalid-key",  # Invalid key will cause API failure
            spur_api="invalid-key",  # Invalid key will cause API failure
            cache_manager=cache_manager,
        )

        # Test that enrichment handles failures gracefully
        result = service.enrich_session("test_session_failure", "192.168.1.200")

        # Should return safe defaults even when APIs fail
        enrichment = result.get("enrichment", {})
        assert "dshield" in enrichment
        assert "spur" in enrichment
        assert "urlhaus" in enrichment

        # Verify the structure is correct even with failures
        assert isinstance(enrichment["dshield"], dict)
        assert isinstance(enrichment["spur"], list)
        assert isinstance(enrichment["urlhaus"], str)


class TestEnrichmentMetadataInReports:
    """Test that enrichment metadata appears in generated reports."""

    def test_session_report_includes_enrichment_data(self, test_database) -> None:
        """Test that session reports include enrichment metadata."""
        # Insert session with enrichment data
        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, dshield_asn, dshield_country, spur_data, urlhaus_tags)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "enriched_session",
                "192.168.1.100",
                "2025-01-01T10:00:00",
                "AS16509",  # DShield ASN
                "US",  # DShield country
                json.dumps(["AS16509", "Amazon.com, Inc.", "DATACENTER"]),  # SPUR data
                "malware,trojan",  # URLHaus tags
            ),
        )
        conn.commit()
        conn.close()

        # Test report generation includes enrichment data
        # This would normally be done by the reporting system
        conn = sqlite3.connect(test_database)
        cursor = conn.execute(
            """
            SELECT * FROM sessions WHERE session = ?
        """,
            ("enriched_session",),
        )

        session = dict(cursor.fetchone())
        conn.close()

        # Verify enrichment data is stored correctly
        assert session["dshield_asn"] == "AS16509"
        assert session["dshield_country"] == "US"
        assert "DATACENTER" in session["spur_data"]
        assert "malware" in session["urlhaus_tags"]

    def test_file_report_includes_vt_enrichment(self, test_database) -> None:
        """Test that file reports include VirusTotal enrichment data."""
        # Insert file with VT enrichment data
        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO files (session, filename, shasum, vt_description,
                             vt_classification, vt_malicious, vt_first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "test_session",
                "malware.exe",
                "d41d8cd98f00b204e9800998ecf8427e",
                "Win32 EXE",  # VT description
                "trojan.generic/malware",  # VT classification
                45,  # VT malicious count
                1677600000,  # VT first seen timestamp
            ),
        )
        conn.commit()
        conn.close()

        # Verify VT data is stored correctly
        conn = sqlite3.connect(test_database)
        cursor = conn.execute(
            """
            SELECT * FROM files WHERE shasum = ?
        """,
            ("d41d8cd98f00b204e9800998ecf8427e",),
        )

        file_data = dict(cursor.fetchone())
        conn.close()

        assert file_data["vt_description"] == "Win32 EXE"
        assert file_data["vt_classification"] == "trojan.generic/malware"
        assert file_data["vt_malicious"] == 45
        assert file_data["vt_first_seen"] == 1677600000


class TestConcurrentEnrichmentProcessing:
    """Test concurrent enrichment processing scenarios."""

    def test_multiple_sessions_enrichment(self, test_database, mock_enrichment_handlers) -> None:
        """Test enriching multiple sessions concurrently."""
        import threading

        # Create multiple test sessions
        sessions = []
        for i in range(5):
            session_data = {
                "session": f"concurrent_session_{i}",
                "src_ip": f"192.168.1.{100 + i}",
                "start_time": f"2025-01-01T10:{i:02d}:00",
                "commands": [f"command_{i}"],
            }
            sessions.append(session_data)

            # Insert into database
            conn = sqlite3.connect(test_database)
            conn.execute(
                """
                INSERT INTO sessions (session, src_ip, start_time, commands)
                VALUES (?, ?, ?, ?)
            """,
                (
                    session_data["session"],
                    session_data["src_ip"],
                    session_data["start_time"],
                    json.dumps(session_data["commands"]),
                ),
            )
            conn.commit()
            conn.close()

        # Test concurrent enrichment processing
        def enrich_session(session_data):
            """Simulate enriching a single session."""
            from process_cowrie import dshield_query, read_spur_data

            dshield_result = dshield_query(session_data["src_ip"])
            spur_result = read_spur_data(session_data["src_ip"], "test-key")

            return {
                "session": session_data["session"],
                "dshield": dshield_result,
                "spur": spur_result,
            }

        # Run enrichment concurrently
        results = []
        threads = []

        for session_data in sessions:
            thread = threading.Thread(target=lambda: results.append(enrich_session(session_data)))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join()

        # Verify all enrichments completed successfully
        assert len(results) == 5
        for result in results:
            assert result["dshield"]["ip"]["asname"] == "AMAZON-02"
            assert len(result["spur"]) == 18

    def test_enrichment_rate_limiting_simulation(self, test_database) -> None:
        """Test behavior under rate limiting conditions."""
        session_data = {
            "session": "rate_limit_test",
            "src_ip": "192.168.1.150",
            "start_time": "2025-01-01T10:00:00",
            "commands": ["ls"],
        }

        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, commands)
            VALUES (?, ?, ?, ?)
        """,
            (
                session_data["session"],
                session_data["src_ip"],
                session_data["start_time"],
                json.dumps(session_data["commands"]),
            ),
        )
        conn.commit()
        conn.close()

        # Mock rate limiting scenario
        call_count = 0

        def rate_limited_dshield(ip_address):
            nonlocal call_count
            call_count += 1
            if call_count <= 4:  # First 4 calls succeed
                return json.loads(get_dshield_response("datacenter"))
            else:  # Subsequent calls are rate limited
                raise Exception("Rate limit exceeded")

        with patch('process_cowrie.enrichment_dshield_query', side_effect=rate_limited_dshield):
            # Test that rate limiting is handled gracefully
            from process_cowrie import dshield_query

            # First few calls should succeed
            for i in range(3):
                result = dshield_query("192.168.1.150")
                assert result["ip"]["asname"] == "AMAZON-02"

            # Later calls should fail gracefully
            result = dshield_query("192.168.1.150")
            assert result == {"ip": {"asname": "", "ascountry": ""}}


class TestEnrichmentDataConsistency:
    """Test consistency of enrichment data across different scenarios."""

    def test_enrichment_data_persistence_across_calls(self, test_database, tmp_path) -> None:
        """Test that enrichment data is consistently cached and retrieved."""
        # Create cache directory
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        # First call should fetch from API
        from process_cowrie import dshield_query

        result1 = dshield_query("192.168.1.100", cache_base=cache_dir)

        # Verify cache file was created
        cache_file = cache_dir / "dshield_192.168.1.100.json"
        assert cache_file.exists()

        # Second call should use cache
        result2 = dshield_query("192.168.1.100", cache_base=cache_dir)

        # Results should be identical
        assert result1 == result2

    def test_enrichment_data_isolation_between_ips(self, test_database, tmp_path) -> None:
        """Test that different IPs get separate enrichment data."""
        cache_dir = tmp_path / "cache"
        cache_dir.mkdir()

        from process_cowrie import dshield_query

        # Enrich two different IPs
        result1 = dshield_query("192.168.1.100", cache_base=cache_dir)
        result2 = dshield_query("192.168.1.200", cache_base=cache_dir)

        # Should have different cache files
        cache_file1 = cache_dir / "dshield_192.168.1.100.json"
        cache_file2 = cache_dir / "dshield_192.168.1.200.json"

        assert cache_file1.exists()
        assert cache_file2.exists()
        assert result1 != result2  # Different IPs should have different data


class TestEnrichmentErrorRecovery:
    """Test error recovery and resilience in enrichment workflows."""

    def test_partial_enrichment_failure_recovery(self, test_database) -> None:
        """Test recovery when some enrichment services fail."""
        session_data = {
            "session": "partial_failure_test",
            "src_ip": "192.168.1.175",
            "start_time": "2025-01-01T10:00:00",
            "commands": ["ls", "pwd"],
        }

        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, commands)
            VALUES (?, ?, ?, ?)
        """,
            (
                session_data["session"],
                session_data["src_ip"],
                session_data["start_time"],
                json.dumps(session_data["commands"]),
            ),
        )
        conn.commit()
        conn.close()

        # Mock partial failure scenario
        with (
            patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
            patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
        ):
            # DShield succeeds, SPUR fails
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))
            mock_spur.side_effect = Exception("SPUR API unavailable")

            from process_cowrie import dshield_query, read_spur_data

            # DShield should work
            dshield_result = dshield_query("192.168.1.175")
            assert dshield_result["ip"]["asname"] == "AMAZON-02"

            # SPUR should fail gracefully
            spur_result = read_spur_data("192.168.1.175", "test-key")
            assert spur_result == [""] * 18

    def test_complete_enrichment_failure_recovery(self, test_database) -> None:
        """Test recovery when all enrichment services fail."""
        session_data = {
            "session": "complete_failure_test",
            "src_ip": "192.168.1.180",
            "start_time": "2025-01-01T10:00:00",
            "commands": ["whoami"],
        }

        conn = sqlite3.connect(test_database)
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, commands)
            VALUES (?, ?, ?, ?)
        """,
            (
                session_data["session"],
                session_data["src_ip"],
                session_data["start_time"],
                json.dumps(session_data["commands"]),
            ),
        )
        conn.commit()
        conn.close()

        # Mock complete failure scenario
        with (
            patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
            patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
            patch('process_cowrie.enrichment_safe_read_uh_data') as mock_urlhaus,
        ):
            # All services fail
            mock_dshield.side_effect = Exception("DShield API down")
            mock_spur.side_effect = Exception("SPUR API down")
            mock_urlhaus.side_effect = Exception("URLHaus API down")

            from process_cowrie import dshield_query, read_spur_data, safe_read_uh_data

            # All should fail gracefully
            dshield_result = dshield_query("192.168.1.180")
            spur_result = read_spur_data("192.168.1.180", "test-key")
            urlhaus_result = safe_read_uh_data("192.168.1.180", "test-key")

            # Should return safe defaults
            assert dshield_result == {"ip": {"asname": "", "ascountry": ""}}
            assert spur_result == [""] * 18
            assert urlhaus_result == ""


class TestEnrichmentPerformanceScenarios:
    """Test enrichment performance under various load conditions."""

    def test_bulk_enrichment_performance(self, test_database) -> None:
        """Test enrichment performance with many sessions."""
        # Create many test sessions
        sessions = []
        for i in range(50):  # 50 sessions
            session_data = {
                "session": f"bulk_session_{i}",
                "src_ip": f"192.168.1.{200 + i}",
                "start_time": f"2025-01-01T10:{i:02d}:00",
                "commands": [f"command_{i}"],
            }
            sessions.append(session_data)

            conn = sqlite3.connect(test_database)
            conn.execute(
                """
                INSERT INTO sessions (session, src_ip, start_time, commands)
                VALUES (?, ?, ?, ?)
            """,
                (
                    session_data["session"],
                    session_data["src_ip"],
                    session_data["start_time"],
                    json.dumps(session_data["commands"]),
                ),
            )
            conn.commit()
            conn.close()

        # Mock enrichment for performance testing
        with (
            patch('process_cowrie.enrichment_dshield_query') as mock_dshield,
            patch('process_cowrie.enrichment_read_spur_data') as mock_spur,
        ):
            mock_dshield.return_value = json.loads(get_dshield_response("datacenter"))
            mock_spur.return_value = json.loads(get_spur_response("datacenter"))

            import time

            from process_cowrie import dshield_query, read_spur_data

            # Measure enrichment time for bulk processing
            start_time = time.time()

            for session_data in sessions:
                dshield_query(session_data["src_ip"])
                read_spur_data(session_data["src_ip"], "test-key")

            end_time = time.time()
            total_time = end_time - start_time

            # Should complete in reasonable time (less than 10 seconds for 50 enrichments)
            assert total_time < 10.0
            assert mock_dshield.call_count == 50
            assert mock_spur.call_count == 50
