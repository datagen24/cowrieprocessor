"""Longtail threat analysis for detecting rare, unusual, and emerging attack patterns."""

from __future__ import annotations

import hashlib
import logging
import pickle
import resource
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import psutil
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import SessionSummary

logger = logging.getLogger(__name__)


@dataclass
class LongtailAnalysisResult:
    """Results from longtail analysis."""
    
    # Detection counts
    rare_command_count: int = 0
    anomalous_sequence_count: int = 0
    outlier_session_count: int = 0
    emerging_pattern_count: int = 0
    high_entropy_payload_count: int = 0
    
    # Analysis metadata
    total_events_analyzed: int = 0
    total_sessions_analyzed: int = 0
    analysis_duration_seconds: float = 0.0
    
    # Feature flags
    vector_analysis_enabled: bool = False
    pgvector_available: bool = False
    
    # Results storage
    rare_commands: List[Dict[str, Any]] = field(default_factory=list)
    anomalous_sequences: List[Dict[str, Any]] = field(default_factory=list)
    outlier_sessions: List[Dict[str, Any]] = field(default_factory=list)
    emerging_patterns: List[Dict[str, Any]] = field(default_factory=list)
    high_entropy_payloads: List[Dict[str, Any]] = field(default_factory=list)
    
    # Statistical summary
    statistical_summary: Dict[str, Any] = field(default_factory=dict)


class CommandVectorizer:
    """Persistent vocabulary management for consistent vectorization."""

    def __init__(
        self,
        vocab_path: Optional[Path] = None,
        max_features: int = 128,
        ngram_range: Tuple[int, int] = (1, 3)
    ) -> None:
        """Initialize command vectorizer with persistent vocabulary.

        Args:
            vocab_path: Path to save/load vocabulary (optional)
            max_features: Maximum number of features for TF-IDF
            ngram_range: Range of n-grams to extract
        """
        self.vocab_path = vocab_path or Path('/var/lib/cowrie-processor/vocab.pkl')
        self.max_features = max_features
        self.ngram_range = ngram_range
        self.vectorizer = self._load_or_create_vectorizer()
        self.is_fitted = hasattr(self.vectorizer, 'vocabulary_') and len(self.vectorizer.vocabulary_) > 0

    def _load_or_create_vectorizer(self) -> TfidfVectorizer:
        """Load existing vocabulary or create new."""
        if self.vocab_path.exists():
            try:
                with open(self.vocab_path, 'rb') as f:
                    return pickle.load(f)
            except (pickle.PickleError, FileNotFoundError, EOFError):
                logger.warning(f"Could not load vocabulary from {self.vocab_path}, creating new")

        return TfidfVectorizer(
            max_features=self.max_features,
            ngram_range=self.ngram_range,
            stop_words=None,  # Commands don't have stop words
            lowercase=False,  # Preserve command case
            token_pattern=r'\b\w+\b',  # Simple word tokenization
        )

    def fit_transform(self, command_sequences: List[str]) -> np.ndarray:
        """Fit vectorizer and transform command sequences.

        Args:
            command_sequences: List of command sequences as strings

        Returns:
            TF-IDF matrix as numpy array
        """
        tfidf_matrix = self.vectorizer.fit_transform(command_sequences)
        self.is_fitted = True
        self._save_vectorizer()
        return tfidf_matrix.toarray()

    def transform(self, command_sequences: List[str]) -> np.ndarray:
        """Transform command sequences using fitted vectorizer.

        Args:
            command_sequences: List of command sequences as strings

        Returns:
            TF-IDF matrix as numpy array
        """
        if not self.is_fitted:
            raise ValueError("Vectorizer must be fitted before transform")

        tfidf_matrix = self.vectorizer.transform(command_sequences)
        return tfidf_matrix.toarray()

    def update_vocabulary(self, new_commands: List[str]) -> None:
        """Incrementally update vocabulary without full retrain."""
        existing_vocab = set(self.vectorizer.vocabulary_.keys())
        new_unique = set(new_commands) - existing_vocab

        if new_unique:
            logger.info(f"Updating vocabulary with {len(new_unique)} new commands")
            # Retrain with combined dataset
            combined_commands = list(existing_vocab) + list(new_unique)
            self.vectorizer.fit(combined_commands)
            self._save_vectorizer()

    def _save_vectorizer(self) -> None:
        """Save vectorizer to persistent storage."""
        try:
            self.vocab_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.vocab_path, 'wb') as f:
                pickle.dump(self.vectorizer, f)
        except Exception as e:
            logger.warning(f"Could not save vocabulary to {self.vocab_path}: {e}")

    def get_feature_names(self) -> List[str]:
        """Get feature names from the vectorizer.

        Returns:
            List of feature names
        """
        if not self.is_fitted:
            raise ValueError("Vectorizer must be fitted before getting feature names")

        return self.vectorizer.get_feature_names_out().tolist()


class LongtailAnalyzer:
    """Detects rare, unusual, and emerging attack patterns using statistical analysis."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        vocab_path: Optional[Path] = None,
        rarity_threshold: float = 0.05,  # Bottom 5% frequency
        sequence_window: int = 5,  # Command sequence window
        cluster_eps: float = 0.3,  # DBSCAN clustering parameter
        min_cluster_size: int = 5,  # Minimum cluster size
        entropy_threshold: float = 0.8,  # High entropy threshold
        sensitivity_threshold: float = 0.95,  # Overall detection threshold
        vector_analysis_enabled: bool = True,  # Enable vector-based analysis
    ) -> None:
        """Initialize longtail analyzer with database access and performance optimizations.

        Args:
            session_factory: SQLAlchemy session factory for database access
            vocab_path: Path to save/load vocabulary (optional)
            rarity_threshold: Threshold for rare command detection (0.0-1.0)
            sequence_window: Number of commands in sequence analysis
            cluster_eps: DBSCAN epsilon parameter for clustering
            min_cluster_size: Minimum cluster size for DBSCAN
            entropy_threshold: Threshold for high entropy detection
            sensitivity_threshold: Overall detection sensitivity
            vector_analysis_enabled: Enable vector-based analysis methods
        """
        self.session_factory = session_factory
        self.rarity_threshold = rarity_threshold
        self.sequence_window = sequence_window
        self.cluster_eps = cluster_eps
        self.min_cluster_size = min_cluster_size
        self.entropy_threshold = entropy_threshold
        self.sensitivity_threshold = sensitivity_threshold
        self.vector_analysis_enabled = vector_analysis_enabled

        # Initialize vectorizer with persistent vocabulary
        self.command_vectorizer = CommandVectorizer(vocab_path)

        # Analysis state
        self._command_frequencies: Dict[str, int] = {}
        self._session_characteristics: List[Dict[str, Any]] = []
        self._command_sequences: List[str] = []

        # Performance optimizations
        self._command_cache: Dict[str, Dict[str, List[str]]] = {}
    
    def analyze(self, sessions: List[SessionSummary], lookback_days: int) -> LongtailAnalysisResult:
        """Perform longtail analysis on sessions with resource monitoring.

        Args:
            sessions: List of session summaries to analyze
            lookback_days: Number of days of data being analyzed

        Returns:
            LongtailAnalysisResult with analysis findings
        """
        # Monitor resources
        process = psutil.Process()
        start_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Set memory limit (500MB)
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        resource.setrlimit(resource.RLIMIT_AS, (500 * 1024 * 1024, hard))

        start_time = time.perf_counter()

        logger.info(
            "Starting longtail analysis: sessions=%d, lookback=%dd, vector_analysis=%s",
            len(sessions),
            lookback_days,
            self.vector_analysis_enabled,
        )

        # Initialize result
        result = LongtailAnalysisResult()
        result.total_sessions_analyzed = len(sessions)
        result.vector_analysis_enabled = self.vector_analysis_enabled

        if not sessions:
            logger.warning("No sessions provided for analysis")
            return result

        try:
            # Extract commands and build frequency analysis
            self._extract_command_data(sessions)
            result.total_events_analyzed = sum(self._command_frequencies.values())

            # Perform analysis methods
            result.rare_commands = self._detect_rare_commands()
            result.anomalous_sequences = self._detect_anomalous_sequences()
            result.outlier_sessions = self._detect_outlier_sessions()
            result.emerging_patterns = self._detect_emerging_patterns()
            result.high_entropy_payloads = self._detect_high_entropy_payloads(sessions)

            # Update counts
            result.rare_command_count = len(result.rare_commands)
            result.anomalous_sequence_count = len(result.anomalous_sequences)
            result.outlier_session_count = len(result.outlier_sessions)
            result.emerging_pattern_count = len(result.emerging_patterns)
            result.high_entropy_payload_count = len(result.high_entropy_payloads)

            # Generate statistical summary
            result.statistical_summary = self._generate_statistical_summary(result)

        except MemoryError:
            logger.error("Memory limit exceeded, falling back to session-level analysis")
            # Fallback to session-level analysis only
            result.statistical_summary = {
                "analysis_method": "session_level_fallback",
                "error": "Memory limit exceeded",
                "total_sessions": len(sessions),
            }

        # Calculate analysis duration and memory usage
        result.analysis_duration_seconds = time.perf_counter() - start_time
        end_memory = process.memory_info().rss / 1024 / 1024
        result.memory_usage_mb = end_memory - start_memory

        if result.memory_usage_mb > 400:  # Warning threshold
            logger.warning(f"High memory usage: {result.memory_usage_mb:.1f}MB")

        logger.info(
            "Longtail analysis completed: duration=%.2fs, memory=%.1fMB, rare_commands=%d, "
            "anomalous_sequences=%d, outlier_sessions=%d, emerging_patterns=%d, "
            "high_entropy_payloads=%d",
            result.analysis_duration_seconds,
            result.memory_usage_mb,
            result.rare_command_count,
            result.anomalous_sequence_count,
            result.outlier_session_count,
            result.emerging_pattern_count,
            result.high_entropy_payload_count,
        )

        return result
    
    def _calculate_session_duration(self, session: SessionSummary) -> float:
        """Calculate session duration in seconds.
        
        Args:
            session: SessionSummary object
            
        Returns:
            Duration in seconds, or 0 if not calculable
        """
        if session.first_event_at and session.last_event_at:
            duration = (session.last_event_at - session.first_event_at).total_seconds()
            return max(0.0, duration)
        return 0.0
    
    def _extract_command_data(self, sessions: List[SessionSummary]) -> None:
        """Extract command data from sessions for analysis.

        Args:
            sessions: List of session summaries to analyze
        """
        self._command_frequencies = {}
        self._session_characteristics = []
        self._command_sequences = []

        # Extract all session IDs for batch query
        session_ids = [session.session_id for session in sessions]

        # Query commands for all sessions in batches
        commands_by_session = self._extract_commands_for_sessions(session_ids)

        for session in sessions:
            # Get commands for this session
            commands = commands_by_session.get(session.session_id, [])

            # Build command frequency
            for command in commands:
                cmd = command.strip()
                if cmd:
                    self._command_frequencies[cmd] = self._command_frequencies.get(cmd, 0) + 1

            # Build session characteristics
            session_chars = {
                'session_id': session.session_id,
                'src_ip': getattr(session, 'src_ip', None),  # May not exist
                'duration': self._calculate_session_duration(session),
                'command_count': len(commands),
                'login_attempts': session.login_attempts,
                'file_operations': session.file_downloads,  # Use file_downloads instead
                'timestamp': session.first_event_at,  # Use first_event_at instead
            }
            self._session_characteristics.append(session_chars)

            # Build command sequences
            if len(commands) >= self.sequence_window:
                sequence = ' '.join(commands[:self.sequence_window])
                if sequence.strip():
                    self._command_sequences.append(sequence)

    def _extract_commands_for_sessions(self, session_ids: List[str]) -> Dict[str, List[str]]:
        """Query RawEvent table for actual commands with caching and performance optimization.

        Args:
            session_ids: List of session IDs to extract commands for

        Returns:
            Dictionary mapping session_id to list of command strings
        """
        # Add result caching for repeated analyses
        cache_key = hashlib.md5(','.join(sorted(session_ids)).encode()).hexdigest()
        if cache_key in self._command_cache:
            return self._command_cache[cache_key]

        commands_by_session = defaultdict(list)

        try:
            # Use read-only transaction for better performance
            with self.session_factory() as session:
                session.execute(text("SET TRANSACTION READ ONLY"))

                # Optimized raw SQL query for critical performance
                result = session.execute(text("""
                    SELECT session_id, payload->>'input' as command
                    FROM raw_events
                    WHERE session_id = ANY(:session_ids)
                    AND event_type = 'cowrie.command.input'
                    AND payload ? 'input'
                """), {"session_ids": session_ids})

                for row in result:
                    if row.command:
                        commands_by_session[row.session_id].append(row.command)

        except Exception as e:
            logger.error(f"Error extracting commands for sessions {session_ids[:5]}...: {e}")

        # Cache results for this analysis run
        self._command_cache[cache_key] = dict(commands_by_session)
        return dict(commands_by_session)

    def _detect_rare_commands(self) -> List[Dict[str, Any]]:
        """Detect rare commands using frequency analysis."""
        if not self._command_frequencies:
            return []
        
        total_commands = sum(self._command_frequencies.values())
        rare_threshold = int(total_commands * self.rarity_threshold)
        
        rare_commands = []
        for command, frequency in self._command_frequencies.items():
            if frequency <= rare_threshold:
                rarity_score = frequency / total_commands
                rare_commands.append({
                    'command': command,
                    'frequency': frequency,
                    'rarity_score': rarity_score,
                    'detection_type': 'rare_command',
                })
        
        # Sort by rarity (lowest frequency first)
        rare_commands.sort(key=lambda x: int(x['frequency']))
        
        return rare_commands
    
    def _detect_anomalous_sequences(self) -> List[Dict[str, Any]]:
        """Detect anomalous command sequences using clustering."""
        if len(self._command_sequences) < self.min_cluster_size:
            return []
        
        try:
            # Vectorize command sequences
            if self.vector_analysis_enabled:
                vectors = self.command_vectorizer.fit_transform(self._command_sequences)
                
                # Use DBSCAN clustering
                clustering = DBSCAN(
                    eps=self.cluster_eps,
                    min_samples=self.min_cluster_size,
                    metric='cosine',
                )
                cluster_labels = clustering.fit_predict(vectors)
                
                # Find outliers (noise points labeled as -1)
                anomalous_sequences = []
                for i, label in enumerate(cluster_labels):
                    if label == -1:  # Outlier
                        anomalous_sequences.append({
                            'sequence': self._command_sequences[i],
                            'cluster_label': label,
                            'detection_type': 'anomalous_sequence',
                            'anomaly_score': 1.0,  # DBSCAN outliers are high anomaly
                        })
                
                return anomalous_sequences
            else:
                # Fallback to simple frequency-based detection
                sequence_freq: Dict[str, int] = {}
                for seq in self._command_sequences:
                    sequence_freq[seq] = sequence_freq.get(seq, 0) + 1
                
                anomalous_sequences = []
                for seq, freq in sequence_freq.items():
                    if freq == 1:  # Unique sequences
                        anomalous_sequences.append({
                            'sequence': seq,
                            'frequency': freq,
                            'detection_type': 'anomalous_sequence',
                            'anomaly_score': 1.0,
                        })
                
                return anomalous_sequences
                
        except Exception as e:
            logger.error(f"Error in anomalous sequence detection: {e}")
            return []
    
    def _detect_outlier_sessions(self) -> List[Dict[str, Any]]:
        """Detect outlier sessions using behavioral characteristics."""
        if len(self._session_characteristics) < self.min_cluster_size:
            return []
        
        try:
            # Extract numerical features for clustering
            features = []
            for session in self._session_characteristics:
                feature_vector = [
                    session['duration'],
                    session['command_count'],
                    session['login_attempts'],
                    session['file_operations'],
                ]
                features.append(feature_vector)
            
            features_array = np.array(features)
            
            # Use DBSCAN clustering
            clustering = DBSCAN(
                eps=self.cluster_eps,
                min_samples=self.min_cluster_size,
                metric='euclidean',
            )
            cluster_labels = clustering.fit_predict(features_array)
            
            # Find outliers
            outlier_sessions = []
            for i, label in enumerate(cluster_labels):
                if label == -1:  # Outlier
                    session = self._session_characteristics[i]
                    outlier_sessions.append({
                        'session_id': session['session_id'],
                        'src_ip': session['src_ip'],
                        'duration': session['duration'],
                        'command_count': session['command_count'],
                        'login_attempts': session['login_attempts'],
                        'file_operations': session['file_operations'],
                        'cluster_label': label,
                        'detection_type': 'outlier_session',
                        'anomaly_score': 1.0,
                    })
            
            return outlier_sessions
            
        except Exception as e:
            logger.error(f"Error in outlier session detection: {e}")
            return []
    
    def _detect_emerging_patterns(self) -> List[Dict[str, Any]]:
        """Detect emerging patterns using temporal analysis."""
        # This is a simplified implementation
        # In a full implementation, this would analyze patterns over time
        emerging_patterns: List[Dict[str, Any]] = []
        
        # Look for commands that appear in recent sessions but not in older ones
        # For now, return empty list as this requires temporal data
        return emerging_patterns
    
    def _detect_high_entropy_payloads(self, sessions: List[SessionSummary]) -> List[Dict[str, Any]]:
        """Detect high entropy payloads in events."""
        high_entropy_payloads: List[Dict[str, Any]] = []
        
        # This would require access to RawEvent data
        # For now, return empty list as this requires event-level analysis
        return high_entropy_payloads
    
    def _generate_statistical_summary(self, result: LongtailAnalysisResult) -> Dict[str, Any]:
        """Generate statistical summary of analysis results."""
        summary = {
            'analysis_parameters': {
                'rarity_threshold': self.rarity_threshold,
                'sequence_window': self.sequence_window,
                'cluster_eps': self.cluster_eps,
                'min_cluster_size': self.min_cluster_size,
                'entropy_threshold': self.entropy_threshold,
                'sensitivity_threshold': self.sensitivity_threshold,
                'vector_analysis_enabled': self.vector_analysis_enabled,
            },
            'detection_counts': {
                'rare_commands': result.rare_command_count,
                'anomalous_sequences': result.anomalous_sequence_count,
                'outlier_sessions': result.outlier_session_count,
                'emerging_patterns': result.emerging_pattern_count,
                'high_entropy_payloads': result.high_entropy_payload_count,
            },
            'data_characteristics': {
                'total_commands': sum(self._command_frequencies.values()),
                'unique_commands': len(self._command_frequencies),
                'total_sessions': len(self._session_characteristics),
                'command_sequences': len(self._command_sequences),
            },
            'performance_metrics': {
                'analysis_duration_seconds': result.analysis_duration_seconds,
                'events_per_second': (
                    result.total_events_analyzed / result.analysis_duration_seconds 
                    if result.analysis_duration_seconds > 0 else 0
                ),
            },
        }
        
        return summary


__all__ = [
    "LongtailAnalyzer",
    "LongtailAnalysisResult",
    "CommandVectorizer",
]
