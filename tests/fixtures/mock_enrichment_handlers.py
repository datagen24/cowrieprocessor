"""Mock enrichment handlers for OTX and AbuseIPDB services."""

from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Any, Dict, List

from tests.fixtures.enrichment_fixtures import (
    get_abuseipdb_response,
    get_otx_response,
)


class MockOTXHandler:
    """Mock AlienVault OTX handler for testing without API keys."""

    def __init__(self, api_key: str, cache_dir: Path) -> None:
        """Initialize mock OTX handler.

        Args:
            api_key: API key (unused in mock)
            cache_dir: Directory for caching responses
        """
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_ttl = 86400  # 24 hours
        self.request_count = 0
        self.rate_limit_threshold = 4  # requests per minute

    def check_ip(self, ip: str) -> Dict[str, Any]:
        """Mock OTX IP reputation check."""
        cache_file = self.cache_dir / f"otx_ip_{ip}.json"

        # Check cache
        if cache_file.exists():
            if time.time() - cache_file.stat().st_mtime < self.cache_ttl:
                try:
                    return json.loads(cache_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass  # Fall through to API call

        # Simulate rate limiting
        self.request_count += 1
        if self.request_count > self.rate_limit_threshold:
            return {"error": "rate_limit"}

        # Generate mock response based on IP pattern
        if ip.startswith(("192.168.", "10.", "127.")):
            # Internal IP - no results
            result = json.loads(get_otx_response("clean_ip"))
        elif ip in ["8.8.8.8", "1.1.1.1", "9.9.9.9"]:
            # Known good IPs - clean
            result = json.loads(get_otx_response("clean_ip"))
        else:
            # Random malicious or clean
            if random.random() < 0.7:  # 70% chance of malicious
                result = json.loads(get_otx_response("malicious_ip"))
                # Add some variety
                result["reputation"] = random.randint(5, 10)
                result["pulse_info"]["pulses"] = [
                    {
                        "name": f"Malicious Activity {random.randint(1, 100)}",
                        "id": f"pulse_{random.randint(1000, 9999)}",
                        "created": "2024-01-01T00:00:00.000000",
                        "modified": "2024-01-15T00:00:00.000000",
                        "description": "Mock malicious activity detection",
                    }
                ]
            else:
                result = json.loads(get_otx_response("clean_ip"))

        # Cache result
        cache_file.write_text(json.dumps(result, indent=2))

        return result

    def check_file_hash(self, hash_value: str) -> Dict[str, Any]:
        """Mock OTX file hash reputation check."""
        cache_file = self.cache_dir / f"otx_hash_{hash_value}.json"

        # Check cache
        if cache_file.exists():
            if time.time() - cache_file.stat().st_mtime < self.cache_ttl:
                try:
                    return json.loads(cache_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass

        # Generate mock response
        if hash_value.startswith(("0000", "dead", "bad")):
            # Known bad hashes
            result = {
                "pulses": random.randint(1, 10),
                "malware": True,
                "first_seen": "2024-01-01T00:00:00Z",
                "threat_names": ["trojan.generic", "malware.win32"],
            }
        elif hash_value.startswith(("aaaa", "clean", "good")):
            # Known good hashes
            result = {"pulses": 0, "malware": False, "first_seen": None, "threat_names": []}
        else:
            # Random result
            result = {
                "pulses": random.randint(0, 5),
                "malware": random.random() > 0.8,
                "first_seen": "2024-01-01T00:00:00Z" if random.random() > 0.5 else None,
                "threat_names": [] if random.random() > 0.7 else ["generic.malware"],
            }

        # Cache result
        cache_file.write_text(json.dumps(result, indent=2))

        return result


class MockAbuseIPDBHandler:
    """Mock AbuseIPDB handler for testing without API keys."""

    def __init__(self, api_key: str, cache_dir: Path) -> None:
        """Initialize mock AbuseIPDB handler.

        Args:
            api_key: API key (unused in mock)
            cache_dir: Directory for caching responses
        """
        self.api_key = api_key
        self.cache_dir = cache_dir
        self.cache_ttl = 3600  # 1 hour
        self.request_count = 0
        self.rate_limit_threshold = 4  # requests per minute
        self.quota_exceeded = False

    def check_ip(self, ip: str, max_age_days: int = 90) -> Dict[str, Any]:
        """Mock AbuseIPDB IP reputation check."""
        cache_file = self.cache_dir / f"abuse_{ip}_{max_age_days}.json"

        # Check cache
        if cache_file.exists():
            if time.time() - cache_file.stat().st_mtime < self.cache_ttl:
                try:
                    return json.loads(cache_file.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass

        # Check quota
        if self.quota_exceeded:
            return {"error": "quota_exceeded"}

        # Simulate rate limiting
        self.request_count += 1
        if self.request_count > self.rate_limit_threshold:
            return {"error": "rate_limit"}

        # Generate mock response based on IP pattern
        if ip.startswith("127.") or ip.startswith("10.") or ip.startswith("192.168."):
            # Private IPs - no abuse data (but vary slightly by max_age for testing)
            result = json.loads(get_abuseipdb_response("low_risk"))
            result["data"]["abuseConfidenceScore"] = 0
            result["data"]["totalReports"] = 0
            result["data"]["numDistinctUsers"] = max_age_days  # Vary by max_age for cache testing
        elif ip in ["8.8.8.8", "1.1.1.1", "208.67.222.222"]:
            # Known good IPs
            result = json.loads(get_abuseipdb_response("low_risk"))
        elif ip.startswith("203.0.113.") or ip.startswith("198.51.100."):
            # Test IPs - high risk (vary by max_age_days)
            result = json.loads(get_abuseipdb_response("high_risk"))
            result["data"]["abuseConfidenceScore"] = random.randint(80, 100)
            result["data"]["totalReports"] = random.randint(10, 50) + (max_age_days // 10)
        else:
            # Random result
            if random.random() > 0.6:  # 60% chance of being flagged
                result = json.loads(get_abuseipdb_response("high_risk"))
                result["data"]["abuseConfidenceScore"] = random.randint(60, 100)
                result["data"]["totalReports"] = random.randint(5, 30)
                result["data"]["reports"] = [
                    {
                        "reportedAt": "2025-01-01T12:00:00+00:00",
                        "comment": random.choice(
                            [
                                "SSH brute force attempt",
                                "Port scanning activity",
                                "Suspicious login attempts",
                                "Malware command and control",
                            ]
                        ),
                        "categories": random.sample([18, 22, 3, 4, 14], k=random.randint(1, 3)),
                        "reporterId": random.randint(1000, 9999),
                        "reporterCountryCode": random.choice(["US", "CA", "GB", "DE", "FR"]),
                        "reporterCountryName": random.choice(
                            ["United States", "Canada", "United Kingdom", "Germany", "France"]
                        ),
                    }
                    for _ in range(random.randint(1, 5))
                ]
            else:
                result = json.loads(get_abuseipdb_response("low_risk"))

        # Cache result
        cache_file.write_text(json.dumps(result, indent=2))

        return result

    def set_quota_exceeded(self, exceeded: bool = True) -> None:
        """Set quota exceeded state for testing."""
        self.quota_exceeded = exceeded

    def reset_rate_limit(self) -> None:
        """Reset rate limit counter for testing."""
        self.request_count = 0


class MockStatisticalAnalyzer:
    """Mock statistical analysis tools ported from dshield-tooling."""

    def __init__(self, db_connection) -> None:
        """Initialize mock statistical analyzer.

        Args:
            db_connection: Database connection (unused in mock)
        """
        self.db = db_connection

    def analyze_upload_patterns(self, days: int = 30) -> Dict[str, Any]:
        """Mock analysis of upload patterns."""
        return {
            "total_unique_files": random.randint(50, 200),
            "avg_sources_per_file": random.uniform(1.5, 5.0),
            "most_distributed": [
                {
                    "shasum": f"hash_{i}",
                    "filename": f"malware_{i}.exe",
                    "unique_sources": random.randint(3, 15),
                    "first_seen": "2025-01-01T00:00:00",
                    "last_seen": "2025-01-15T00:00:00",
                }
                for i in range(10)
            ],
            "temporal_clustering": {
                "clusters": random.randint(2, 8),
                "avg_cluster_size": random.uniform(5, 20),
                "peak_hours": [random.randint(0, 23) for _ in range(3)],
            },
            "file_type_distribution": {
                "exe": random.randint(30, 60),
                "elf": random.randint(10, 30),
                "script": random.randint(5, 15),
                "other": random.randint(5, 20),
            },
        }

    def analyze_attack_velocity(self) -> Dict[str, Any]:
        """Mock analysis of attack patterns and velocity."""
        return {
            "behavior_distribution": {
                "human_like": random.randint(20, 40),
                "semi_automated": random.randint(30, 50),
                "automated": random.randint(15, 35),
                "aggressive_bot": random.randint(5, 15),
            },
            "avg_attack_duration": random.uniform(300, 3600),  # 5 minutes to 1 hour
            "persistence_score": random.uniform(0.1, 0.9),
            "velocity_percentiles": {
                "p50": random.uniform(1, 10),
                "p75": random.uniform(10, 50),
                "p95": random.uniform(50, 200),
            },
        }

    def detect_coordinated_attacks(self) -> List[Dict[str, Any]]:
        """Mock detection of coordinated attack campaigns."""
        coordinated_attacks = []

        # Generate 0-3 mock coordinated attacks
        for i in range(random.randint(0, 3)):
            coordinated_attacks.append(
                {
                    "command": random.choice(["cat /etc/passwd", "ls -la", "whoami", "uname -a", "ps aux"]),
                    "ips": [f"192.168.1.{j}" for j in random.sample(range(100, 200), random.randint(3, 8))],
                    "timespan_minutes": random.uniform(5, 60),
                    "confidence": random.uniform(0.6, 0.95),
                }
            )

        return sorted(
            coordinated_attacks,
            key=lambda x: x['confidence'],  # type: ignore
            reverse=True,
        )[:5]

    def generate_threat_indicators(self) -> Dict[str, Any]:
        """Mock generation of high-confidence threat indicators."""
        return {
            "high_risk_ips": [
                {
                    "ip": f"203.0.113.{i}",
                    "risk_score": random.uniform(0.8, 1.0),
                    "threat_types": random.sample(
                        ["brute_force", "malware_distribution", "c2_server", "scanner"], k=random.randint(1, 3)
                    ),
                    "first_seen": "2025-01-01T00:00:00",
                    "last_seen": "2025-01-15T00:00:00",
                }
                for i in range(random.randint(5, 15))
            ],
            "suspicious_files": [
                {
                    "shasum": f"hash_{i}",
                    "filename": f"suspicious_{i}.exe",
                    "detection_count": random.randint(1, 20),
                    "threat_level": random.choice(["low", "medium", "high", "critical"]),
                }
                for i in range(random.randint(3, 10))
            ],
            "emerging_patterns": [
                {
                    "pattern_type": random.choice(["command_sequence", "timing_pattern", "target_selection"]),
                    "description": f"Mock pattern {i}",
                    "confidence": random.uniform(0.5, 0.9),
                    "first_observed": "2025-01-01T00:00:00",
                }
                for i in range(random.randint(2, 6))
            ],
            "zero_day_candidates": [
                {
                    "indicator": f"zero_day_{i}",
                    "novelty_score": random.uniform(0.7, 1.0),
                    "detection_gap": random.randint(1, 30),  # days
                    "affected_systems": random.randint(5, 50),
                }
                for i in range(random.randint(1, 5))
            ],
        }


def create_mock_enrichment_handlers(cache_dir: Path) -> Dict[str, Any]:
    """Create all mock enrichment handlers for testing."""
    return {
        "otx": MockOTXHandler("mock_otx_key", cache_dir),
        "abuseipdb": MockAbuseIPDBHandler("mock_abuse_key", cache_dir),
        "statistical_analyzer": None,  # Will be created with DB connection
    }


def setup_mock_enrichment_environment(cache_dir: Path, db_connection=None) -> Dict[str, Any]:
    """Setup complete mock enrichment environment for testing."""
    handlers = create_mock_enrichment_handlers(cache_dir)

    if db_connection:
        handlers["statistical_analyzer"] = MockStatisticalAnalyzer(db_connection)

    return handlers
