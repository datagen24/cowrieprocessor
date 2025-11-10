"""Integration tests for ORM sanitization as defense-in-depth (Phase 2)."""

from __future__ import annotations

import unittest

from sqlalchemy.orm import Session

from cowrieprocessor.db.engine import create_engine_from_settings
from cowrieprocessor.db.models import Files, SessionSummary
from cowrieprocessor.settings import DatabaseSettings


class TestORMSanitizationIntegration(unittest.TestCase):
    """Integration tests for ORM-level sanitization as safety net."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Create in-memory SQLite engine
        settings = DatabaseSettings(url="sqlite:///:memory:", enable_orm_sanitization=True)
        self.engine = create_engine_from_settings(settings)

        # Initialize migrations
        from cowrieprocessor.db import apply_migrations

        apply_migrations(self.engine)

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        self.engine.dispose()

    def test_orm_sanitizes_even_if_ingestion_missed(self) -> None:
        """Test that ORM listeners catch dirty data even if Phase 1 sanitization was bypassed.

        This demonstrates the defense-in-depth approach: even if ingestion-time
        sanitization fails or is bypassed, the ORM listeners will still protect
        the database from Unicode control characters.
        """
        # Simulate a scenario where dirty data bypassed Phase 1 sanitization
        # (e.g., direct ORM usage, legacy code path, or ingestion bug)
        with Session(self.engine) as session:
            # Create SessionSummary with dirty enrichment data directly
            dirty_session = SessionSummary(
                session_id="bypass-test-1",
                enrichment={  # type: ignore[arg-type]
                    "malicious": {
                        "field": "value\x00with\x01control\x02chars",
                    }
                },
            )

            session.add(dirty_session)
            session.commit()

            # Query back the data
            retrieved = session.query(SessionSummary).filter(SessionSummary.session_id == "bypass-test-1").one()

            # Verify ORM listener sanitized it before INSERT
            self.assertIsNotNone(retrieved.enrichment)
            self.assertEqual(
                retrieved.enrichment["malicious"]["field"],  # type: ignore[index]
                "valuewithcontrolchars",
            )

    def test_orm_sanitizes_file_metadata_on_insert(self) -> None:
        """Test that ORM listeners sanitize file metadata on INSERT operations."""
        with Session(self.engine) as session:
            # Create Files record with dirty metadata
            dirty_file = Files(
                session_id="bypass-test-file",
                shasum="a" * 64,
                filename="evil\x00.exe",
                download_url="http://bad\x00site.com/malware",
                vt_classification="trojan\x00.generic",
                vt_description="Detected\x00 by AV",
            )

            session.add(dirty_file)
            session.commit()

            # Query back
            retrieved = session.query(Files).filter(Files.shasum == "a" * 64).one()

            # Verify all fields were sanitized
            self.assertEqual(retrieved.filename, "evil.exe")
            self.assertEqual(retrieved.download_url, "http://badsite.com/malware")
            self.assertEqual(retrieved.vt_classification, "trojan.generic")
            self.assertEqual(retrieved.vt_description, "Detected by AV")

    def test_orm_sanitizes_on_update_operations(self) -> None:
        """Test that ORM listeners sanitize data on UPDATE operations."""
        with Session(self.engine) as session:
            # Create clean record
            clean_session = SessionSummary(
                session_id="update-test-1",
                enrichment={"clean": "data"},
            )
            session.add(clean_session)
            session.commit()

            # Update with dirty data
            clean_session.enrichment = {"dirty": "data\x00with\x01nulls"}
            session.commit()

            # Query back
            session.expire_all()  # Force refresh from database
            retrieved = session.query(SessionSummary).filter(SessionSummary.session_id == "update-test-1").one()

            # Verify sanitization happened on UPDATE
            self.assertEqual(retrieved.enrichment["dirty"], "datawithnulls")  # type: ignore[index]

    def test_bulk_insert_with_orm_listeners(self) -> None:
        """Test that ORM listeners work correctly with bulk insert operations."""
        with Session(self.engine) as session:
            # Create multiple dirty records
            dirty_sessions = [
                SessionSummary(
                    session_id=f"bulk-{i}",
                    enrichment={"value": f"data\x00{i}"},
                )
                for i in range(10)
            ]

            session.bulk_save_objects(dirty_sessions)
            session.commit()

            # Query all back
            retrieved = session.query(SessionSummary).filter(SessionSummary.session_id.like("bulk-%")).all()

            # Verify all were sanitized
            self.assertEqual(len(retrieved), 10)
            for i, record in enumerate(sorted(retrieved, key=lambda x: x.session_id)):  # type: ignore[arg-type,return-value]
                self.assertEqual(record.enrichment["value"], f"data{i}")  # type: ignore[index]

    def test_defense_in_depth_with_both_layers(self) -> None:
        """Test that both Phase 1 (ingestion) and Phase 2 (ORM) sanitization work together.

        In production, Phase 1 (ingestion-time sanitization) should catch most
        issues, but Phase 2 (ORM listeners) provides a safety net for edge cases.
        """
        # Simulate Phase 1: Data sanitized during ingestion
        clean_from_phase1 = {
            "dshield": {
                "asname": "ISP Name",  # Already sanitized by Phase 1
                "ascountry": "US",
            }
        }

        # Simulate Phase 2: Additional dirty data added later (bypassed Phase 1)
        dirty_additional = {
            "urlhaus": {
                "tags": "malware\x00,phishing",  # Dirty data from another code path
            }
        }

        with Session(self.engine) as session:
            # Create session with Phase 1 sanitized data
            test_session = SessionSummary(
                session_id="defense-in-depth-1",
                enrichment=clean_from_phase1,
            )
            session.add(test_session)
            session.commit()

            # Later, update with additional dirty data (simulating bypass of Phase 1)
            test_session.enrichment.update(dirty_additional)  # type: ignore[union-attr]
            test_session.enrichment = test_session.enrichment  # Trigger ORM listener
            session.commit()

            # Query back
            session.expire_all()
            retrieved = session.query(SessionSummary).filter(SessionSummary.session_id == "defense-in-depth-1").one()

            # Verify Phase 1 data is still clean
            self.assertEqual(retrieved.enrichment["dshield"]["asname"], "ISP Name")  # type: ignore[index]

            # Verify Phase 2 caught the dirty data that bypassed Phase 1
            self.assertEqual(retrieved.enrichment["urlhaus"]["tags"], "malware,phishing")  # type: ignore[index]

    def test_performance_overhead_acceptable(self) -> None:
        """Test that ORM listener overhead is acceptable for normal operations.

        This is a basic sanity check - full performance benchmarks should be
        done separately with realistic data volumes.
        """
        import time

        with Session(self.engine) as session:
            # Measure time for 100 inserts with listeners enabled
            start = time.time()
            for i in range(100):
                session.add(
                    SessionSummary(
                        session_id=f"perf-test-{i}",
                        enrichment={"data": f"value\x00{i}"},
                    )
                )
            session.commit()
            elapsed_with_listeners = time.time() - start

            # Basic sanity check: should complete in reasonable time (<1 second for 100 records)
            self.assertLess(
                elapsed_with_listeners,
                1.0,
                f"ORM operations took {elapsed_with_listeners:.3f}s for 100 records",
            )


if __name__ == "__main__":
    unittest.main()
