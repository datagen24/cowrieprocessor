"""Unit tests for Files table model."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from cowrieprocessor.db.base import Base
from cowrieprocessor.db.models import Files


@pytest.fixture
def engine():
    """Create in-memory SQLite engine for testing."""
    engine = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    """Create database session for testing."""
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


class TestFilesTable:
    """Test Files table model."""

    def test_create_files_record(self, session):
        """Test creating a Files record."""
        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="test.txt",
            file_size=1024,
            download_url="http://example.com/test.txt",
            enrichment_status="pending",
        )

        session.add(file_record)
        session.commit()

        # Verify record was created
        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result is not None
        assert result.session_id == "session123"
        assert result.filename == "test.txt"
        assert result.file_size == 1024
        assert result.download_url == "http://example.com/test.txt"
        assert result.enrichment_status == "pending"

    def test_unique_constraint_session_hash(self, session):
        """Test unique constraint on session_id + shasum."""
        # Create first record
        file_record1 = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="test1.txt",
            enrichment_status="pending",
        )
        session.add(file_record1)
        session.commit()

        # Try to create duplicate
        file_record2 = Files(
            session_id="session123",
            shasum="a" * 64,  # Same session_id and shasum
            filename="test2.txt",
            enrichment_status="pending",
        )
        session.add(file_record2)

        with pytest.raises(Exception):  # IntegrityError or similar
            session.commit()

    def test_different_sessions_same_hash(self, session):
        """Test that same hash can exist for different sessions."""
        # Create record for session1
        file_record1 = Files(
            session_id="session1",
            shasum="a" * 64,
            filename="test1.txt",
            enrichment_status="pending",
        )
        session.add(file_record1)

        # Create record for session2 with same hash
        file_record2 = Files(
            session_id="session2",
            shasum="a" * 64,  # Same hash, different session
            filename="test2.txt",
            enrichment_status="pending",
        )
        session.add(file_record2)

        session.commit()

        # Verify both records exist
        results = session.query(Files).filter_by(shasum="a" * 64).all()
        assert len(results) == 2

    def test_enrichment_status_default(self, session):
        """Test that enrichment_status defaults to 'pending'."""
        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="test.txt",
        )

        session.add(file_record)
        session.commit()

        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result.enrichment_status == "pending"

    def test_vt_enrichment_fields(self, session):
        """Test VirusTotal enrichment fields."""
        vt_first_seen = datetime.now()
        vt_last_analysis = datetime.now()

        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="malware.exe",
            vt_classification="malware",
            vt_description="Trojan",
            vt_malicious=True,
            vt_first_seen=vt_first_seen,
            vt_last_analysis=vt_last_analysis,
            vt_positives=45,
            vt_total=60,
            vt_scan_date=vt_last_analysis,
            enrichment_status="enriched",
        )

        session.add(file_record)
        session.commit()

        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result.vt_classification == "malware"
        assert result.vt_description == "Trojan"
        assert result.vt_malicious is True
        assert result.vt_first_seen == vt_first_seen
        assert result.vt_last_analysis == vt_last_analysis
        assert result.vt_positives == 45
        assert result.vt_total == 60
        assert result.vt_scan_date == vt_last_analysis
        assert result.enrichment_status == "enriched"

    def test_timestamps_auto_generated(self, session):
        """Test that timestamps are auto-generated."""
        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="test.txt",
        )

        session.add(file_record)
        session.commit()

        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result.first_seen is not None
        assert result.last_updated is not None
        assert isinstance(result.first_seen, datetime)
        assert isinstance(result.last_updated, datetime)

    def test_nullable_fields(self, session):
        """Test that optional fields can be null."""
        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            # filename, file_size, download_url are None
            enrichment_status="pending",
        )

        session.add(file_record)
        session.commit()

        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result.filename is None
        assert result.file_size is None
        assert result.download_url is None
        assert result.vt_classification is None
        assert result.vt_description is None
        assert result.vt_malicious is False  # Default value

    def test_vt_malicious_default(self, session):
        """Test that vt_malicious defaults to False."""
        file_record = Files(
            session_id="session123",
            shasum="a" * 64,
            filename="test.txt",
        )

        session.add(file_record)
        session.commit()

        result = session.query(Files).filter_by(shasum="a" * 64).first()
        assert result.vt_malicious is False

    def test_query_by_enrichment_status(self, session):
        """Test querying files by enrichment status."""
        # Create files with different statuses
        pending_file = Files(
            session_id="session1",
            shasum="a" * 64,
            filename="pending.txt",
            enrichment_status="pending",
        )

        enriched_file = Files(
            session_id="session2",
            shasum="b" * 64,
            filename="enriched.txt",
            enrichment_status="enriched",
        )

        failed_file = Files(
            session_id="session3",
            shasum="c" * 64,
            filename="failed.txt",
            enrichment_status="failed",
        )

        session.add_all([pending_file, enriched_file, failed_file])
        session.commit()

        # Query pending files
        pending_files = session.query(Files).filter_by(enrichment_status="pending").all()
        assert len(pending_files) == 1
        assert pending_files[0].filename == "pending.txt"

        # Query enriched files
        enriched_files = session.query(Files).filter_by(enrichment_status="enriched").all()
        assert len(enriched_files) == 1
        assert enriched_files[0].filename == "enriched.txt"

    def test_query_by_vt_malicious(self, session):
        """Test querying files by VT malicious flag."""
        # Create clean and malicious files
        clean_file = Files(
            session_id="session1",
            shasum="a" * 64,
            filename="clean.txt",
            vt_malicious=False,
            enrichment_status="enriched",
        )

        malicious_file = Files(
            session_id="session2",
            shasum="b" * 64,
            filename="malware.exe",
            vt_malicious=True,
            enrichment_status="enriched",
        )

        session.add_all([clean_file, malicious_file])
        session.commit()

        # Query malicious files
        malicious_files = session.query(Files).filter_by(vt_malicious=True).all()
        assert len(malicious_files) == 1
        assert malicious_files[0].filename == "malware.exe"

        # Query clean files
        clean_files = session.query(Files).filter_by(vt_malicious=False).all()
        assert len(clean_files) == 1
        assert clean_files[0].filename == "clean.txt"

    def test_query_by_session_id(self, session):
        """Test querying files by session ID."""
        # Create files for different sessions
        session1_file1 = Files(
            session_id="session1",
            shasum="a" * 64,
            filename="file1.txt",
            enrichment_status="pending",
        )

        session1_file2 = Files(
            session_id="session1",
            shasum="b" * 64,
            filename="file2.txt",
            enrichment_status="pending",
        )

        session2_file1 = Files(
            session_id="session2",
            shasum="c" * 64,
            filename="file3.txt",
            enrichment_status="pending",
        )

        session.add_all([session1_file1, session1_file2, session2_file1])
        session.commit()

        # Query files for session1
        session1_files = session.query(Files).filter_by(session_id="session1").all()
        assert len(session1_files) == 2
        filenames = {f.filename for f in session1_files}
        assert filenames == {"file1.txt", "file2.txt"}

        # Query files for session2
        session2_files = session.query(Files).filter_by(session_id="session2").all()
        assert len(session2_files) == 1
        assert session2_files[0].filename == "file3.txt"
