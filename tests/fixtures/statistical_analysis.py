"""Statistical analysis tools ported from dshield-tooling for testing."""

from __future__ import annotations

import random
import sqlite3
from datetime import datetime
from typing import Any, Dict, List

from tests.fixtures.mock_enrichment_handlers import MockStatisticalAnalyzer


class HoneypotStatisticalAnalyzer:
    """Statistical analysis tools for honeypot data analysis."""

    def __init__(self, db_connection: sqlite3.Connection):
        """Initialize with database connection."""
        self.db = db_connection
        self.mock_analyzer = MockStatisticalAnalyzer(db_connection)

    def analyze_session_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Analyze patterns in honeypot sessions."""
        try:
            # Query session data
            cursor = self.db.execute(
                """
                SELECT
                    src_ip,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen,
                    COUNT(*) as total_sessions,
                    COUNT(DISTINCT DATE(timestamp)) as active_days
                FROM sessions
                WHERE timestamp > datetime('now', '-{} days')
                GROUP BY src_ip
                HAVING total_sessions > 1
            """.format(days)
            )

            sessions = [dict(row) for row in cursor.fetchall()]

            if not sessions:
                return self._get_empty_analysis()

            # Calculate statistics
            total_ips = len(sessions)
            avg_sessions_per_ip = sum(s['total_sessions'] for s in sessions) / total_ips
            avg_active_days = sum(s['active_days'] for s in sessions) / total_ips

            # Find most active IPs
            most_active = sorted(sessions, key=lambda x: x['total_sessions'], reverse=True)[:10]

            return {
                "total_unique_ips": total_ips,
                "avg_sessions_per_ip": round(avg_sessions_per_ip, 2),
                "avg_active_days": round(avg_active_days, 2),
                "most_active_ips": most_active,
                "session_distribution": self._analyze_session_distribution(sessions),
                "temporal_patterns": self._analyze_temporal_patterns(sessions),
            }

        except sqlite3.Error:
            # Return mock data if database query fails
            return self.mock_analyzer.analyze_upload_patterns(days)

    def analyze_command_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Analyze patterns in executed commands."""
        try:
            cursor = self.db.execute(
                """
                SELECT
                    command,
                    COUNT(*) as frequency,
                    COUNT(DISTINCT session) as sessions,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen
                FROM commands
                WHERE timestamp > datetime('now', '-{} days')
                GROUP BY command
                ORDER BY frequency DESC
                LIMIT 50
            """.format(days)
            )

            commands = [dict(row) for row in cursor.fetchall()]

            if not commands:
                return self._get_empty_command_analysis()

            total_commands = sum(c['frequency'] for c in commands)
            unique_commands = len(commands)

            # Analyze command complexity
            command_lengths = [len(c['command']) for c in commands]
            avg_command_length = sum(command_lengths) / len(command_lengths)

            # Find suspicious command patterns
            suspicious_commands = [
                c
                for c in commands
                if any(
                    keyword in c['command'].lower()
                    for keyword in ['wget', 'curl', 'nc ', 'netcat', 'python', 'perl', 'bash', 'sh']
                )
            ]

            return {
                "total_commands": total_commands,
                "unique_commands": unique_commands,
                "avg_command_length": round(avg_command_length, 2),
                "most_common_commands": commands[:20],
                "suspicious_commands": suspicious_commands[:10],
                "command_categories": self._categorize_commands(commands),
            }

        except sqlite3.Error:
            # Return mock data if database query fails
            return {
                "total_commands": random.randint(1000, 10000),
                "unique_commands": random.randint(50, 200),
                "avg_command_length": random.uniform(10, 50),
                "most_common_commands": [
                    {"command": f"command_{i}", "frequency": random.randint(10, 100)} for i in range(10)
                ],
                "suspicious_commands": [
                    {"command": f"suspicious_{i}", "frequency": random.randint(5, 20)} for i in range(5)
                ],
                "command_categories": {
                    "system": random.randint(30, 60),
                    "network": random.randint(20, 40),
                    "file": random.randint(10, 30),
                    "other": random.randint(5, 15),
                },
            }

    def analyze_file_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Analyze patterns in downloaded/uploaded files."""
        try:
            cursor = self.db.execute(
                """
                SELECT
                    f.shasum,
                    f.filename,
                    f.filesize,
                    COUNT(DISTINCT s.src_ip) as unique_sources,
                    MIN(f.timestamp) as first_seen,
                    MAX(f.timestamp) as last_seen,
                    GROUP_CONCAT(DISTINCT s.src_ip) as source_ips
                FROM files f
                JOIN sessions s ON f.session = s.session
                WHERE f.timestamp > datetime('now', '-{} days')
                GROUP BY f.shasum
                ORDER BY unique_sources DESC
            """.format(days)
            )

            files = [dict(row) for row in cursor.fetchall()]

            if not files:
                return self._get_empty_file_analysis()

            # Calculate statistics
            total_files = len(files)
            avg_sources_per_file = sum(f['unique_sources'] for f in files) / total_files

            # File size analysis
            file_sizes = [f['filesize'] for f in files if f['filesize']]
            avg_file_size = sum(file_sizes) / len(file_sizes) if file_sizes else 0

            # Most distributed files
            most_distributed = sorted(files, key=lambda x: x['unique_sources'], reverse=True)[:10]

            return {
                "total_unique_files": total_files,
                "avg_sources_per_file": round(avg_sources_per_file, 2),
                "avg_file_size": round(avg_file_size, 2),
                "most_distributed_files": most_distributed,
                "file_size_distribution": self._analyze_file_sizes(file_sizes),
                "filename_patterns": self._analyze_filename_patterns([f['filename'] for f in files]),
            }

        except sqlite3.Error:
            return self.mock_analyzer.analyze_upload_patterns(days)

    def analyze_attack_velocity(self, days: int = 30) -> Dict[str, Any]:
        """Analyze attack velocity and behavior patterns."""
        try:
            cursor = self.db.execute(
                """
                SELECT
                    src_ip,
                    MIN(timestamp) as first_seen,
                    MAX(timestamp) as last_seen,
                    COUNT(*) as total_events,
                    COUNT(DISTINCT session) as sessions,
                    COUNT(DISTINCT DATE(timestamp)) as active_days
                FROM events
                WHERE timestamp > datetime('now', '-{} days')
                GROUP BY src_ip
                HAVING total_events > 5
            """.format(days)
            )

            attackers = [dict(row) for row in cursor.fetchall()]

            if not attackers:
                return self._get_empty_velocity_analysis()

            # Calculate attack velocity
            for attacker in attackers:
                duration_hours = (
                    datetime.fromisoformat(attacker['last_seen'].replace('Z', '+00:00'))
                    - datetime.fromisoformat(attacker['first_seen'].replace('Z', '+00:00'))
                ).total_seconds() / 3600
                attacker['duration_hours'] = max(duration_hours, 0.1)  # Avoid division by zero
                attacker['events_per_hour'] = attacker['total_events'] / attacker['duration_hours']

            # Classify attacker behavior
            for attacker in attackers:
                events_per_hour = attacker['events_per_hour']
                if events_per_hour < 10:
                    attacker['behavior'] = 'human_like'
                elif events_per_hour < 100:
                    attacker['behavior'] = 'semi_automated'
                elif events_per_hour < 1000:
                    attacker['behavior'] = 'automated'
                else:
                    attacker['behavior'] = 'aggressive_bot'

            # Calculate statistics
            behavior_counts: dict[str, int] = {}
            for attacker in attackers:
                behavior = attacker['behavior']
                behavior_counts[behavior] = behavior_counts.get(behavior, 0) + 1

            velocity_percentiles = self._calculate_percentiles([a['events_per_hour'] for a in attackers])

            return {
                "total_attackers": len(attackers),
                "behavior_distribution": behavior_counts,
                "avg_attack_duration": sum(a['duration_hours'] for a in attackers) / len(attackers),
                "velocity_percentiles": velocity_percentiles,
                "most_active_attackers": sorted(attackers, key=lambda x: x['total_events'], reverse=True)[:10],
            }

        except sqlite3.Error:
            return self.mock_analyzer.analyze_attack_velocity()

    def detect_coordinated_attacks(self, days: int = 7) -> List[Dict[str, Any]]:
        """Detect potentially coordinated attack campaigns."""
        try:
            cursor = self.db.execute(
                """
                SELECT
                    c.command,
                    s.src_ip,
                    s.timestamp,
                    s.session
                FROM commands c
                JOIN sessions s ON c.session = s.session
                WHERE s.timestamp > datetime('now', '-{} days')
                ORDER BY c.command, s.timestamp
            """.format(days)
            )

            command_events = [dict(row) for row in cursor.fetchall()]

            if not command_events:
                return []

            # Group by command pattern
            command_groups: dict[str, list] = {}
            for event in command_events:
                cmd = event['command']
                if cmd not in command_groups:
                    command_groups[cmd] = []
                command_groups[cmd].append(event)

            coordinated = []

            for cmd, events in command_groups.items():
                if len(events) < 5:  # Need multiple events
                    continue

                # Get unique IPs
                unique_ips = list(set(e['src_ip'] for e in events))
                if len(unique_ips) < 3:  # Need multiple IPs for coordination
                    continue

                # Check temporal clustering
                timestamps = [datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')) for e in events]
                timestamps.sort()

                time_diffs = [(timestamps[i + 1] - timestamps[i]).total_seconds() for i in range(len(timestamps) - 1)]

                # Calculate clustering score
                if time_diffs:
                    avg_time_diff = sum(time_diffs) / len(time_diffs)
                    time_std = (sum((d - avg_time_diff) ** 2 for d in time_diffs) / len(time_diffs)) ** 0.5

                    # If events are clustered (low standard deviation)
                    if time_std < 3600:  # Within 1 hour std dev
                        timespan = (timestamps[-1] - timestamps[0]).total_seconds() / 60  # minutes

                        coordinated.append(
                            {
                                "command": cmd,
                                "ips": unique_ips,
                                "timespan_minutes": round(timespan, 2),
                                "confidence": min(0.95, 1.0 - (time_std / 3600)),
                                "event_count": len(events),
                            }
                        )

            return sorted(coordinated, key=lambda x: x['confidence'], reverse=True)[:10]

        except sqlite3.Error:
            return self.mock_analyzer.detect_coordinated_attacks()

    def generate_threat_indicators(self, days: int = 30) -> Dict[str, Any]:
        """Generate high-confidence threat indicators."""
        try:
            # High risk IPs based on multiple criteria
            cursor = self.db.execute(
                """
                SELECT
                    s.src_ip,
                    COUNT(DISTINCT s.session) as sessions,
                    COUNT(c.command) as commands,
                    COUNT(f.shasum) as files,
                    MIN(s.start_time) as first_seen,
                    MAX(s.start_time) as last_seen
                FROM sessions s
                LEFT JOIN commands c ON s.session = c.session
                LEFT JOIN files f ON s.session = f.session
                WHERE s.start_time > datetime('now', '-{} days')
                GROUP BY s.src_ip
                HAVING sessions > 5 OR commands > 10 OR files > 2
                ORDER BY (sessions * 2 + commands + files * 5) DESC
                LIMIT 20
            """.format(days)
            )

            high_risk_ips = [dict(row) for row in cursor.fetchall()]

            # Calculate risk scores
            for ip_data in high_risk_ips:
                sessions = ip_data['sessions']
                commands = ip_data['commands'] or 0
                files = ip_data['files'] or 0

                # Risk score based on activity level
                risk_score = min(1.0, (sessions * 0.1 + commands * 0.05 + files * 0.3))

                ip_data['risk_score'] = risk_score
                ip_data['threat_types'] = self._classify_threat_types(sessions, commands, files)

            # Suspicious files based on VT data and distribution
            cursor = self.db.execute(
                """
                SELECT
                    f.shasum,
                    f.filename,
                    f.filesize,
                    COUNT(DISTINCT s.src_ip) as sources,
                    MAX(f.vt_malicious) as max_malicious,
                    MAX(f.vt_first_seen) as first_seen
                FROM files f
                JOIN sessions s ON f.session = s.session
                WHERE f.timestamp > datetime('now', '-{} days')
                GROUP BY f.shasum
                HAVING sources > 2 OR max_malicious > 0
                ORDER BY sources DESC, max_malicious DESC
                LIMIT 15
            """.format(days)
            )

            suspicious_files = [dict(row) for row in cursor.fetchall()]

            for file_data in suspicious_files:
                sources = file_data['sources']
                malicious = file_data['max_malicious'] or 0

                threat_level = "low"
                if malicious > 10 or sources > 5:
                    threat_level = "critical"
                elif malicious > 5 or sources > 3:
                    threat_level = "high"
                elif malicious > 0 or sources > 1:
                    threat_level = "medium"

                file_data['threat_level'] = threat_level
                file_data['detection_count'] = malicious

            return {
                "high_risk_ips": high_risk_ips,
                "suspicious_files": suspicious_files,
                "emerging_patterns": self._detect_emerging_patterns(days),
                "zero_day_candidates": self._find_zero_day_candidates(days),
            }

        except sqlite3.Error:
            return self.mock_analyzer.generate_threat_indicators()

    def _get_empty_analysis(self) -> Dict[str, Any]:
        """Return empty analysis when no data is available."""
        return {
            "total_unique_ips": 0,
            "avg_sessions_per_ip": 0.0,
            "avg_active_days": 0.0,
            "most_active_ips": [],
            "session_distribution": {},
            "temporal_patterns": {},
        }

    def _get_empty_command_analysis(self) -> Dict[str, Any]:
        """Return empty command analysis."""
        return {
            "total_commands": 0,
            "unique_commands": 0,
            "avg_command_length": 0.0,
            "most_common_commands": [],
            "suspicious_commands": [],
            "command_categories": {},
        }

    def _get_empty_file_analysis(self) -> Dict[str, Any]:
        """Return empty file analysis."""
        return {
            "total_unique_files": 0,
            "avg_sources_per_file": 0.0,
            "avg_file_size": 0.0,
            "most_distributed_files": [],
            "file_size_distribution": {},
            "filename_patterns": {},
        }

    def _get_empty_velocity_analysis(self) -> Dict[str, Any]:
        """Return empty velocity analysis."""
        return {
            "total_attackers": 0,
            "behavior_distribution": {},
            "avg_attack_duration": 0.0,
            "velocity_percentiles": {"p50": 0, "p75": 0, "p95": 0},
            "most_active_attackers": [],
        }

    def _analyze_session_distribution(self, sessions: List[Dict[str, Any]]) -> Dict[str, int]:
        """Analyze distribution of sessions per IP."""
        distribution: dict[str, int] = {}
        for session in sessions:
            session_count = session['total_sessions']
            bucket = self._get_session_bucket(session_count)
            distribution[bucket] = distribution.get(bucket, 0) + 1

        return distribution

    def _get_session_bucket(self, count: int) -> str:
        """Get bucket name for session count."""
        if count <= 2:
            return "1-2"
        elif count <= 5:
            return "3-5"
        elif count <= 10:
            return "6-10"
        elif count <= 20:
            return "11-20"
        else:
            return "20+"

    def _analyze_temporal_patterns(self, sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Analyze temporal patterns in sessions."""
        hourly_activity = [0] * 24
        daily_activity = [0] * 7

        for session in sessions:
            try:
                dt = datetime.fromisoformat(session['first_seen'].replace('Z', '+00:00'))
                hourly_activity[dt.hour] += 1
                daily_activity[dt.weekday()] += 1
            except (ValueError, AttributeError):
                continue

        peak_hours = [i for i, count in enumerate(hourly_activity) if count > 0]
        peak_days = [i for i, count in enumerate(daily_activity) if count > 0]

        return {
            "peak_hours": peak_hours,
            "peak_days": peak_days,
            "hourly_distribution": hourly_activity,
            "daily_distribution": daily_activity,
        }

    def _analyze_file_sizes(self, file_sizes: List[int]) -> Dict[str, int]:
        """Analyze file size distribution."""
        if not file_sizes:
            return {}

        distribution = {
            "tiny": 0,  # < 1KB
            "small": 0,  # 1KB - 100KB
            "medium": 0,  # 100KB - 1MB
            "large": 0,  # 1MB - 10MB
            "huge": 0,  # > 10MB
        }

        for size in file_sizes:
            if size < 1024:
                distribution["tiny"] += 1
            elif size < 102400:
                distribution["small"] += 1
            elif size < 1048576:
                distribution["medium"] += 1
            elif size < 10485760:
                distribution["large"] += 1
            else:
                distribution["huge"] += 1

        return distribution

    def _analyze_filename_patterns(self, filenames: List[str]) -> Dict[str, Any]:
        """Analyze patterns in filenames."""
        if not filenames:
            return {}

        # Common extensions
        extensions: dict[str, int] = {}
        for filename in filenames:
            ext = filename.split('.')[-1].lower() if '.' in filename else 'no_extension'
            extensions[ext] = extensions.get(ext, 0) + 1

        # Common prefixes/suffixes
        suspicious_patterns = {"malware_indicators": 0, "script_files": 0, "binary_files": 0, "archive_files": 0}

        for filename in filenames:
            filename_lower = filename.lower()
            if any(indicator in filename_lower for indicator in ['malware', 'virus', 'trojan', 'backdoor']):
                suspicious_patterns["malware_indicators"] += 1
            if filename_lower.endswith(('.sh', '.py', '.pl', '.rb')):
                suspicious_patterns["script_files"] += 1
            if filename_lower.endswith(('.exe', '.elf', '.bin')):
                suspicious_patterns["binary_files"] += 1
            if filename_lower.endswith(('.zip', '.tar', '.gz', '.bz2')):
                suspicious_patterns["archive_files"] += 1

        return {
            "common_extensions": dict(sorted(extensions.items(), key=lambda x: x[1], reverse=True)[:10]),
            "suspicious_patterns": suspicious_patterns,
        }

    def _categorize_commands(self, commands: List[Dict[str, Any]]) -> Dict[str, int]:
        """Categorize commands by type."""
        categories = {"system": 0, "network": 0, "file": 0, "process": 0, "other": 0}

        for cmd_data in commands:
            cmd = cmd_data['command'].lower()

            if any(
                keyword in cmd
                for keyword in ['ls', 'cd', 'pwd', 'mkdir', 'rm', 'cp', 'mv', 'cat', 'head', 'tail', 'grep']
            ):
                categories["file"] += cmd_data['frequency']
            elif any(keyword in cmd for keyword in ['ps', 'kill', 'top', 'htop', 'who', 'w', 'whoami', 'id']):
                categories["process"] += cmd_data['frequency']
            elif any(keyword in cmd for keyword in ['ping', 'nc', 'netcat', 'wget', 'curl', 'ssh', 'telnet', 'ftp']):
                categories["network"] += cmd_data['frequency']
            elif any(keyword in cmd for keyword in ['chmod', 'chown', 'su', 'sudo', 'passwd', 'usermod']):
                categories["system"] += cmd_data['frequency']
            else:
                categories["other"] += cmd_data['frequency']

        return categories

    def _calculate_percentiles(self, values: List[float]) -> Dict[str, float]:
        """Calculate percentiles for a list of values."""
        if not values:
            return {"p50": 0, "p75": 0, "p95": 0}

        sorted_values = sorted(values)
        n = len(sorted_values)

        return {
            "p50": sorted_values[int(n * 0.5)],
            "p75": sorted_values[int(n * 0.75)],
            "p95": sorted_values[int(n * 0.95)],
        }

    def _classify_threat_types(self, sessions: int, commands: int, files: int) -> List[str]:
        """Classify threat types based on activity patterns."""
        threat_types = []

        if files > 5:
            threat_types.append("malware_distribution")
        if commands > 20:
            threat_types.append("command_injection")
        if sessions > 10:
            threat_types.append("persistent_attacker")
        if sessions > 3 and commands > 50:
            threat_types.append("brute_force")
        if files > 0 and commands > 10:
            threat_types.append("c2_server")

        return threat_types if threat_types else ["generic_attacker"]

    def _detect_emerging_patterns(self, days: int) -> List[Dict[str, Any]]:
        """Detect emerging attack patterns."""
        # This would analyze recent data for new patterns
        # For now, return mock data
        return [
            {
                "pattern_type": "command_sequence",
                "description": f"New command pattern detected: sequence_{i}",
                "confidence": random.uniform(0.6, 0.9),
                "first_observed": datetime.now().isoformat(),
                "frequency": random.randint(5, 20),
            }
            for i in range(random.randint(2, 5))
        ]

    def _find_zero_day_candidates(self, days: int) -> List[Dict[str, Any]]:
        """Find potential zero-day attack indicators."""
        # This would look for unusual patterns that don't match known attacks
        # For now, return mock data
        return [
            {
                "indicator": f"zero_day_candidate_{i}",
                "novelty_score": random.uniform(0.7, 1.0),
                "detection_gap": random.randint(1, 30),
                "affected_systems": random.randint(5, 50),
                "first_seen": datetime.now().isoformat(),
            }
            for i in range(random.randint(1, 3))
        ]
