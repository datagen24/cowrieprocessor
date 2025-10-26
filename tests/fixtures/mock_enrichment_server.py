"""Mock enrichment server for testing without external API dependencies."""

from __future__ import annotations

import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlparse

from tests.fixtures.enrichment_fixtures import (
    get_abuseipdb_response,
    get_dshield_response,
    get_otx_response,
    get_spur_response,
    get_urlhaus_response,
    get_vt_response,
)


class MockEnrichmentHandler(BaseHTTPRequestHandler):
    """HTTP handler for mock enrichment APIs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Initialize mock HTTP handler."""
        self.request_count = 0
        self.rate_limit_threshold = 100  # requests per minute
        self.rate_limit_window = 60  # seconds
        self.requests_in_window = 0
        self.window_start = time.time()
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:
        """Handle GET requests."""
        self.request_count += 1
        self._check_rate_limit()

        parsed_path = urlparse(self.path)
        path = parsed_path.path
        query_params = parse_qs(parsed_path.query)

        if path.startswith('/api/v3/files/'):
            self._handle_vt_file_request(path)
        elif '/api/ip/' in path and 'isc.sans.edu' in self.headers.get('Host', ''):
            self._handle_dshield_request(path, query_params)
        elif '/api/v1/context/' in path:
            self._handle_spur_request(path)
        elif '/api/v1/indicators/IPv4/' in path and '/general' in path:
            self._handle_otx_ip_request(path)
        elif '/api/v1/indicators/IPv4/' in path:
            self._handle_otx_ip_details_request(path)
        else:
            self._send_error(404, "Not Found")

    def do_POST(self) -> None:
        """Handle POST requests."""
        self.request_count += 1
        self._check_rate_limit()

        parsed_path = urlparse(self.path)
        path = parsed_path.path

        if path == '/api/v1/host/':
            self._handle_urlhaus_request()
        elif path == '/api/v2/check':
            self._handle_abuseipdb_request()
        else:
            self._send_error(404, "Not Found")

    def _check_rate_limit(self) -> None:
        """Check and enforce rate limiting."""
        current_time = time.time()

        # Reset window if needed
        if current_time - self.window_start > self.rate_limit_window:
            self.requests_in_window = 0
            self.window_start = current_time

        self.requests_in_window += 1

        if self.requests_in_window > self.rate_limit_threshold:
            self._send_error(429, "Rate limit exceeded", {"Retry-After": "60"})

    def _handle_vt_file_request(self, path: str) -> None:
        """Handle VirusTotal file lookup requests."""
        # Extract hash from path
        hash_value = path.split('/')[-1]

        # Simulate different responses based on hash
        if hash_value.startswith('0000') or hash_value.startswith('dead'):
            # Known malicious
            response_data = json.loads(get_vt_response("malware"))
        elif hash_value.startswith('aaaa') or hash_value.startswith('clean'):
            # Known clean
            response_data = json.loads(get_vt_response("clean"))
        elif hash_value.startswith('unknown'):
            # Not found
            self._send_error(404, "File not found")
            return
        else:
            # Random result
            if random.random() > 0.7:
                response_data = json.loads(get_vt_response("malware"))
            else:
                response_data = json.loads(get_vt_response("clean"))

        self._send_json_response(response_data)

    def _handle_dshield_request(self, path: str, query_params: dict[str, list[str]]) -> None:
        """Handle DShield IP lookup requests."""
        # Extract IP from path
        ip = path.split('/')[-1].split('?')[0]

        # Check for email parameter
        email = query_params.get('email', [''])[0]
        if not email:
            self._send_error(400, "Email parameter required")
            return

        # Simulate different responses based on IP
        if ip.startswith('192.168.'):
            response_data = json.loads(get_dshield_response("datacenter"))
        elif ip.startswith('10.'):
            response_data = json.loads(get_dshield_response("residential"))
        elif ip in ['8.8.8.8', '1.1.1.1']:
            response_data = json.loads(get_dshield_response("datacenter"))
        else:
            # Random result
            response_types = ["datacenter", "residential", "vpn"]
            response_data = json.loads(get_dshield_response(random.choice(response_types)))

        self._send_json_response(response_data)

    def _handle_spur_request(self, path: str) -> None:
        """Handle SPUR IP context requests."""
        # Extract IP from path
        ip = path.split('/')[-1]

        # Simulate different responses based on IP
        if ip.startswith('192.168.'):
            response_data = json.loads(get_spur_response("datacenter"))
        elif ip.startswith('10.'):
            response_data = json.loads(get_spur_response("residential"))
        elif ip in ['8.8.8.8', '1.1.1.1']:
            response_data = json.loads(get_spur_response("datacenter"))
        else:
            # Random result
            response_types = ["datacenter", "residential", "vpn"]
            response_data = json.loads(get_spur_response(random.choice(response_types)))

        self._send_json_response(response_data)

    def _handle_urlhaus_request(self) -> None:
        """Handle URLHaus host lookup requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = parse_qs(post_data)

        host = params.get('host', [''])[0]

        if not host:
            self._send_error(400, "Host parameter required")
            return

        # Simulate malicious URLs for test IPs
        if host.startswith('203.0.113.') or host.startswith('198.51.100.'):
            response_data = json.loads(get_urlhaus_response("malicious_urls"))
        else:
            response_data = json.loads(get_urlhaus_response("no_results"))

        self._send_json_response(response_data)

    def _handle_otx_ip_request(self, path: str) -> None:
        """Handle OTX IP general lookup requests."""
        # Extract IP from path
        ip = path.split('/')[-2]  # /api/v1/indicators/IPv4/{ip}/general

        # Simulate different responses based on IP
        if ip.startswith('192.168.'):
            response_data = json.loads(get_otx_response("clean_ip"))
        elif ip in ['8.8.8.8', '1.1.1.1']:
            response_data = json.loads(get_otx_response("clean_ip"))
        else:
            # Random result
            if random.random() > 0.6:
                response_data = json.loads(get_otx_response("malicious_ip"))
            else:
                response_data = json.loads(get_otx_response("clean_ip"))

        self._send_json_response(response_data)

    def _handle_otx_ip_details_request(self, path: str) -> None:
        """Handle OTX IP details requests."""
        # Extract IP from path
        ip = path.split('/')[-1]

        # Return detailed IP information
        if ip.startswith('192.168.'):
            response_data = json.loads(get_otx_response("clean_ip"))
        else:
            response_data = json.loads(get_otx_response("malicious_ip"))

        self._send_json_response(response_data)

    def _handle_abuseipdb_request(self) -> None:
        """Handle AbuseIPDB IP check requests."""
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = parse_qs(post_data)

        ip = params.get('ipAddress', [''])[0]

        if not ip:
            self._send_error(400, "IP address required")
            return

        # Simulate different responses based on IP
        if ip.startswith('127.') or ip.startswith('10.') or ip.startswith('192.168.'):
            response_data = json.loads(get_abuseipdb_response("low_risk"))
        elif ip in ['8.8.8.8', '1.1.1.1']:
            response_data = json.loads(get_abuseipdb_response("low_risk"))
        elif ip.startswith('203.0.113.') or ip.startswith('198.51.100.'):
            response_data = json.loads(get_abuseipdb_response("high_risk"))
        else:
            # Random result
            if random.random() > 0.6:
                response_data = json.loads(get_abuseipdb_response("high_risk"))
            else:
                response_data = json.loads(get_abuseipdb_response("low_risk"))

        self._send_json_response(response_data)

    def _send_json_response(self, data: dict[str, Any]) -> None:
        """Send JSON response."""
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        self.wfile.write(json.dumps(data, indent=2).encode('utf-8'))

    def _send_error(self, code: int, message: str, headers: Optional[dict[str, str]] = None) -> None:
        """Send error response."""
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        if headers:
            for key, value in headers.items():
                self.send_header(key, str(value))
        self.end_headers()

        error_data = {"error": {"code": str(code), "message": message}}
        self.wfile.write(json.dumps(error_data, indent=2).encode('utf-8'))

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default logging."""
        pass  # Don't log requests to avoid test noise


class MockEnrichmentServer:
    """Mock server for enrichment API testing."""

    def __init__(self, port: int = 8888, host: str = 'localhost') -> None:
        """Initialize mock server.

        Args:
            port: Port to listen on
            host: Host to bind to
        """
        self.port = port
        self.host = host
        self.server: Optional[HTTPServer] = None
        self.thread: Optional[threading.Thread] = None
        self.handler_class = MockEnrichmentHandler

    def start(self) -> None:
        """Start the mock server."""
        self.server = HTTPServer((self.host, self.port), self.handler_class)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.daemon = True
        self.thread.start()

        # Wait a bit for server to start
        time.sleep(0.1)

    def stop(self) -> None:
        """Stop the mock server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=1.0)

    def reset_rate_limit(self) -> None:
        """Reset rate limiting counters."""
        # Note: Handler instances are created per request, so rate limiting
        # state is maintained in class variables (not implemented here)
        pass

    def get_request_count(self) -> int:
        """Get total request count."""
        # Note: Handler instances are created per request, so request counting
        # would need to be implemented with class variables (not implemented here)
        return 0

    def set_rate_limit(self, threshold: int) -> None:
        """Set rate limit threshold."""
        # Note: Handler instances are created per request, so rate limiting
        # would need to be implemented with class variables (not implemented here)
        pass


def create_mock_server_config() -> Dict[str, Any]:
    """Create configuration for mock server endpoints."""
    return {
        "virustotal": {
            "base_url": "https://www.virustotal.com",
            "endpoints": {"/api/v3/files/{hash}": {"method": "GET", "description": "File hash lookup"}},
        },
        "dshield": {
            "base_url": "https://isc.sans.edu",
            "endpoints": {
                "/api/ip/{ip}": {"method": "GET", "description": "IP reputation lookup", "params": ["email"]}
            },
        },
        "urlhaus": {
            "base_url": "https://urlhaus-api.abuse.ch",
            "endpoints": {"/v1/host/": {"method": "POST", "description": "Host/URL lookup", "params": ["host"]}},
        },
        "spur": {
            "base_url": "https://spur.us",
            "endpoints": {"/api/v1/context/{ip}": {"method": "GET", "description": "IP context lookup"}},
        },
        "otx": {
            "base_url": "https://otx.alienvault.com",
            "endpoints": {
                "/api/v1/indicators/IPv4/{ip}/general": {"method": "GET", "description": "IP general information"},
                "/api/v1/indicators/IPv4/{ip}": {"method": "GET", "description": "IP detailed information"},
            },
        },
        "abuseipdb": {
            "base_url": "https://api.abuseipdb.com",
            "endpoints": {
                "/api/v2/check": {
                    "method": "POST",
                    "description": "IP abuse check",
                    "params": ["ipAddress", "maxAgeInDays"],
                }
            },
        },
    }


class MockEnrichmentServerManager:
    """Manager for mock enrichment servers with multiple configurations."""

    def __init__(self) -> None:
        """Initialize mock server manager."""
        self.servers: dict[str, MockEnrichmentServer] = {}
        self.configs = create_mock_server_config()

    def start_server(self, service_name: str, port: Optional[int] = None) -> int:
        """Start a mock server for a specific service."""
        if service_name not in self.configs:
            raise ValueError(f"Unknown service: {service_name}")

        if port is None:
            port = 8888 + len(self.servers)

        server = MockEnrichmentServer(port=port)
        server.start()

        self.servers[service_name] = server
        return port

    def stop_server(self, service_name: str) -> None:
        """Stop a mock server for a specific service."""
        if service_name in self.servers:
            self.servers[service_name].stop()
            del self.servers[service_name]

    def stop_all_servers(self) -> None:
        """Stop all mock servers."""
        for server in self.servers.values():
            server.stop()
        self.servers.clear()

    def get_server_url(self, service_name: str, endpoint: str = "") -> str:
        """Get the URL for a specific service endpoint."""
        if service_name not in self.servers:
            raise ValueError(f"Server not started for service: {service_name}")

        server = self.servers[service_name]

        return f"http://{server.host}:{server.port}{endpoint}"

    def configure_rate_limiting(self, service_name: str, threshold: int) -> None:
        """Configure rate limiting for a service."""
        if service_name in self.servers:
            self.servers[service_name].set_rate_limit(threshold)

    def get_request_stats(self) -> Dict[str, int]:
        """Get request statistics for all servers."""
        return {service: server.get_request_count() for service, server in self.servers.items()}


# Global server manager instance
mock_server_manager = MockEnrichmentServerManager()


def start_mock_servers(services: List[str], base_port: int = 8888) -> Dict[str, int]:
    """Start mock servers for multiple services."""
    ports = {}
    port = base_port

    for service in services:
        server_port = mock_server_manager.start_server(service, port)
        ports[service] = server_port
        port += 1

    return ports


def stop_mock_servers() -> None:
    """Stop all mock servers."""
    mock_server_manager.stop_all_servers()


# Context manager for automatic server management
class MockServerContext:
    """Context manager for mock servers."""

    def __init__(self, services: List[str], base_port: int = 8888) -> None:
        """Initialize context manager for mock servers.

        Args:
            services: List of service names to start
            base_port: Base port number
        """
        self.services = services
        self.base_port = base_port
        self.ports: dict[str, int] = {}

    def __enter__(self) -> Dict[str, int]:
        """Start mock servers and return port mapping."""
        self.ports = start_mock_servers(self.services, self.base_port)
        return self.ports

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Stop all mock servers."""
        stop_mock_servers()


def with_mock_servers(services: List[str], base_port: int = 8888) -> MockServerContext:
    """Decorator/context manager for tests using mock servers."""
    return MockServerContext(services, base_port)
