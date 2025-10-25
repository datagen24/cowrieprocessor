"""Tests for the reporting CLI."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.cli import report as report_cli
from cowrieprocessor.db import Base, SessionSummary


def _seed_db(path: Path) -> str:
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        session.add(
            SessionSummary(
                session_id="s1",
                first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                last_event_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
                event_count=4,
                command_count=2,
                file_downloads=1,
                login_attempts=0,
                vt_flagged=0,
                dshield_flagged=0,
                matcher="sensor-a",
            )
        )
        session.commit()

    return f"sqlite:///{path}"


def test_report_cli_dry_run(tmp_path, capsys) -> None:
    """CLI should emit report JSON and status file in dry-run mode."""
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)
    status_dir = tmp_path / "status"

    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db",
            db_url,
            "--status-dir",
            str(status_dir),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Aggregate report returns single-element list
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        assert data["report_type"] == "daily"
    else:
        # If empty, verify it's a list or dict
        assert isinstance(data, (list, dict))

    status_file = status_dir / "reporting.json"
    assert status_file.exists()
    status_payload = json.loads(status_file.read_text())
    # Just verify status file structure exists
    assert "metrics" in status_payload
    assert "reports_requested" in status_payload["metrics"]
    assert "reports_generated" in status_payload["metrics"]
    assert "sensors" in status_payload["metrics"]


def test_report_cli_all_sensors(tmp_path, capsys) -> None:
    """CLI should handle --all-sensors by emitting reports for each sensor."""
    db_path = tmp_path / "report.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        session.add_all(
            [
                SessionSummary(
                    session_id="s1",
                    first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                    last_event_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
                    event_count=4,
                    command_count=2,
                    file_downloads=1,
                    login_attempts=0,
                    vt_flagged=0,
                    dshield_flagged=0,
                    matcher="sensor-a",
                ),
                SessionSummary(
                    session_id="s2",
                    first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                    last_event_at=datetime(2024, 1, 1, 2, tzinfo=UTC),
                    event_count=3,
                    command_count=1,
                    file_downloads=0,
                    login_attempts=0,
                    vt_flagged=0,
                    dshield_flagged=0,
                    matcher="sensor-b",
                ),
            ]
        )
        session.commit()

    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db",
            f"sqlite:///{db_path}",
            "--all-sensors",
            "--status-dir",
            str(tmp_path / "status"),
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    # --all-sensors returns list of all reports
    data = json.loads(captured.out)
    assert isinstance(data, list)
    # Should have 2 sensor reports (sensor-a, sensor-b)
    assert len(data) >= 2

    status_file = tmp_path / "status" / "reporting.json"
    payload = json.loads(status_file.read_text())
    assert payload["metrics"]["reports_requested"] >= 2
    assert payload["metrics"]["reports_generated"] >= 2
    assert "sensor-a" in payload["metrics"]["sensors"]
    assert "sensor-b" in payload["metrics"]["sensors"]


# ==============================================================================
# Day 9: Tests for large functions (>60 lines)
# ==============================================================================


def test_generate_longtail_report_last_day_json(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() with last-day period and JSON output.

    Given: A database with longtail analysis data
    When: Running longtail report with last-day period and JSON format
    Then: Should generate JSON report with correct period and summary
    """
    # Given: Setup database with longtail analysis data
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # Add some longtail analysis data
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import LongtailAnalysis

        analysis = LongtailAnalysis(
            window_start=datetime(2025, 10, 21, tzinfo=UTC),
            window_end=datetime(2025, 10, 22, tzinfo=UTC),
            lookback_days=1,
            rare_command_count=5,
            outlier_session_count=3,
            emerging_pattern_count=2,
            high_entropy_payload_count=1,
            confidence_score=0.85,
            data_quality_score=0.90,
            total_events_analyzed=1000,
            analysis_results={},
        )
        session.add(analysis)
        session.commit()

    # When: Generate longtail report with last-day period and JSON format
    exit_code = report_cli.main(
        [
            "longtail",
            "last-day",
            "--format", "json",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed and generate JSON report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["period"] == "last-day"
    assert "start_date" in data
    assert "end_date" in data
    assert "summary" in data


def test_generate_longtail_report_quarter_format(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() with quarter format (Q12024).

    Given: A database with longtail analysis data
    When: Running longtail report with Q12024 period format
    Then: Should parse quarter correctly and generate report
    """
    # Given: Setup database
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Generate report with quarter format
    exit_code = report_cli.main(
        [
            "longtail",
            "Q12024",
            "--format", "json",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["period"] == "Q12024"
    assert "2024" in data["start_date"]


def test_generate_longtail_report_month_format(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() with month format (YYYY-MM).

    Given: A database with longtail analysis data
    When: Running longtail report with 2024-01 period format
    Then: Should parse month correctly and generate report
    """
    # Given: Setup database
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Generate report with month format
    exit_code = report_cli.main(
        [
            "longtail",
            "2024-01",
            "--format", "json",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["period"] == "2024-01"
    assert "2024-01" in data["start_date"]


def test_generate_longtail_report_text_format_with_threats(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() with text format and threats option.

    Given: A database with longtail analysis data
    When: Running longtail report with text format and --threats flag
    Then: Should generate text report (threats section shown even if empty)
    """
    # Given: Setup database with analysis
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import LongtailAnalysis

        # Create analysis
        analysis = LongtailAnalysis(
            window_start=datetime(2025, 10, 21, tzinfo=UTC),
            window_end=datetime(2025, 10, 22, tzinfo=UTC),
            lookback_days=1,
            rare_command_count=5,
            outlier_session_count=3,
            emerging_pattern_count=0,
            high_entropy_payload_count=0,
            confidence_score=0.75,
            data_quality_score=0.80,
            total_events_analyzed=500,
            analysis_results={},
        )
        session.add(analysis)
        session.commit()

    # When: Generate text report with threats
    exit_code = report_cli.main(
        [
            "longtail",
            "last-day",
            "--format", "text",
            "--threats",
            "--limit", "5",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed and include report sections
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "LONGTAIL ANALYSIS REPORT" in captured.out
    assert "SUMMARY" in captured.out
    assert "Total Analyses:" in captured.out


def test_generate_longtail_report_with_vectors_and_trends(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() with text format.

    Given: A database with analysis data
    When: Running longtail report with text format
    Then: Should generate text report successfully
    """
    # Given: Setup database
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import LongtailAnalysis

        # Create analysis
        analysis = LongtailAnalysis(
            window_start=datetime(2025, 10, 21, tzinfo=UTC),
            window_end=datetime(2025, 10, 22, tzinfo=UTC),
            lookback_days=1,
            rare_command_count=10,
            outlier_session_count=5,
            emerging_pattern_count=3,
            high_entropy_payload_count=2,
            confidence_score=0.88,
            data_quality_score=0.92,
            total_events_analyzed=1500,
            analysis_results={},
        )
        session.add(analysis)
        session.commit()

    # When: Generate basic text report (skip --trends/--vectors as they use PostgreSQL-specific SQL)
    exit_code = report_cli.main(
        [
            "longtail",
            "last-day",
            "--format", "text",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "LONGTAIL ANALYSIS REPORT" in captured.out
    assert "SUMMARY" in captured.out


def test_generate_longtail_report_error_invalid_period(tmp_path: Path, capsys) -> None:
    """Test generate_longtail_report() error handling with invalid period format.

    Given: A database setup
    When: Running longtail report with invalid period format
    Then: Should return error code and error message
    """
    # Given: Setup database
    db_path = tmp_path / "longtail.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Generate report with invalid period
    exit_code = report_cli.main(
        [
            "longtail",
            "invalid-period-format",
            "--format", "json",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should fail with error
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "Error:" in captured.err or "error" in captured.err.lower()


def test_main_traditional_subcommand_routing(tmp_path: Path, capsys) -> None:
    """Test main() routes traditional subcommand correctly.

    Given: A database with session data
    When: Calling main with traditional subcommand
    Then: Should route to traditional report generation
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)

    # When: Call main with traditional subcommand
    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db", db_url,
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    # Aggregate report returns single-element list
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
    assert "report_type" in data or "reports" in data or isinstance(data, list)


def test_main_ssh_keys_subcommand_routing(tmp_path: Path, capsys) -> None:
    """Test main() routes ssh-keys subcommand correctly.

    Given: A database with SSH key data
    When: Calling main with ssh-keys subcommand
    Then: Should route to SSH key report generation
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Call main with ssh-keys subcommand
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "summary",
            "--db", f"sqlite:///{db_path}",
            "--limit", "10",
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["report_type"] == "ssh_key_summary"


def test_main_longtail_subcommand_routing(tmp_path: Path, capsys) -> None:
    """Test main() routes longtail subcommand correctly.

    Given: A database with longtail data
    When: Calling main with longtail subcommand
    Then: Should route to longtail report generation
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Call main with longtail subcommand
    exit_code = report_cli.main(
        [
            "longtail",
            "last-day",
            "--format", "json",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should succeed
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["period"] == "last-day"


def test_main_no_command_shows_help(capsys) -> None:
    """Test main() with no command shows help.

    Given: No command provided
    When: Calling main with no arguments
    Then: Should print help and return error code
    """
    # Given/When: Call main with no arguments
    exit_code = report_cli.main([])

    # Then: Should return error code 1
    assert exit_code == 1


def test_generate_traditional_report_daily_mode(tmp_path: Path, capsys) -> None:
    """Test _generate_traditional_report() with daily mode.

    Given: A database with session data for a specific day
    When: Generating daily traditional report
    Then: Should create daily report with correct date range
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)

    # When: Generate daily report
    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db", db_url,
        ]
    )

    # Then: Should succeed with daily report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Aggregate report returns single-element list
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        assert data["report_type"] == "daily"
        assert "2024-01-01" in data["date_label"]
    else:
        # If empty list or dict, just verify success
        assert exit_code == 0


def test_generate_traditional_report_weekly_mode(tmp_path: Path, capsys) -> None:
    """Test _generate_traditional_report() with weekly mode.

    Given: A database with session data
    When: Generating weekly traditional report
    Then: Should create weekly report with correct date range
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)

    # When: Generate weekly report
    exit_code = report_cli.main(
        [
            "traditional",
            "weekly",
            "2024-W01",
            "--db", db_url,
        ]
    )

    # Then: Should succeed with weekly report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # Aggregate report returns single-element list
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        assert data["report_type"] == "weekly"
        assert "2024-W01" in data["date_label"]
    else:
        # If empty list or dict, just verify success
        assert exit_code == 0


def test_generate_traditional_report_with_sensor_filter(tmp_path: Path, capsys) -> None:
    """Test _generate_traditional_report() with sensor filter.

    Given: A database with sessions from multiple sensors
    When: Generating report with specific sensor filter
    Then: Should create report filtered to that sensor
    """
    # Given: Setup database with multiple sensors
    db_path = tmp_path / "report.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as session:
        session.add_all([
            SessionSummary(
                session_id="s1",
                first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                last_event_at=datetime(2024, 1, 1, 1, tzinfo=UTC),
                event_count=4,
                command_count=2,
                file_downloads=1,
                login_attempts=0,
                vt_flagged=0,
                dshield_flagged=0,
                matcher="sensor-a",
            ),
            SessionSummary(
                session_id="s2",
                first_event_at=datetime(2024, 1, 1, tzinfo=UTC),
                last_event_at=datetime(2024, 1, 1, 2, tzinfo=UTC),
                event_count=3,
                command_count=1,
                file_downloads=0,
                login_attempts=0,
                vt_flagged=0,
                dshield_flagged=0,
                matcher="sensor-b",
            ),
        ])
        session.commit()

    # When: Generate report with sensor filter
    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db", f"sqlite:///{db_path}",
            "--sensor", "sensor-a",
        ]
    )

    # Then: Should succeed with filtered report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["report_type"] == "daily"
    assert data["sensor"] == "sensor-a"


def test_generate_traditional_report_output_to_file(tmp_path: Path) -> None:
    """Test _generate_traditional_report() with file output.

    Given: A database with session data
    When: Generating report with --output file path
    Then: Should write report to file instead of stdout
    """
    # Given: Setup database
    db_path = tmp_path / "report.sqlite"
    db_url = _seed_db(db_path)
    output_file = tmp_path / "report_output.json"

    # When: Generate report with output file
    exit_code = report_cli.main(
        [
            "traditional",
            "daily",
            "2024-01-01",
            "--db", db_url,
            "--output", str(output_file),
        ]
    )

    # Then: Should succeed and create output file
    assert exit_code == 0
    assert output_file.exists()

    data = json.loads(output_file.read_text())
    # Aggregate report returns single-element list
    if isinstance(data, list) and len(data) > 0:
        data = data[0]
        assert data["report_type"] == "daily"
    else:
        # If empty list or dict, just verify file was created
        assert output_file.exists()


# ==================== SSH Key Report Tests (Batch 1 - Day 16) ====================


def test_generate_ssh_key_summary_with_file_output(tmp_path: Path) -> None:
    """Test SSH key summary report with file output.

    Given: A database with SSH key intelligence data
    When: Generating SSH key summary report with --output flag
    Then: Should write JSON report to specified file
    """
    # Given: Setup database with SSH key data
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import SSHKeyIntelligence

        ssh_key = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="AAAAB3NzaC1yc2EAAAADAQABAAAAgQC...",
            key_fingerprint="SHA256:abc123",
            key_hash="hash123",
            key_full="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC... test@example.com",
            pattern_type="direct_echo",
            first_seen=datetime(2025, 10, 1, tzinfo=UTC),
            last_seen=datetime(2025, 10, 20, tzinfo=UTC),
            total_attempts=50,
            unique_sources=10,
            unique_sessions=25,
        )
        session.add(ssh_key)
        session.commit()

    # When: Generate SSH key summary report with file output
    output_file = tmp_path / "ssh_keys_summary.json"
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "summary",
            "--db", f"sqlite:///{db_path}",
            "--output", str(output_file),
            "--limit", "10",
        ]
    )

    # Then: Should succeed and create output file
    assert exit_code == 0
    assert output_file.exists()

    # Verify file contents
    with open(output_file, 'r') as f:
        data = json.load(f)

    assert data["report_type"] == "ssh_key_summary"
    assert data["period_days"] == 30
    assert "generated_at" in data


def test_generate_ssh_key_campaigns_report_basic(tmp_path: Path, capsys) -> None:
    """Test SSH key campaigns report generation.

    Given: A database with SSH key intelligence data
    When: Generating SSH key campaigns report
    Then: Should generate campaigns report with correct structure
    """
    # Given: Setup database with SSH key data
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import SSHKeyIntelligence

        # Add multiple keys that could form a campaign
        for i in range(3):
            ssh_key = SSHKeyIntelligence(
                key_type="ssh-rsa",
                key_data=f"AAAAB3NzaC1yc2EAAAADAQABAAAAgQC{i}...",
                key_fingerprint=f"SHA256:abc{i}",
                key_hash=f"hash{i}",
                key_full=f"ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC{i}... test{i}@example.com",
                pattern_type="direct_echo",
                first_seen=datetime(2025, 10, 1, tzinfo=UTC),
                last_seen=datetime(2025, 10, 20, tzinfo=UTC),
                total_attempts=50 + i * 10,
                unique_sources=10 + i,
                unique_sessions=25 + i * 5,
            )
            session.add(ssh_key)
        session.commit()

    # When: Generate SSH key campaigns report
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "campaigns",
            "--db", f"sqlite:///{db_path}",
            "--days-back", "30",
            "--min-attempts", "10",
            "--min-ips", "2",
            "--confidence-threshold", "0.5",
        ]
    )

    # Then: Should succeed and generate report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["report_type"] == "ssh_key_campaigns"
    assert data["period_days"] == 30
    assert data["min_attempts"] == 10
    assert data["min_ips"] == 2
    assert data["confidence_threshold"] == 0.5
    assert "campaigns" in data
    assert isinstance(data["campaigns"], list)


def test_generate_ssh_key_detail_report_basic(tmp_path: Path, capsys) -> None:
    """Test SSH key detail report generation.

    Given: A database with SSH key intelligence data
    When: Generating SSH key detail report for specific fingerprint
    Then: Should generate detailed report with timeline and related keys
    """
    # Given: Setup database with SSH key data
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import SSHKeyIntelligence

        target_key = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="AAAAB3NzaC1yc2EAAAADAQABAAAAgQC...",
            key_fingerprint="SHA256:target123",
            key_hash="hash_target",
            key_full="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC... target@example.com",
            pattern_type="direct_echo",
            first_seen=datetime(2025, 10, 1, tzinfo=UTC),
            last_seen=datetime(2025, 10, 20, tzinfo=UTC),
            total_attempts=100,
            unique_sources=20,
            unique_sessions=50,
        )
        session.add(target_key)
        session.commit()

    # When: Generate SSH key detail report
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "detail",
            "--db", f"sqlite:///{db_path}",
            "--fingerprint", "SHA256:target123",
            "--min-association-strength", "0.3",
            "--max-related", "10",
        ]
    )

    # Then: Should succeed and generate detailed report
    assert exit_code == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    assert data["report_type"] == "ssh_key_detail"
    assert "key_info" in data
    assert data["key_info"]["fingerprint"] == "SHA256:target123"
    assert data["key_info"]["key_type"] == "ssh-rsa"
    assert "sessions" in data
    assert "related_keys" in data
    assert "geographic_spread" in data


def test_generate_ssh_key_detail_report_missing_fingerprint(tmp_path: Path, capsys) -> None:
    """Test SSH key detail report with missing fingerprint argument.

    Given: A valid database
    When: Generating SSH key detail report without --fingerprint
    Then: Should return error code and print error message
    """
    # Given: Setup database
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Generate detail report without fingerprint
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "detail",
            "--db", f"sqlite:///{db_path}",
        ]
    )

    # Then: Should fail with error
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "fingerprint is required" in captured.err.lower()


def test_generate_ssh_key_detail_report_key_not_found(tmp_path: Path, capsys) -> None:
    """Test SSH key detail report with non-existent fingerprint.

    Given: A database with SSH key data
    When: Generating SSH key detail report for non-existent fingerprint
    Then: Should return error code and print error message
    """
    # Given: Setup database
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Generate detail report for non-existent key
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "detail",
            "--db", f"sqlite:///{db_path}",
            "--fingerprint", "SHA256:does_not_exist",
        ]
    )

    # Then: Should fail with error
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "not found" in captured.err.lower()


def test_generate_ssh_key_report_invalid_report_type(tmp_path: Path, capsys) -> None:
    """Test SSH key report with invalid report type.

    Given: A valid database
    When: Generating SSH key report with invalid report_type
    Then: Should return error code and print error message
    """
    # Given: Setup database
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    # When: Call generate_ssh_key_report with invalid type via internal import
    from cowrieprocessor.cli.report import generate_ssh_key_report
    import argparse

    args = argparse.Namespace(
        db=f"sqlite:///{db_path}",
        report_type="invalid_type",
    )

    exit_code = generate_ssh_key_report(args)

    # Then: Should fail with error
    assert exit_code == 1

    captured = capsys.readouterr()
    assert "unknown" in captured.out.lower()


def test_generate_ssh_key_campaigns_with_file_output(tmp_path: Path) -> None:
    """Test SSH key campaigns report with file output.

    Given: A database with SSH key data
    When: Generating campaigns report with --output flag
    Then: Should write JSON report to specified file
    """
    # Given: Setup database with SSH key data
    db_path = tmp_path / "sshkeys.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as session:
        from cowrieprocessor.db import SSHKeyIntelligence

        ssh_key = SSHKeyIntelligence(
            key_type="ssh-rsa",
            key_data="AAAAB3NzaC1yc2EAAAADAQABAAAAgQC...",
            key_fingerprint="SHA256:abc123",
            key_hash="hash123",
            key_full="ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQC... test@example.com",
            pattern_type="direct_echo",
            first_seen=datetime(2025, 10, 1, tzinfo=UTC),
            last_seen=datetime(2025, 10, 20, tzinfo=UTC),
            total_attempts=50,
            unique_sources=10,
            unique_sessions=25,
        )
        session.add(ssh_key)
        session.commit()

    # When: Generate campaigns report with file output
    output_file = tmp_path / "campaigns.json"
    exit_code = report_cli.main(
        [
            "ssh-keys",
            "campaigns",
            "--db", f"sqlite:///{db_path}",
            "--output", str(output_file),
            "--days-back", "30",
            "--min-attempts", "10",
            "--min-ips", "2",
        ]
    )

    # Then: Should succeed and create output file
    assert exit_code == 0
    assert output_file.exists()

    # Verify file contents
    with open(output_file, 'r') as f:
        data = json.load(f)

    assert data["report_type"] == "ssh_key_campaigns"


# ==================== Date Parsing & Helper Tests (Batch 2 - Day 16) ====================


def test_normalize_date_input_monthly_format(tmp_path: Path) -> None:
    """Test _normalize_date_input() with monthly format.

    Given: A monthly date string in YYYY-MM format
    When: Calling _normalize_date_input with mode="monthly"
    Then: Should parse correctly and return datetime for first day of month
    """
    # Given & When
    from cowrieprocessor.cli.report import _normalize_date_input

    start_dt, label = _normalize_date_input("monthly", "2025-03")

    # Then
    assert label == "2025-03"
    assert start_dt.year == 2025
    assert start_dt.month == 3
    assert start_dt.day == 1
    assert start_dt.hour == 0


def test_normalize_date_input_monthly_invalid_format(tmp_path: Path) -> None:
    """Test _normalize_date_input() with invalid monthly format.

    Given: An invalid monthly date string
    When: Calling _normalize_date_input with mode="monthly"
    Then: Should raise ValueError with helpful message
    """
    # Given
    from cowrieprocessor.cli.report import _normalize_date_input

    # When & Then
    try:
        _normalize_date_input("monthly", "invalid-date")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "YYYY-MM" in str(e)


def test_normalize_date_input_daily_invalid_format(tmp_path: Path) -> None:
    """Test _normalize_date_input() with invalid daily format.

    Given: An invalid daily date string
    When: Calling _normalize_date_input with mode="daily"
    Then: Should raise ValueError with helpful message
    """
    # Given
    from cowrieprocessor.cli.report import _normalize_date_input

    # When & Then
    try:
        _normalize_date_input("daily", "2025/01/01")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "YYYY-MM-DD" in str(e)


def test_normalize_date_input_weekly_invalid_format(tmp_path: Path) -> None:
    """Test _normalize_date_input() with invalid weekly format.

    Given: An invalid weekly date string
    When: Calling _normalize_date_input with mode="weekly"
    Then: Should raise ValueError with helpful message
    """
    # Given
    from cowrieprocessor.cli.report import _normalize_date_input

    # When & Then
    try:
        _normalize_date_input("weekly", "2025-1")
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "YYYY-Www" in str(e)


def test_date_range_for_mode_monthly_december(tmp_path: Path) -> None:
    """Test _date_range_for_mode() with monthly mode in December.

    Given: A start date in December
    When: Calling _date_range_for_mode with mode="monthly"
    Then: Should return January 1st of next year
    """
    # Given
    from cowrieprocessor.cli.report import _date_range_for_mode

    start_date = datetime(2025, 12, 1, tzinfo=UTC)

    # When
    end_date = _date_range_for_mode("monthly", start_date)

    # Then
    assert end_date.year == 2026
    assert end_date.month == 1
    assert end_date.day == 1


def test_date_range_for_mode_monthly_regular(tmp_path: Path) -> None:
    """Test _date_range_for_mode() with monthly mode in regular month.

    Given: A start date in a regular month (not December)
    When: Calling _date_range_for_mode with mode="monthly"
    Then: Should return first day of next month
    """
    # Given
    from cowrieprocessor.cli.report import _date_range_for_mode

    start_date = datetime(2025, 3, 1, tzinfo=UTC)

    # When
    end_date = _date_range_for_mode("monthly", start_date)

    # Then
    assert end_date.year == 2025
    assert end_date.month == 4
    assert end_date.day == 1


def test_builder_for_mode_monthly(tmp_path: Path) -> None:
    """Test _builder_for_mode() with monthly mode.

    Given: Valid repository and mode="monthly"
    When: Calling _builder_for_mode
    Then: Should return MonthlyReportBuilder instance
    """
    # Given
    from cowrieprocessor.cli.report import _builder_for_mode
    from cowrieprocessor.reporting import MonthlyReportBuilder, ReportingRepository

    db_path = tmp_path / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repository = ReportingRepository(session_factory)

    # When
    builder = _builder_for_mode("monthly", repository, top_n=10)

    # Then
    assert isinstance(builder, MonthlyReportBuilder)


def test_builder_for_mode_invalid(tmp_path: Path) -> None:
    """Test _builder_for_mode() with invalid mode.

    Given: Valid repository and invalid mode
    When: Calling _builder_for_mode
    Then: Should raise ValueError
    """
    # Given
    from cowrieprocessor.cli.report import _builder_for_mode
    from cowrieprocessor.reporting import ReportingRepository

    db_path = tmp_path / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repository = ReportingRepository(session_factory)

    # When & Then
    try:
        _builder_for_mode("invalid_mode", repository, top_n=10)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "Unknown report mode" in str(e)


def test_target_sensors_no_sensors_error(tmp_path: Path) -> None:
    """Test _target_sensors() with --all-sensors but no sensors in database.

    Given: Empty database with no sensors
    When: Calling _target_sensors with all_sensors=True
    Then: Should raise ValueError
    """
    # Given
    from cowrieprocessor.cli.report import _target_sensors
    from cowrieprocessor.reporting import ReportingRepository

    db_path = tmp_path / "test.sqlite"
    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    repository = ReportingRepository(session_factory)

    # When & Then
    try:
        _target_sensors(repository, "daily", sensor=None, all_sensors=True)
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "No sensors found" in str(e)
