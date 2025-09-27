"""Test fixtures and mock data for enrichment services."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def load_json_fixture(fixture_name: str) -> Dict[str, Any]:
    """Load JSON fixture from the fixtures directory."""
    fixture_path = Path(__file__).parent / f"{fixture_name}.json"
    try:
        return json.loads(fixture_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        # Return minimal valid response if fixture doesn't exist
        return {}


# VirusTotal API responses
VIRUSTOTAL_RESPONSES = {
    "malware": {
        "data": {
            "attributes": {
                "type_description": "Win32 EXE",
                "popular_threat_classification": {"suggested_threat_label": "trojan.generic/malware"},
                "first_submission_date": 1677600000,
                "last_analysis_stats": {
                    "malicious": 45,
                    "suspicious": 5,
                    "undetected": 10,
                    "harmless": 0,
                    "timeout": 0,
                },
                "signature_info": {
                    "copyright": "Microsoft Corporation",
                    "description": "Windows Command Processor",
                    "file_version": "10.0.19041.1",
                },
            }
        }
    },
    "clean": {
        "data": {
            "attributes": {
                "type_description": "Win32 EXE",
                "popular_threat_classification": {"suggested_threat_label": "win32.exe"},
                "first_submission_date": 1677600000,
                "last_analysis_stats": {"malicious": 0, "suspicious": 0, "undetected": 60, "harmless": 0, "timeout": 0},
                "signature_info": {
                    "copyright": "Microsoft Corporation",
                    "description": "Windows Command Processor",
                    "file_version": "10.0.19041.1",
                },
            }
        }
    },
    "unknown": {"error": "not_found"},
    "rate_limit": {"error": {"code": "QuotaExceededError", "message": "You have exceeded your API request quota"}},
}

# DShield API responses
DSHIELD_RESPONSES = {
    "datacenter": {
        "ip": {
            "asname": "AMAZON-02",
            "ascountry": "US",
            "asnumber": 16509,
            "asdescription": "Amazon.com, Inc.",
            "ipcountrycode": "US",
            "ipcountryname": "United States",
            "ipregion": "Virginia",
            "ipcity": "Ashburn",
            "count": "999",
            "attacks": "1000",
            "firstseen": "2023-01-01",
            "lastseen": "2025-01-01",
            "updated": "2025-01-01T00:00:00Z",
        }
    },
    "residential": {
        "ip": {
            "asname": "COMCAST-7922",
            "ascountry": "US",
            "asnumber": 7922,
            "asdescription": "Comcast Cable Communications, LLC",
            "ipcountrycode": "US",
            "ipcountryname": "United States",
            "ipregion": "California",
            "ipcity": "San Francisco",
            "count": "5",
            "attacks": "5",
            "firstseen": "2024-01-01",
            "lastseen": "2025-01-01",
            "updated": "2025-01-01T00:00:00Z",
        }
    },
    "vpn": {
        "ip": {
            "asname": "MULLVAD-VPN",
            "ascountry": "SE",
            "asnumber": 60068,
            "asdescription": "Mullvad VPN AB",
            "ipcountrycode": "SE",
            "ipcountryname": "Sweden",
            "ipregion": "Stockholm",
            "ipcity": "Stockholm",
            "count": "50",
            "attacks": "60",
            "firstseen": "2023-06-01",
            "lastseen": "2025-01-01",
            "updated": "2025-01-01T00:00:00Z",
        }
    },
}

# URLHaus API responses
URLHAUS_RESPONSES = {
    "malicious_urls": {
        "query_status": "ok",
        "urls": [
            {
                "url": "http://malicious-site.com/malware.exe",
                "url_status": "online",
                "urlhaus_reference": "https://urlhaus.abuse.ch/url/12345/",
                "reporter": "testuser",
                "date_added": "2024-01-01 12:00:00 UTC",
                "threat": "malware_download",
                "tags": ["elf", "mirai", "trojan"],
                "urlhaus_link": "https://urlhaus.abuse.ch/browse/tag/elf/",
            },
            {
                "url": "http://another-bad-site.com/bot.exe",
                "url_status": "online",
                "urlhaus_reference": "https://urlhaus.abuse.ch/url/67890/",
                "reporter": "testuser",
                "date_added": "2024-01-02 12:00:00 UTC",
                "threat": "malware_download",
                "tags": ["exe", "emotet", "banker"],
                "urlhaus_link": "https://urlhaus.abuse.ch/browse/tag/exe/",
            },
        ],
    },
    "no_results": {"query_status": "no_results"},
    "invalid_request": {"query_status": "invalid_request"},
}

# SPUR API responses (mocked since no license)
SPUR_RESPONSES = {
    "datacenter": {
        "asn": {"number": 16509, "organization": "Amazon.com, Inc."},
        "organization": "Amazon Web Services",
        "infrastructure": "DATACENTER",
        "client": {
            "behaviors": ["SCANNER"],
            "proxies": "",
            "types": ["SERVER"],
            "count": 1,
            "concentration": "HIGH",
            "countries": ["US"],
            "spread": "LOW",
        },
        "risks": [""],
        "services": ["SSH", "HTTP"],
        "location": {"city": "Ashburn", "state": "Virginia", "country": "US"},
        "tunnels": [{"anonymous": "", "entries": "", "operator": "", "type": ""}],
    },
    "residential": {
        "asn": {"number": 7922, "organization": "Comcast Cable"},
        "organization": "Comcast",
        "infrastructure": "RESIDENTIAL",
        "client": {
            "behaviors": ["BROWSER"],
            "proxies": "",
            "types": ["DESKTOP"],
            "count": 1,
            "concentration": "LOW",
            "countries": ["US"],
            "spread": "LOW",
        },
        "risks": [""],
        "services": ["SSH"],
        "location": {"city": "San Francisco", "state": "California", "country": "US"},
        "tunnels": [],
    },
    "vpn": {
        "asn": {"number": 60068, "organization": "Mullvad VPN AB"},
        "organization": "Mullvad VPN",
        "infrastructure": "VPN",
        "client": {
            "behaviors": ["VPN"],
            "proxies": "VPN",
            "types": ["MOBILE"],
            "count": 5,
            "concentration": "MEDIUM",
            "countries": ["SE", "US", "DE"],
            "spread": "GLOBAL",
        },
        "risks": [""],
        "services": ["SSH", "HTTP"],
        "location": {"city": "Stockholm", "state": "", "country": "SE"},
        "tunnels": [{"anonymous": "YES", "entries": "10", "operator": "Mullvad", "type": "OPENVPN"}],
    },
}

# Mock OTX API responses
OTX_RESPONSES = {
    "malicious_ip": {
        "reputation": 8,
        "pulse_info": {
            "pulses": [
                {
                    "name": "Malicious IP Activity",
                    "id": "pulse_12345",
                    "created": "2024-01-01T00:00:00.000000",
                    "modified": "2024-01-15T00:00:00.000000",
                    "description": "IP address involved in malicious activities",
                }
            ]
        },
        "country_name": "United States",
        "asn": "AS15169",
        "validation": [{"source": "spamhaus", "message": "IP listed on Spamhaus DROP"}],
        "malware_families": ["mirai", "gafgyt"],
    },
    "clean_ip": {
        "reputation": 0,
        "pulse_info": {"pulses": []},
        "country_name": "United States",
        "asn": "AS15169",
        "validation": [],
        "malware_families": [],
    },
}

# Mock AbuseIPDB API responses
ABUSEIPDB_RESPONSES = {
    "high_risk": {
        "data": {
            "ipAddress": "192.168.1.100",
            "isPublic": True,
            "ipVersion": 4,
            "isWhitelisted": False,
            "abuseConfidenceScore": 95,
            "countryCode": "US",
            "countryName": "United States",
            "usageType": "Data Center/Web Hosting/Transit",
            "isp": "Example Hosting Inc",
            "domain": "example.com",
            "totalReports": 25,
            "numDistinctUsers": 15,
            "lastReportedAt": "2025-01-01T12:00:00+00:00",
            "reports": [
                {
                    "reportedAt": "2025-01-01T12:00:00+00:00",
                    "comment": "SSH brute force attempt",
                    "categories": [18, 22],  # SSH, Brute Force
                    "reporterId": 12345,
                    "reporterCountryCode": "US",
                    "reporterCountryName": "United States",
                }
            ],
        }
    },
    "low_risk": {
        "data": {
            "ipAddress": "8.8.8.8",
            "isPublic": True,
            "ipVersion": 4,
            "isWhitelisted": True,
            "abuseConfidenceScore": 0,
            "countryCode": "US",
            "countryName": "United States",
            "usageType": "Fixed Line ISP",
            "isp": "Google LLC",
            "domain": "google.com",
            "totalReports": 0,
            "numDistinctUsers": 0,
            "lastReportedAt": None,
            "reports": [],
        }
    },
    "rate_limited": {"error": "rate_limit"},
    "quota_exceeded": {"error": "quota_exceeded"},
}

# Error responses for testing
ERROR_RESPONSES = {
    "timeout": {"error": "timeout"},
    "network_error": {"error": "network_error"},
    "malformed_json": {"invalid": "json structure"},
}

# Combined fixture data for easy access
ENRICHMENT_FIXTURES = {
    "virustotal": VIRUSTOTAL_RESPONSES,
    "dshield": DSHIELD_RESPONSES,
    "urlhaus": URLHAUS_RESPONSES,
    "spur": SPUR_RESPONSES,
    "otx": OTX_RESPONSES,
    "abuseipdb": ABUSEIPDB_RESPONSES,
    "errors": ERROR_RESPONSES,
}


def get_vt_response(response_type: str = "malware") -> str:
    """Get VirusTotal API response as JSON string."""
    return json.dumps(VIRUSTOTAL_RESPONSES[response_type])


def get_dshield_response(response_type: str = "datacenter") -> str:
    """Get DShield API response as JSON string."""
    return json.dumps(DSHIELD_RESPONSES[response_type])


def get_urlhaus_response(response_type: str = "malicious_urls") -> str:
    """Get URLHaus API response as JSON string."""
    return json.dumps(URLHAUS_RESPONSES[response_type])


def get_spur_response(response_type: str = "datacenter") -> str:
    """Get SPUR API response as JSON string."""
    return json.dumps(SPUR_RESPONSES[response_type])


def get_otx_response(response_type: str = "malicious_ip") -> str:
    """Get OTX API response as JSON string."""
    return json.dumps(OTX_RESPONSES[response_type])


def get_abuseipdb_response(response_type: str = "high_risk") -> str:
    """Get AbuseIPDB API response as JSON string."""
    return json.dumps(ABUSEIPDB_RESPONSES[response_type])


def get_error_response(error_type: str = "timeout") -> str:
    """Get error response as JSON string."""
    return json.dumps(ERROR_RESPONSES[error_type])


def create_mock_session(response_text: str, status_code: int = 200) -> Any:
    """Create a mock requests session with predefined response."""
    from types import SimpleNamespace

    mock_response = SimpleNamespace()
    mock_response.status_code = status_code
    mock_response.text = response_text
    mock_response.raise_for_status = lambda: None
    mock_response.json = lambda: json.loads(response_text) if response_text else {}

    class MockSession:
        def __init__(self):
            self.headers = {}
            self.calls = []
            self.closed = False

        def get(self, url: str, timeout: float = 30):
            self.calls.append(("GET", url, timeout))
            return mock_response

        def post(self, url: str, headers: dict, data: dict, timeout: float = 30):
            self.calls.append(("POST", url, headers, data, timeout))
            return mock_response

        def close(self):
            self.closed = True

    return MockSession()
