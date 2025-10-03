"""Longtail threat analysis for detecting rare, unusual, and emerging attack patterns."""

from __future__ import annotations

import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np
from sklearn.cluster import DBSCAN
from sklearn.feature_extraction.text import TfidfVectorizer
from sqlalchemy.orm import Session, sessionmaker

from ..db.models import CommandStat, RawEvent, SessionSummary

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
    """Vectorize command sequences using TF-IDF."""
    
    def __init__(self, max_features: int = 1000, ngram_range: Tuple[int, int] = (1, 2)) -> None:
        """Initialize command vectorizer.
        
        Args:
            max_features: Maximum number of features for TF-IDF
            ngram_range: Range of n-grams to extract
        """
        self.vectorizer = TfidfVectorizer(
            max_features=max_features,
            ngram_range=ngram_range,
            stop_words=None,  # Commands don't have stop words
            lowercase=False,  # Preserve command case
            token_pattern=r'\b\w+\b',  # Simple word tokenization
        )
        self.is_fitted = False
    
    def fit_transform(self, command_sequences: List[str]) -> np.ndarray:
        """Fit vectorizer and transform command sequences.
        
        Args:
            command_sequences: List of command sequences as strings
            
        Returns:
            TF-IDF matrix as numpy array
        """
        tfidf_matrix = self.vectorizer.fit_transform(command_sequences)
        self.is_fitted = True
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
        rarity_threshold: float = 0.05,  # Bottom 5% frequency
        sequence_window: int = 5,  # Command sequence window
        cluster_eps: float = 0.3,  # DBSCAN clustering parameter
        min_cluster_size: int = 5,  # Minimum cluster size
        entropy_threshold: float = 0.8,  # High entropy threshold
        sensitivity_threshold: float = 0.95,  # Overall detection threshold
        vector_analysis_enabled: bool = True,  # Enable vector-based analysis
    ) -> None:
        """Initialize longtail analyzer with database access.

        Args:
            session_factory: SQLAlchemy session factory for database access
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

        # Initialize vectorizer
        self.command_vectorizer = CommandVectorizer()

        # Analysis state
        self._command_frequencies: Dict[str, int] = {}
        self._session_characteristics: List[Dict[str, Any]] = []
        self._command_sequences: List[str] = []
    
    def analyze(self, sessions: List[SessionSummary], lookback_days: int) -> LongtailAnalysisResult:
        """Perform longtail analysis on sessions.

        Args:
            sessions: List of session summaries to analyze
            lookback_days: Number of days of data being analyzed

        Returns:
            LongtailAnalysisResult with analysis findings
        """
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
        
        # Calculate analysis duration
        result.analysis_duration_seconds = time.perf_counter() - start_time
        
        logger.info(
            "Longtail analysis completed: duration=%.2fs, rare_commands=%d, "
            "anomalous_sequences=%d, outlier_sessions=%d, emerging_patterns=%d, "
            "high_entropy_payloads=%d",
            result.analysis_duration_seconds,
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
        """Query RawEvent table for actual commands with batching strategy.

        Args:
            session_ids: List of session IDs to extract commands for

        Returns:
            Dictionary mapping session_id to list of command strings
        """
        commands_by_session = defaultdict(list)

        try:
            # Batch query strategy for performance
            batch_size = 1000

            for i in range(0, len(session_ids), batch_size):
                batch_ids = session_ids[i:i + batch_size]

                # Query RawEvent for cowrie.command.input events
                with self.session_factory() as session:
                    events = session.query(RawEvent).filter(
                        RawEvent.session_id.in_(batch_ids),
                        RawEvent.event_type == "cowrie.command.input"
                    ).all()

                    for event in events:
                        if event.payload and isinstance(event.payload, dict):
                            command = event.payload.get('input')
                            if command and isinstance(command, str):
                                commands_by_session[event.session_id].append(command.strip())

        except Exception as e:
            logger.error(f"Error extracting commands for sessions {session_ids[:5]}...: {e}")

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
