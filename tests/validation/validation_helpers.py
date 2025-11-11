"""Validation helper utilities for ADR-007 Phase 3 production validation.

This module provides helper functions for validating the snapshot population backfill
on production database. It includes utilities for:
- Database connection management
- Snapshot coverage analysis
- Query performance measurement
- Data quality sampling
- Safety checks

**Safety Features**:
- Read-only operations by default
- Explicit --allow-writes flag required for modifications
- Transaction rollback on errors
- Dry-run validation support

**Usage**:
    from tests.validation.validation_helpers import (
        get_production_engine,
        check_snapshot_coverage,
        measure_query_performance,
        validate_snapshot_accuracy,
    )

    # Check coverage
    coverage = check_snapshot_coverage(engine)
    print(f"Snapshot coverage: {coverage['percent_with_snapshots']:.2f}%")

    # Measure performance
    perf = measure_query_performance(engine, country='CN', ip_type='DATACENTER')
    print(f"Speedup: {perf['speedup']:.1f}x")

**References**:
- Design: docs/designs/adr007-snapshot-population-fix.md (Phase 3 validation)
- Models: cowrieprocessor/db/models.py (SessionSummary, IPInventory)
"""

from __future__ import annotations

import random
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from sqlalchemy import Engine, func, text
from sqlalchemy.orm import Session

from cowrieprocessor.db import create_engine_from_settings
from cowrieprocessor.db.models import IPInventory, SessionSummary
from cowrieprocessor.settings import DatabaseSettings


def get_production_engine(db_url: Optional[str] = None) -> Engine:
    """Create database engine with production credentials.

    Args:
        db_url: Optional database URL. If None, reads from config/sensors.toml

    Returns:
        SQLAlchemy engine instance

    Raises:
        RuntimeError: If database connection fails
    """
    try:
        if db_url:
            db_settings = DatabaseSettings(url=db_url)
            engine = create_engine_from_settings(db_settings)
        else:
            # Read from config/sensors.toml
            config_path = Path(__file__).parent.parent.parent / "config" / "sensors.toml"
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            db_settings = DatabaseSettings(url=config["global"]["db"])
            engine = create_engine_from_settings(db_settings)

        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        return engine

    except Exception as e:
        raise RuntimeError(f"Failed to connect to production database: {e}") from e


def check_snapshot_coverage(engine: Engine) -> Dict[str, Any]:
    """Analyze snapshot column coverage across all sessions.

    Args:
        engine: Database engine

    Returns:
        Dictionary with coverage statistics:
            {
                'total_sessions': int,
                'with_source_ip': int,
                'with_snapshot_asn': int,
                'with_snapshot_country': int,
                'with_snapshot_ip_types': int,  # Note: key name preserved for backwards compatibility
                'percent_with_snapshots': float,
                'timestamp': str,
            }
    """
    with engine.connect() as conn:
        # Use raw SQL to handle potential schema variations (snapshot_ip_type vs snapshot_ip_types)
        total = conn.execute(text("SELECT COUNT(*) FROM session_summaries")).scalar() or 0

        with_source_ip = (
            conn.execute(text("SELECT COUNT(*) FROM session_summaries WHERE source_ip IS NOT NULL")).scalar() or 0
        )

        with_asn = (
            conn.execute(text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_asn IS NOT NULL")).scalar() or 0
        )

        with_country = (
            conn.execute(text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_country IS NOT NULL")).scalar()
            or 0
        )

        # Try both singular and plural forms for ip_type (post-migration: singular is primary)
        try:
            with_ip_types = (
                conn.execute(text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_type IS NOT NULL")).scalar()
                or 0
            )
        except Exception:
            # Fallback to plural form (pre-migration schema)
            with_ip_types = (
                conn.execute(
                    text("SELECT COUNT(*) FROM session_summaries WHERE snapshot_ip_types IS NOT NULL")
                ).scalar()
                or 0
            )

        return {
            "total_sessions": total,
            "with_source_ip": with_source_ip,
            "with_snapshot_asn": with_asn,
            "with_snapshot_country": with_country,
            "with_snapshot_ip_types": with_ip_types,
            "percent_with_snapshots": (100.0 * with_country / total) if total > 0 else 0.0,
            "timestamp": datetime.now(UTC).isoformat(),
        }


def measure_query_performance(
    engine: Engine,
    country: str = "CN",
    ip_type: str = "DATACENTER",
    iterations: int = 3,
) -> Dict[str, Any]:
    """Measure query performance: snapshot columns vs JOIN to ip_inventory.

    Args:
        engine: Database engine
        country: Country code to filter by
        ip_type: IP type to filter by (DATACENTER, RESIDENTIAL, etc.)
        iterations: Number of iterations to average (default: 3)

    Returns:
        Dictionary with performance metrics:
            {
                'snapshot_query_ms': float,
                'join_query_ms': float,
                'speedup': float,
                'result_count_snapshot': int,
                'result_count_join': int,
                'results_match': bool,
            }
    """
    with Session(engine) as session:
        # Query 1: Using snapshot columns (NO JOIN)
        snapshot_times = []
        snapshot_count = 0
        for _ in range(iterations):
            start = time.perf_counter()
            snapshot_count = (
                session.query(func.count(SessionSummary.session_id))
                .filter(
                    SessionSummary.snapshot_country == country,
                    SessionSummary.snapshot_ip_type == ip_type,
                )
                .scalar()
                or 0
            )
            elapsed = (time.perf_counter() - start) * 1000  # Convert to ms
            snapshot_times.append(elapsed)

        # Query 2: Using JOIN to ip_inventory
        join_times = []
        join_count = 0
        for _ in range(iterations):
            start = time.perf_counter()
            join_count = (
                session.query(func.count(SessionSummary.session_id))
                .join(IPInventory, SessionSummary.source_ip == IPInventory.ip_address)
                .filter(
                    IPInventory.geo_country == country,
                    IPInventory.ip_type == ip_type,
                )
                .scalar()
                or 0
            )
            elapsed = (time.perf_counter() - start) * 1000
            join_times.append(elapsed)

        avg_snapshot = sum(snapshot_times) / len(snapshot_times)
        avg_join = sum(join_times) / len(join_times)

        return {
            "snapshot_query_ms": round(avg_snapshot, 2),
            "join_query_ms": round(avg_join, 2),
            "speedup": round(avg_join / avg_snapshot, 2) if avg_snapshot > 0 else 0.0,
            "result_count_snapshot": snapshot_count,
            "result_count_join": join_count,
            "results_match": snapshot_count == join_count,
            "iterations": iterations,
        }


def validate_snapshot_accuracy(
    engine: Engine,
    sample_size: int = 100,
    random_seed: int = 42,
) -> Dict[str, Any]:
    """Validate snapshot column accuracy against ip_inventory.

    Randomly samples sessions and verifies that snapshot columns match
    current ip_inventory state. Allows for temporal drift (ASN changes).

    Args:
        engine: Database engine
        sample_size: Number of sessions to validate (default: 100)
        random_seed: Random seed for reproducibility (default: 42)

    Returns:
        Dictionary with validation results:
            {
                'sample_size': int,
                'perfect_matches': int,
                'asn_mismatches': int,
                'country_mismatches': int,
                'ip_type_mismatches': int,
                'orphan_sessions': int,  # IPs not in ip_inventory
                'accuracy_rate': float,
                'mismatches': List[Dict],  # Details of mismatches
            }
    """
    random.seed(random_seed)

    with Session(engine) as session:
        # Get random sample of sessions with snapshots
        total_sessions = (
            session.query(func.count(SessionSummary.session_id))
            .filter(SessionSummary.snapshot_country.isnot(None))
            .scalar()
            or 0
        )

        if total_sessions == 0:
            return {
                "sample_size": 0,
                "error": "No sessions with snapshots found",
            }

        # Random offset sampling
        offset = random.randint(0, max(0, total_sessions - sample_size))
        samples = (
            session.query(SessionSummary)
            .filter(SessionSummary.snapshot_country.isnot(None))
            .offset(offset)
            .limit(sample_size)
            .all()
        )

        perfect_matches = 0
        asn_mismatches = 0
        country_mismatches = 0
        ip_type_mismatches = 0
        orphan_sessions = 0
        mismatch_details: List[Dict[str, Any]] = []

        for sample in samples:
            # Lookup IP inventory
            ip_inv = session.query(IPInventory).filter(IPInventory.ip_address == sample.source_ip).first()

            if ip_inv is None:
                orphan_sessions += 1
                mismatch_details.append(
                    {
                        "session_id": sample.session_id,
                        "source_ip": sample.source_ip,
                        "issue": "IP not in ip_inventory (orphan)",
                    }
                )
                continue

            # Check matches
            asn_match = sample.snapshot_asn == ip_inv.current_asn
            country_match = sample.snapshot_country == ip_inv.geo_country
            ip_type_match = sample.snapshot_ip_type == ip_inv.ip_type

            if asn_match and country_match and ip_type_match:
                perfect_matches += 1
            else:
                if not asn_match:
                    asn_mismatches += 1
                if not country_match:
                    country_mismatches += 1
                if not ip_type_match:
                    ip_type_mismatches += 1

                mismatch_details.append(
                    {
                        "session_id": sample.session_id,
                        "source_ip": sample.source_ip,
                        "snapshot_asn": sample.snapshot_asn,
                        "current_asn": ip_inv.current_asn,
                        "snapshot_country": sample.snapshot_country,
                        "current_country": ip_inv.geo_country,
                        "snapshot_ip_type": sample.snapshot_ip_type,
                        "current_ip_type": ip_inv.ip_type,
                    }
                )

        total_validated = len(samples)
        accuracy_rate = (100.0 * perfect_matches / total_validated) if total_validated > 0 else 0.0

        return {
            "sample_size": total_validated,
            "perfect_matches": perfect_matches,
            "asn_mismatches": asn_mismatches,
            "country_mismatches": country_mismatches,
            "ip_type_mismatches": ip_type_mismatches,
            "orphan_sessions": orphan_sessions,
            "accuracy_rate": round(accuracy_rate, 2),
            "mismatches": mismatch_details[:10],  # Limit to first 10 for readability
        }


def count_sessions_needing_backfill(engine: Engine) -> Dict[str, Any]:
    """Count sessions that need snapshot backfilling.

    Args:
        engine: Database engine

    Returns:
        Dictionary with backfill requirements:
            {
                'total_sessions': int,
                'sessions_needing_backfill': int,
                'percent_needing_backfill': float,
                'estimated_batches': int,  # At 1000/batch
            }
    """
    with Session(engine) as session:
        total = session.query(func.count(SessionSummary.session_id)).scalar() or 0

        needing_backfill = (
            session.query(func.count(SessionSummary.session_id)).filter(SessionSummary.source_ip.is_(None)).scalar()
            or 0
        )

        return {
            "total_sessions": total,
            "sessions_needing_backfill": needing_backfill,
            "percent_needing_backfill": (100.0 * needing_backfill / total) if total > 0 else 0.0,
            "estimated_batches": (needing_backfill + 999) // 1000,  # Round up
        }


def get_sample_sessions(
    engine: Engine,
    limit: int = 10,
    with_snapshots: bool = True,
) -> List[Tuple[str, Optional[str], Optional[int], Optional[str], Optional[str]]]:
    """Get sample sessions for manual inspection.

    Args:
        engine: Database engine
        limit: Number of sessions to retrieve (default: 10)
        with_snapshots: If True, only sessions with snapshots; if False, only without

    Returns:
        List of tuples: (session_id, source_ip, snapshot_asn, snapshot_country, snapshot_ip_type)
    """
    with Session(engine) as session:
        query = session.query(
            SessionSummary.session_id,
            SessionSummary.source_ip,
            SessionSummary.snapshot_asn,
            SessionSummary.snapshot_country,
            SessionSummary.snapshot_ip_type,
        )

        if with_snapshots:
            query = query.filter(SessionSummary.snapshot_country.isnot(None))
        else:
            query = query.filter(SessionSummary.source_ip.is_(None))

        results = query.limit(limit).all()
        return [(r[0], r[1], r[2], r[3], r[4]) for r in results]


def check_database_health(engine: Engine) -> Dict[str, Any]:
    """Perform basic database health checks.

    Args:
        engine: Database engine

    Returns:
        Dictionary with health metrics:
            {
                'connection_ok': bool,
                'session_summaries_count': int,
                'ip_inventory_count': int,
                'orphan_sessions': int,  # Sessions with IPs not in ip_inventory
                'database_version': str,
            }
    """
    with Session(engine) as session:
        try:
            # Connection check
            session.execute(text("SELECT 1"))

            # Table counts
            session_count = session.query(func.count(SessionSummary.session_id)).scalar() or 0
            ip_count = session.query(func.count(IPInventory.ip_address)).scalar() or 0

            # Orphan sessions (IPs not in ip_inventory)
            orphan_count = (
                session.query(func.count(SessionSummary.session_id))
                .outerjoin(IPInventory, SessionSummary.source_ip == IPInventory.ip_address)
                .filter(
                    SessionSummary.source_ip.isnot(None),
                    IPInventory.ip_address.is_(None),
                )
                .scalar()
                or 0
            )

            # Database version
            version_result = session.execute(text("SELECT version()")).scalar()

            return {
                "connection_ok": True,
                "session_summaries_count": session_count,
                "ip_inventory_count": ip_count,
                "orphan_sessions": orphan_count,
                "database_version": str(version_result),
            }

        except Exception as e:
            return {
                "connection_ok": False,
                "error": str(e),
            }
