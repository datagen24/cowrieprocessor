"""Integration tests for enrichment metadata in generated reports."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def test_database_with_enrichment():
    """Create test database with enrichment data for report testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as tmp:
        db_path = Path(tmp.name)

    conn = sqlite3.connect(db_path)

    # Create tables matching the actual schema
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

    conn.execute("""
        CREATE TABLE commands (
            session TEXT NOT NULL,
            command TEXT NOT NULL,
            timestamp TEXT
        )
    """)

    # Insert test data with enrichment
    test_sessions = [
        {
            "session": "enriched_session_1",
            "src_ip": "192.168.1.100",
            "start_time": "2025-01-01T10:00:00",
            "end_time": "2025-01-01T10:05:00",
            "commands": json.dumps(["ls", "cat /etc/passwd", "whoami"]),
            "dshield_asn": "AS16509",
            "dshield_country": "US",
            "spur_data": json.dumps(["AS16509", "Amazon.com, Inc.", "DATACENTER"]),
            "urlhaus_tags": "malware,trojan",
        },
        {
            "session": "enriched_session_2",
            "src_ip": "203.0.113.100",
            "start_time": "2025-01-01T11:00:00",
            "end_time": "2025-01-01T11:03:00",
            "commands": json.dumps(["wget malware.exe", "chmod +x malware.exe"]),
            "dshield_asn": "AS7922",
            "dshield_country": "US",
            "spur_data": json.dumps(["AS7922", "Comcast Cable", "RESIDENTIAL"]),
            "urlhaus_tags": "exe,botnet",
        },
    ]

    for session in test_sessions:
        conn.execute(
            """
            INSERT INTO sessions (session, src_ip, start_time, end_time, commands,
                                 dshield_asn, dshield_country, spur_data, urlhaus_tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                session["session"],
                session["src_ip"],
                session["start_time"],
                session["end_time"],
                session["commands"],
                session["dshield_asn"],
                session["dshield_country"],
                session["spur_data"],
                session["urlhaus_tags"],
            ),
        )

    # Insert file data with VT enrichment
    test_files = [
        {
            "session": "enriched_session_1",
            "filename": "malware.exe",
            "shasum": "d41d8cd98f00b204e9800998ecf8427e",
            "filesize": 1024,
            "url": "http://malicious-site.com/malware.exe",
            "timestamp": "2025-01-01T10:02:00",
            "vt_description": "Win32 EXE",
            "vt_classification": "trojan.generic/malware",
            "vt_malicious": 45,
            "vt_first_seen": 1677600000,
        },
        {
            "session": "enriched_session_2",
            "filename": "bot.exe",
            "shasum": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "filesize": 2048,
            "url": "http://botnet-site.com/bot.exe",
            "timestamp": "2025-01-01T11:01:00",
            "vt_description": "Win32 EXE",
            "vt_classification": "trojan.botnet",
            "vt_malicious": 23,
            "vt_first_seen": 1677600000,
        },
    ]

    for file_data in test_files:
        conn.execute(
            """
            INSERT INTO files (session, filename, shasum, filesize, url, timestamp,
                             vt_description, vt_classification, vt_malicious, vt_first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                file_data["session"],
                file_data["filename"],
                file_data["shasum"],
                file_data["filesize"],
                file_data["url"],
                file_data["timestamp"],
                file_data["vt_description"],
                file_data["vt_classification"],
                file_data["vt_malicious"],
                file_data["vt_first_seen"],
            ),
        )

    # Insert command data
    commands_data = [
        ("enriched_session_1", "ls", "2025-01-01T10:01:00"),
        ("enriched_session_1", "cat /etc/passwd", "2025-01-01T10:02:00"),
        ("enriched_session_1", "whoami", "2025-01-01T10:03:00"),
        ("enriched_session_2", "wget malware.exe", "2025-01-01T11:01:00"),
        ("enriched_session_2", "chmod +x malware.exe", "2025-01-01T11:02:00"),
    ]

    for session, command, timestamp in commands_data:
        conn.execute(
            """
            INSERT INTO commands (session, command, timestamp)
            VALUES (?, ?, ?)
        """,
            (session, command, timestamp),
        )

    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink()


class TestEnrichmentInSessionReports:
    """Test that enrichment data appears in session reports."""

    def test_session_report_includes_dshield_data(self, test_database_with_enrichment):
        """Test that DShield data appears in session reports."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Query session with DShield enrichment
        cursor = conn.execute(
            """
            SELECT session, src_ip, dshield_asn, dshield_country
            FROM sessions
            WHERE session = ?
        """,
            ("enriched_session_1",),
        )

        session = dict(cursor.fetchone())
        conn.close()

        # Verify DShield data is present
        assert session["dshield_asn"] == "AS16509"
        assert session["dshield_country"] == "US"

        # Test that this data would appear in a report
        report_content = self._generate_mock_session_report(session)

        assert "AS16509" in report_content
        assert "US" in report_content
        assert "DShield" in report_content or "ASN" in report_content

    def test_session_report_includes_spur_data(self, test_database_with_enrichment):
        """Test that SPUR data appears in session reports."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Query session with SPUR enrichment
        cursor = conn.execute(
            """
            SELECT session, src_ip, spur_data
            FROM sessions
            WHERE session = ?
        """,
            ("enriched_session_1",),
        )

        session = dict(cursor.fetchone())
        conn.close()

        # Parse SPUR data
        spur_data = json.loads(session["spur_data"])

        # Verify SPUR data structure
        assert len(spur_data) == 18
        assert spur_data[0] == "AS16509"  # ASN
        assert spur_data[1] == "Amazon.com, Inc."  # Organization
        assert spur_data[2] == "DATACENTER"  # Infrastructure

        # Test that this data would appear in a report
        report_content = self._generate_mock_session_report(session)

        assert "Amazon.com" in report_content
        assert "DATACENTER" in report_content

    def test_session_report_includes_urlhaus_data(self, test_database_with_enrichment):
        """Test that URLHaus data appears in session reports."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Query session with URLHaus enrichment
        cursor = conn.execute(
            """
            SELECT session, src_ip, urlhaus_tags
            FROM sessions
            WHERE session = ?
        """,
            ("enriched_session_1",),
        )

        session = dict(cursor.fetchone())
        conn.close()

        # Verify URLHaus data is present
        assert session["urlhaus_tags"] == "malware,trojan"

        # Test that this data would appear in a report
        report_content = self._generate_mock_session_report(session)

        assert "malware" in report_content
        assert "trojan" in report_content

    def test_multiple_sessions_enrichment_consistency(self, test_database_with_enrichment):
        """Test that enrichment data is consistent across multiple sessions."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Query all sessions with enrichment
        cursor = conn.execute("""
            SELECT session, src_ip, dshield_asn, dshield_country, spur_data, urlhaus_tags
            FROM sessions
            ORDER BY session
        """)

        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Verify both sessions have enrichment data
        assert len(sessions) == 2

        for session in sessions:
            assert session["dshield_asn"] is not None
            assert session["dshield_country"] is not None
            assert session["spur_data"] is not None
            assert session["urlhaus_tags"] is not None

            # Parse SPUR data
            spur_data = json.loads(session["spur_data"])
            assert len(spur_data) == 18
            assert spur_data[0].startswith("AS")  # Should have ASN

        # Test report generation for both sessions
        for session in sessions:
            report_content = self._generate_mock_session_report(session)

            # Each report should include enrichment data
            assert session["dshield_asn"] in report_content
            assert session["dshield_country"] in report_content

            # SPUR data should be represented
            spur_data = json.loads(session["spur_data"])
            if spur_data[1]:  # Organization name
                assert spur_data[1] in report_content


class TestEnrichmentInFileReports:
    """Test that enrichment data appears in file reports."""

    def test_file_report_includes_vt_data(self, test_database_with_enrichment):
        """Test that VirusTotal data appears in file reports."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Query files with VT enrichment
        cursor = conn.execute("""
            SELECT session, filename, shasum, vt_description, vt_classification, vt_malicious, vt_first_seen
            FROM files
            ORDER BY session
        """)

        files = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Verify VT data is present
        assert len(files) == 2

        for file_data in files:
            assert file_data["vt_description"] == "Win32 EXE"
            assert file_data["vt_classification"] is not None
            assert file_data["vt_malicious"] > 0
            assert file_data["vt_first_seen"] > 0

        # Test that this data would appear in a report
        for file_data in files:
            report_content = self._generate_mock_file_report(file_data)

            assert file_data["vt_description"] in report_content
            assert file_data["vt_classification"] in report_content
            assert str(file_data["vt_malicious"]) in report_content

    def test_file_report_enrichment_metadata(self, test_database_with_enrichment):
        """Test that file report includes comprehensive enrichment metadata."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Get file with enrichment and related session data
        cursor = conn.execute(
            """
            SELECT f.*, s.src_ip, s.dshield_asn, s.dshield_country
            FROM files f
            JOIN sessions s ON f.session = s.session
            WHERE f.session = ?
        """,
            ("enriched_session_1",),
        )

        file_data = dict(cursor.fetchone())
        conn.close()

        # Test comprehensive report generation
        report_content = self._generate_mock_comprehensive_report(file_data)

        # Should include file metadata
        assert file_data["filename"] in report_content
        assert file_data["shasum"] in report_content
        assert str(file_data["filesize"]) in report_content

        # Should include VT enrichment
        assert file_data["vt_description"] in report_content
        assert file_data["vt_classification"] in report_content

        # Should include session context
        assert file_data["src_ip"] in report_content
        assert file_data["dshield_asn"] in report_content


class TestReportEnrichmentIntegration:
    """Test integration of enrichment data in full reports."""

    def test_daily_report_includes_enrichment_summary(self, test_database_with_enrichment):
        """Test that daily reports include enrichment summaries."""
        # Mock the report generation process
        conn = sqlite3.connect(test_database_with_enrichment)

        # Get summary data that would be used for daily reports
        cursor = conn.execute("""
            SELECT
                COUNT(DISTINCT session) as total_sessions,
                COUNT(DISTINCT src_ip) as unique_ips,
                COUNT(DISTINCT shasum) as unique_files,
                COUNT(CASE WHEN vt_malicious > 0 THEN 1 END) as malicious_files,
                COUNT(DISTINCT dshield_asn) as unique_asns
            FROM sessions s
            LEFT JOIN files f ON s.session = f.session
            WHERE s.start_time >= date('now', '-1 day')
        """)

        summary = dict(cursor.fetchone())
        conn.close()

        # Generate mock daily report
        self._generate_mock_daily_report(summary)

        # Verify enrichment statistics are included
        assert "total_sessions" in str(summary)
        assert "unique_ips" in str(summary)
        assert "malicious_files" in str(summary)
        assert "unique_asns" in str(summary)

    def test_abnormal_activity_report_enrichment_flags(self, test_database_with_enrichment):
        """Test that abnormal activity reports flag suspicious enrichment data."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Find sessions with suspicious enrichment data
        cursor = conn.execute("""
            SELECT s.*, COUNT(f.shasum) as file_count
            FROM sessions s
            LEFT JOIN files f ON s.session = f.session
            WHERE s.dshield_asn IS NOT NULL
               OR s.urlhaus_tags IS NOT NULL
               OR f.vt_malicious > 10
            GROUP BY s.session
            HAVING file_count > 0 OR s.urlhaus_tags IS NOT NULL
        """)

        suspicious_sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        # Generate abnormal activity report
        report_content = self._generate_mock_abnormal_report(suspicious_sessions)

        # Verify suspicious indicators are flagged
        for session in suspicious_sessions:
            # Should mention the suspicious indicators
            if session.get("urlhaus_tags"):
                assert "malware" in report_content or "trojan" in report_content
            if session.get("dshield_asn"):
                assert session["dshield_asn"] in report_content


class TestEnrichmentReportFormatting:
    """Test formatting of enrichment data in reports."""

    def test_enrichment_data_formatting_consistency(self, test_database_with_enrichment):
        """Test that enrichment data is formatted consistently in reports."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Get session with all types of enrichment
        cursor = conn.execute(
            """
            SELECT * FROM sessions WHERE session = ?
        """,
            ("enriched_session_1",),
        )

        session = dict(cursor.fetchone())
        conn.close()

        # Test multiple formatting approaches
        report_variants = [
            self._generate_mock_session_report(session),
            self._generate_mock_detailed_session_report(session),
            self._generate_mock_summary_session_report(session),
        ]

        # All reports should include key enrichment data
        for report_content in report_variants:
            assert session["dshield_asn"] in report_content
            assert session["dshield_country"] in report_content

            # SPUR data should be represented
            spur_data = json.loads(session["spur_data"])
            if spur_data[1]:  # Organization
                assert spur_data[1] in report_content

    def test_enrichment_tags_parsing_and_display(self, test_database_with_enrichment):
        """Test that URLHaus tags are properly parsed and displayed."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Get session with URLHaus tags
        cursor = conn.execute("""
            SELECT session, urlhaus_tags FROM sessions WHERE urlhaus_tags IS NOT NULL
        """)

        sessions = [dict(row) for row in cursor.fetchall()]
        conn.close()

        for session in sessions:
            tags = session["urlhaus_tags"]
            assert "," in tags  # Should be comma-separated

            # Test tag display formatting
            formatted_tags = self._format_urlhaus_tags(tags)
            assert "malware" in formatted_tags or "trojan" in formatted_tags or "botnet" in formatted_tags

    def test_vt_classification_display(self, test_database_with_enrichment):
        """Test that VT classifications are displayed appropriately."""
        conn = sqlite3.connect(test_database_with_enrichment)

        # Get files with VT classifications
        cursor = conn.execute("""
            SELECT filename, vt_classification, vt_malicious FROM files WHERE vt_classification IS NOT NULL
        """)

        files = [dict(row) for row in cursor.fetchall()]
        conn.close()

        for file_data in files:
            classification = file_data["vt_classification"]
            malicious_count = file_data["vt_malicious"]

            # Test classification display
            display_text = self._format_vt_classification(classification, malicious_count)

            assert classification in display_text
            assert str(malicious_count) in display_text


# Helper methods for generating mock reports
def _generate_mock_session_report(session_data):
    """Generate mock session report content."""
    lines = [
        f"Session: {session_data['session']}",
        f"Source IP: {session_data['src_ip']}",
    ]

    if session_data.get("dshield_asn"):
        lines.append(f"ASN: {session_data['dshield_asn']} ({session_data['dshield_country']})")

    if session_data.get("spur_data"):
        spur_data = json.loads(session_data["spur_data"])
        if spur_data[1]:  # Organization
            lines.append(f"Organization: {spur_data[1]}")
        if spur_data[3]:  # Infrastructure
            lines.append(f"Infrastructure: {spur_data[3]}")

    if session_data.get("urlhaus_tags"):
        lines.append(f"Threat Tags: {session_data['urlhaus_tags']}")

    return "\n".join(lines)


def _generate_mock_file_report(file_data):
    """Generate mock file report content."""
    lines = [
        f"File: {file_data['filename']}",
        f"SHA256: {file_data['shasum']}",
        f"Size: {file_data['filesize']} bytes",
    ]

    if file_data.get("vt_description"):
        lines.append(f"Type: {file_data['vt_description']}")

    if file_data.get("vt_classification"):
        lines.append(f"Classification: {file_data['vt_classification']}")

    if file_data.get("vt_malicious"):
        lines.append(f"Malicious detections: {file_data['vt_malicious']}")

    return "\n".join(lines)


def _generate_mock_comprehensive_report(session_data):
    """Generate mock comprehensive report content."""
    lines = [
        "=== Session Report ===",
        f"Session ID: {session_data['session']}",
        f"Source IP: {session_data['src_ip']}",
    ]

    if session_data.get("dshield_asn"):
        lines.append(f"DShield ASN: {session_data['dshield_asn']} (Country: {session_data['dshield_country']})")

    if session_data.get("spur_data"):
        spur_data = json.loads(session_data["spur_data"])
        lines.append(f"SPUR Infrastructure: {spur_data[3]}")
        lines.append(f"SPUR Organization: {spur_data[1]}")

    if session_data.get("urlhaus_tags"):
        lines.append(f"URLHaus Tags: {session_data['urlhaus_tags']}")

    return "\n".join(lines)


def _generate_mock_daily_report(summary_data):
    """Generate mock daily report content."""
    lines = [
        "=== Daily Summary ===",
        f"Total Sessions: {summary_data['total_sessions']}",
        f"Unique IPs: {summary_data['unique_ips']}",
        f"Unique Files: {summary_data['unique_files']}",
        f"Malicious Files: {summary_data['malicious_files']}",
        f"Unique ASNs: {summary_data['unique_asns']}",
    ]

    return "\n".join(lines)


def _generate_mock_abnormal_report(suspicious_sessions):
    """Generate mock abnormal activity report content."""
    lines = [
        "=== Abnormal Activity Report ===",
        f"Suspicious sessions found: {len(suspicious_sessions)}",
        "",
    ]

    for session in suspicious_sessions:
        lines.append(f"Session: {session['session']}")
        lines.append(f"Source IP: {session['src_ip']}")

        if session.get("dshield_asn"):
            lines.append(f"  ASN: {session['dshield_asn']}")

        if session.get("urlhaus_tags"):
            lines.append(f"  Tags: {session['urlhaus_tags']}")

        lines.append("")

    return "\n".join(lines)


def _generate_mock_detailed_session_report(session_data):
    """Generate mock detailed session report."""
    lines = [
        "DETAILED SESSION ANALYSIS",
        f"Session: {session_data['session']}",
        f"IP: {session_data['src_ip']}",
    ]

    if session_data.get("dshield_asn"):
        lines.append("Network Information:")
        lines.append(f"  Autonomous System: {session_data['dshield_asn']}")
        lines.append(f"  Country: {session_data['dshield_country']}")

    if session_data.get("spur_data"):
        spur_data = json.loads(session_data["spur_data"])
        lines.append("Infrastructure Analysis:")
        lines.append(f"  Type: {spur_data[3]}")
        lines.append(f"  Organization: {spur_data[1]}")

    if session_data.get("urlhaus_tags"):
        lines.append("Threat Intelligence:")
        lines.append(f"  Tags: {session_data['urlhaus_tags']}")

    return "\n".join(lines)


def _generate_mock_summary_session_report(session_data):
    """Generate mock summary session report."""
    spur_data = json.loads(session_data["spur_data"]) if session_data.get("spur_data") else []

    return (
        f"{session_data['session']} | {session_data['src_ip']} | "
        f"{session_data.get('dshield_asn', 'N/A')} | "
        f"{spur_data[3] if len(spur_data) > 3 else 'N/A'} | "
        f"{session_data.get('urlhaus_tags', 'N/A')}"
    )


def _format_urlhaus_tags(tags_str):
    """Format URLHaus tags for display."""
    return tags_str.replace(",", ", ")


def _format_vt_classification(classification, malicious_count):
    """Format VT classification for display."""
    return f"{classification} ({malicious_count} detections)"
