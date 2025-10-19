"""Storage layer for threat detection analysis results."""

from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import (
    LongtailAnalysis,
    LongtailDetection,
    LongtailDetectionSession,
    SessionSummary,
)
from ..db.type_guards import get_enrichment_dict
from .longtail import LongtailAnalysisResult

logger = logging.getLogger(__name__)


def _serialize_for_json(obj: Any) -> Any:
    """Serialize objects for JSON storage, handling datetime and numpy objects.

    Args:
        obj: Object to serialize

    Returns:
        JSON-serializable version of the object
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif hasattr(obj, 'item'):  # Handle numpy scalars (int64, float64, etc.)
        return obj.item()
    elif isinstance(obj, dict):
        return {k: _serialize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_serialize_for_json(item) for item in obj]
    else:
        return obj


def _check_pgvector_available(connection: Any) -> bool:
    """Check if pgvector extension is available (PostgreSQL only).

    Args:
        connection: Database connection

    Returns:
        True if pgvector is available, False otherwise
    """
    try:
        dialect_name = connection.dialect.name
        if dialect_name != 'postgresql':
            logger.debug("pgvector only available for PostgreSQL, skipping vector storage")
            return False

        # Check if pgvector extension is installed
        result = connection.execute(text("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"))
        has_pgvector = result.scalar()

        if has_pgvector:
            logger.info("pgvector extension detected, vector storage enabled")
        else:
            logger.debug("pgvector extension not found, skipping vector storage")

        return bool(has_pgvector)

    except Exception as e:
        logger.warning(f"Error checking pgvector availability: {e}")
        return False


def _store_command_vectors(
    db_session: Session,
    analyzer: Any,
    sessions: List[SessionSummary],
    analysis_id: int,
) -> None:
    """Store command sequence vectors when pgvector is available.

    Args:
        db_session: Database session object
        analyzer: LongtailAnalyzer instance with fitted vectorizer
        sessions: List of analyzed sessions
        analysis_id: ID of the analysis record
    """
    logger.info(f"Starting vector storage for {len(sessions)} sessions, analysis_id={analysis_id}")

    if not _check_pgvector_available(db_session.connection()):
        logger.info("pgvector not available, skipping vector storage")
        return

    try:
        # Extract command sequences and vectors for each session
        vectors_to_store = []

        # Check if analyzer has a fitted vectorizer
        if not hasattr(analyzer, 'command_vectorizer'):
            logger.warning("Analyzer does not have command_vectorizer attribute")
            return

        if not hasattr(analyzer.command_vectorizer, 'transform'):
            logger.warning("command_vectorizer does not have transform method")
            return

        logger.info("Analyzer has command_vectorizer with transform method")

        for session in sessions:
            # Get commands for this session
            session_commands = []
            try:
                result = db_session.execute(
                    text("""
                        SELECT payload->>'input' as input
                        FROM raw_events
                        WHERE session_id = :session_id
                        AND event_type = 'cowrie.command.input'
                        ORDER BY event_timestamp
                    """),
                    {"session_id": session.session_id},
                )

                for row in result:
                    if row.input and row.input.strip():
                        session_commands.append(row.input.strip())

            except Exception as e:
                logger.warning(f"Error extracting commands for session {session.session_id}: {e}")
                continue

            if not session_commands:
                continue

            # Create command sequence string
            sequence = ' '.join(session_commands[: analyzer.sequence_window])
            if not sequence.strip():
                continue

            # Vectorize the sequence
            try:
                logger.debug(f"Vectorizing sequence for session {session.session_id}: {sequence[:100]}...")
                vector = analyzer.command_vectorizer.transform([sequence])
                logger.debug(f"Vector shape: {vector.shape}")
                if vector.shape[1] > 0:  # Ensure we have features
                    # Convert to list for JSON storage
                    vector_list = vector[0].tolist()
                    logger.debug(f"Vector length: {len(vector_list)}")

                    # Extract source IP from session enrichment data
                    src_ip = None
                    enrichment_dict = get_enrichment_dict(session)
                    if enrichment_dict:
                        # Try to get source IP from enrichment data
                        # Look for common patterns in enrichment structure
                        for key, value in enrichment_dict.items():
                            if isinstance(value, dict):
                                # Check if this looks like IP data
                                for sub_key, sub_value in value.items():
                                    try:
                                        import ipaddress

                                        ip_obj = ipaddress.ip_address(sub_key)
                                        if not (ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_private):
                                            src_ip = sub_key
                                            break
                                    except ValueError:
                                        continue
                                if src_ip:
                                    break

                        # If not found in nested structure, try direct lookup
                        if not src_ip:
                            for key in session.enrichment.keys():
                                try:
                                    import ipaddress

                                    ip_obj = ipaddress.ip_address(key)
                                    if not (ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_private):
                                        src_ip = key
                                        break
                                except ValueError:
                                    continue

                    vectors_to_store.append(
                        {
                            'session_id': session.session_id,
                            'command_sequence': sequence,
                            'sequence_vector': vector_list,
                            'timestamp': session.first_event_at or datetime.now(UTC),
                            'source_ip': src_ip or '127.0.0.1',  # Use localhost for unknown IPs
                            'analysis_id': analysis_id,
                        }
                    )

            except Exception as e:
                logger.warning(f"Error vectorizing sequence for session {session.session_id}: {e}")
                continue

        # Bulk insert vectors
        if vectors_to_store:
            logger.info(f"Storing {len(vectors_to_store)} command sequence vectors")

            # Insert into command_sequence_vectors table
            insert_sql = text("""
                INSERT INTO command_sequence_vectors 
                (session_id, command_sequence, sequence_vector, timestamp, source_ip, analysis_id)
                VALUES (:session_id, :command_sequence, :sequence_vector, :timestamp, :source_ip, :analysis_id)
            """)

            db_session.execute(insert_sql, vectors_to_store)
            logger.info(f"Successfully stored {len(vectors_to_store)} vectors")
        else:
            logger.debug("No vectors to store")

    except Exception as e:
        logger.error(f"Error storing command vectors: {e}")


def _create_detection_sessions_links(
    session: Session,
    detection_id: int,
    sessions_metadata: List[Dict[str, Any]],
) -> None:
    """Create junction table entries linking detection to sessions.

    Args:
        session: Database session
        detection_id: ID of the detection record
        sessions_metadata: List of session metadata dictionaries
    """
    if not sessions_metadata:
        return

    try:
        # Create junction table entries
        links_to_create = []

        for session_meta in sessions_metadata:
            session_id = session_meta.get('session_id')
            if session_id:
                links_to_create.append(
                    {
                        'detection_id': detection_id,
                        'session_id': session_id,
                    }
                )

        if links_to_create:
            # Bulk insert junction table entries
            from sqlalchemy import insert

            stmt = insert(LongtailDetectionSession)
            session.execute(stmt, links_to_create)
            logger.debug(f"Created {len(links_to_create)} detection-session links for detection {detection_id}")

    except Exception as e:
        logger.error(f"Error creating detection-session links: {e}")


def store_longtail_analysis(
    session_factory: sessionmaker[Session],
    result: LongtailAnalysisResult,
    window_start: datetime,
    window_end: datetime,
    lookback_days: int,
    analyzer: Optional[Any] = None,
    sessions: Optional[List[SessionSummary]] = None,
) -> int:
    """Store longtail analysis with proper session linking and vector persistence.

    Args:
        session_factory: SQLAlchemy session factory
        result: Analysis results to store
        window_start: Analysis window start time
        window_end: Analysis window end time
        lookback_days: Number of days analyzed
        analyzer: Optional analyzer instance for vector storage
        sessions: Optional sessions list for vector storage

    Returns:
        ID of the stored analysis record

    Raises:
        Exception: If storage fails
    """
    try:
        with session_factory() as db_session:
            # Create main analysis record
            analysis_record = LongtailAnalysis(
                window_start=window_start,
                window_end=window_end,
                lookback_days=lookback_days,
                confidence_score=result.statistical_summary.get("confidence_score", 0.0),
                total_events_analyzed=result.total_events_analyzed,
                rare_command_count=result.rare_command_count,
                anomalous_sequence_count=result.anomalous_sequence_count,
                outlier_session_count=result.outlier_session_count,
                emerging_pattern_count=result.emerging_pattern_count,
                high_entropy_payload_count=result.high_entropy_payload_count,
                analysis_results=_serialize_for_json(
                    {
                        "rare_commands": result.rare_commands,
                        "anomalous_sequences": result.anomalous_sequences,
                        "outlier_sessions": result.outlier_sessions,
                        "emerging_patterns": result.emerging_patterns,
                        "high_entropy_payloads": result.high_entropy_payloads,
                    }
                ),
                statistical_summary=_serialize_for_json(result.statistical_summary),
                analysis_duration_seconds=result.analysis_duration_seconds,
                memory_usage_mb=getattr(result, 'memory_usage_mb', None),
                data_quality_score=result.statistical_summary.get("data_quality_score"),
                enrichment_coverage=result.statistical_summary.get("enrichment_coverage"),
            )

            db_session.add(analysis_record)
            db_session.flush()  # Get the ID
            analysis_id = analysis_record.id

            logger.info(f"Created analysis record with ID {analysis_id}")

            # Store individual detections with proper session linking
            total_detections = 0

            # Store rare command detections
            for detection in result.rare_commands:
                detection_record = LongtailDetection(
                    analysis_id=analysis_id,
                    detection_type="rare_command",
                    session_id=None,  # Will be linked via junction table
                    detection_data=_serialize_for_json(
                        {
                            "command": detection.get("command"),
                            "frequency": detection.get("frequency"),
                            "rarity_score": detection.get("rarity_score"),
                            "session_count": detection.get("session_count", 0),
                            "detection_type": "rare_command",
                        }
                    ),
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("source_ip"),
                )

                db_session.add(detection_record)
                db_session.flush()  # Get the ID

                # Create session links
                sessions_metadata = detection.get("sessions", [])
                _create_detection_sessions_links(db_session, int(detection_record.id), sessions_metadata)
                total_detections += 1

            # Store anomalous sequence detections
            for detection in result.anomalous_sequences:
                detection_record = LongtailDetection(
                    analysis_id=analysis_id,
                    detection_type="anomalous_sequence",
                    session_id=None,
                    detection_data=_serialize_for_json(
                        {
                            "sequence": detection.get("sequence"),
                            "frequency": detection.get("frequency"),
                            "anomaly_score": detection.get("anomaly_score"),
                            "detection_type": "anomalous_sequence",
                        }
                    ),
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("source_ip"),
                )

                db_session.add(detection_record)
                total_detections += 1

            # Store outlier session detections
            for detection in result.outlier_sessions:
                detection_record = LongtailDetection(
                    analysis_id=analysis_id,
                    detection_type="outlier_session",
                    session_id=detection.get("session_id"),
                    detection_data=_serialize_for_json(
                        {
                            "session_id": detection.get("session_id"),
                            "src_ip": detection.get("src_ip"),
                            "duration": detection.get("duration"),
                            "command_count": detection.get("command_count"),
                            "login_attempts": detection.get("login_attempts"),
                            "file_operations": detection.get("file_operations"),
                            "cluster_label": detection.get("cluster_label"),
                            "detection_type": "outlier_session",
                        }
                    ),
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("src_ip"),
                )

                db_session.add(detection_record)
                total_detections += 1

            # Store emerging pattern detections
            for detection in result.emerging_patterns:
                detection_record = LongtailDetection(
                    analysis_id=analysis_id,
                    detection_type="emerging_pattern",
                    session_id=None,
                    detection_data=_serialize_for_json(
                        {
                            "pattern": detection.get("pattern"),
                            "emergence_score": detection.get("emergence_score"),
                            "detection_type": "emerging_pattern",
                        }
                    ),
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("source_ip"),
                )

                db_session.add(detection_record)
                total_detections += 1

            # Store high entropy payload detections
            for detection in result.high_entropy_payloads:
                detection_record = LongtailDetection(
                    analysis_id=analysis_id,
                    detection_type="high_entropy_payload",
                    session_id=None,
                    detection_data=_serialize_for_json(
                        {
                            "payload": detection.get("payload"),
                            "entropy": detection.get("entropy"),
                            "detection_type": "high_entropy_payload",
                        }
                    ),
                    confidence_score=detection.get("confidence_score", 0.0),
                    severity_score=detection.get("severity_score", 0.0),
                    timestamp=detection.get("timestamp", window_start),
                    source_ip=detection.get("source_ip"),
                )

                db_session.add(detection_record)
                total_detections += 1

            # Commit all detection records
            db_session.commit()
            logger.info(f"Stored {total_detections} detection records for analysis {analysis_id}")

            # Store vectors if analyzer and sessions provided
            logger.info(
                f"Checking vector storage conditions: analyzer={analyzer is not None}, sessions={sessions is not None if sessions else False}, vector_analysis_enabled={result.vector_analysis_enabled}"
            )
            if analyzer and sessions and result.vector_analysis_enabled:
                try:
                    _store_command_vectors(db_session, analyzer, sessions, int(analysis_id))
                    result.pgvector_available = True
                    logger.info("Vector storage completed successfully")
                except Exception as e:
                    logger.warning(f"Vector storage failed: {e}")
                    result.pgvector_available = False

            # Commit vector storage if it happened
            if analyzer and sessions and result.vector_analysis_enabled:
                db_session.commit()
                logger.info("Committed vector storage transaction")

            return int(analysis_id)

    except Exception as e:
        logger.error(f"Failed to store longtail analysis: {e}")
        raise


def get_analysis_checkpoint(
    session_factory: sessionmaker[Session],
    checkpoint_date: datetime,
) -> Optional[Dict[str, Any]]:
    """Get analysis checkpoint for a specific date.

    Args:
        session_factory: SQLAlchemy session factory
        checkpoint_date: Date to check for checkpoint

    Returns:
        Checkpoint data if found, None otherwise
    """
    try:
        with session_factory() as session:
            result = session.execute(
                text("""
                    SELECT id, checkpoint_date, window_start, window_end, 
                           sessions_analyzed, vocabulary_hash, last_analysis_id, completed_at
                    FROM longtail_analysis_checkpoints
                    WHERE checkpoint_date = :checkpoint_date
                """),
                {"checkpoint_date": checkpoint_date.date()},
            )

            row = result.fetchone()
            if row:
                return {
                    "id": row.id,
                    "checkpoint_date": row.checkpoint_date,
                    "window_start": row.window_start,
                    "window_end": row.window_end,
                    "sessions_analyzed": row.sessions_analyzed,
                    "vocabulary_hash": row.vocabulary_hash,
                    "last_analysis_id": row.last_analysis_id,
                    "completed_at": row.completed_at,
                }
            return None

    except Exception as e:
        logger.warning(f"Error retrieving checkpoint for {checkpoint_date}: {e}")
        return None


def create_analysis_checkpoint(
    session_factory: sessionmaker[Session],
    checkpoint_date: datetime,
    window_start: datetime,
    window_end: datetime,
    sessions_analyzed: int,
    vocabulary_hash: str,
    analysis_id: int,
) -> None:
    """Create or update analysis checkpoint.

    Args:
        session_factory: SQLAlchemy session factory
        checkpoint_date: Date for checkpoint
        window_start: Analysis window start
        window_end: Analysis window end
        sessions_analyzed: Number of sessions analyzed
        vocabulary_hash: Hash of vocabulary state
        analysis_id: ID of the analysis record
    """
    try:
        with session_factory() as session:
            # Use upsert pattern (INSERT ... ON CONFLICT UPDATE)
            session.execute(
                text("""
                    INSERT INTO longtail_analysis_checkpoints 
                    (checkpoint_date, window_start, window_end, sessions_analyzed, 
                     vocabulary_hash, last_analysis_id, completed_at)
                    VALUES (:checkpoint_date, :window_start, :window_end, :sessions_analyzed,
                            :vocabulary_hash, :analysis_id, :completed_at)
                    ON CONFLICT (checkpoint_date) DO UPDATE SET
                        window_start = EXCLUDED.window_start,
                        window_end = EXCLUDED.window_end,
                        sessions_analyzed = EXCLUDED.sessions_analyzed,
                        vocabulary_hash = EXCLUDED.vocabulary_hash,
                        last_analysis_id = EXCLUDED.last_analysis_id,
                        completed_at = EXCLUDED.completed_at
                """),
                {
                    "checkpoint_date": checkpoint_date.date(),
                    "window_start": window_start,
                    "window_end": window_end,
                    "sessions_analyzed": sessions_analyzed,
                    "vocabulary_hash": vocabulary_hash,
                    "analysis_id": analysis_id,
                    "completed_at": datetime.now(UTC),
                },
            )
            session.commit()
            logger.info(f"Created/updated checkpoint for {checkpoint_date.date()}")

    except Exception as e:
        logger.error(f"Error creating checkpoint: {e}")
        raise


def compute_vocabulary_hash(analyzer: Any) -> str:
    """Compute hash of current vocabulary state for change detection.

    Args:
        analyzer: LongtailAnalyzer instance

    Returns:
        MD5 hash of vocabulary state
    """
    try:
        if not analyzer.command_vectorizer.is_fitted:
            return "unfitted"

        # Get vocabulary and feature names
        vocab = analyzer.command_vectorizer.vectorizer.vocabulary_
        features = analyzer.command_vectorizer.get_feature_names()

        # Create deterministic hash
        vocab_str = str(sorted(vocab.items())) + str(sorted(features))
        return hashlib.md5(vocab_str.encode()).hexdigest()

    except Exception as e:
        logger.warning(f"Error computing vocabulary hash: {e}")
        return "error"
