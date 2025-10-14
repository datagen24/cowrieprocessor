"""Comprehensive Cowrie event validation schema.

This module provides detailed validation schemas for all Cowrie event types
based on the official documentation and real-world log analysis.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Union

try:
    from jsonschema import ValidationError, validate
except ImportError:
    # Fallback for environments without jsonschema
    def validate(instance, schema):
        """Fallback validate function when jsonschema is not available."""
        pass

    class ValidationError(Exception):
        """Fallback ValidationError class when jsonschema is not available."""
        
        def __init__(self, message):
            """Initialize ValidationError with message."""
            self.message = message
            super().__init__(message)


class CowrieEventSchema:
    """Comprehensive validation schemas for Cowrie events."""

    # Base schema that all Cowrie events must satisfy
    BASE_SCHEMA = {
        "type": "object",
        "required": ["eventid", "timestamp"],
        "properties": {
            "eventid": {"type": "string", "pattern": "^cowrie\\.[a-z]+\\.[a-z]+$"},
            "timestamp": {"type": "string", "format": "date-time"},
            "session": {"type": "string", "pattern": "^(?:[a-f0-9]{8}|unknown-session)$"},
            "src_ip": {"type": "string", "format": "ipv4"},
            "dst_ip": {"type": "string", "format": "ipv4"},
            "src_port": {"type": "integer", "minimum": 1, "maximum": 65535},
            "dst_port": {"type": "integer", "minimum": 1, "maximum": 65535},
        },
        "additionalProperties": True,
    }

    # Event-specific schemas
    EVENT_SCHEMAS = {
        "cowrie.session.connect": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "src_ip"],
            "properties": {
                "eventid": {"const": "cowrie.session.connect"},
                "protocol": {"type": "string", "enum": ["ssh", "telnet"]},
                "src_ip": {"type": "string", "format": "ipv4"},
                "src_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "dst_ip": {"type": "string", "format": "ipv4"},
                "dst_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "ttylog": {"type": "string"},
                "duration": {"type": "string"},
                "version": {"type": "string"},
                "cipher": {"type": "string"},
                "mac": {"type": "string"},
                "compression": {"type": "string"},
                "kexAlgs": {"type": "array", "items": {"type": "string"}},
                "keyAlgs": {"type": "array", "items": {"type": "string"}},
                "enc": {"type": "array", "items": {"type": "string"}},
                "macs": {"type": "array", "items": {"type": "string"}},
                "comp": {"type": "array", "items": {"type": "string"}},
                "fingerprint": {"type": "string"},
                "hassh": {"type": "string"},
                "hasshAlgorithms": {"type": "string"},
                "hasshServer": {"type": "string"},
                "hasshServerAlgorithms": {"type": "string"},
            },
        },
        "cowrie.session.closed": {
            "type": "object",
            "required": ["eventid", "timestamp", "session"],
            "properties": {
                "eventid": {"const": "cowrie.session.closed"},
                "duration": {"type": "string"},
                "ttylog": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
                "shasum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            },
        },
        "cowrie.login.success": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "username", "password"],
            "properties": {
                "eventid": {"const": "cowrie.login.success"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "src_ip": {"type": "string", "format": "ipv4"},
                "message": {"type": "string"},
            },
        },
        "cowrie.login.failed": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "username", "password"],
            "properties": {
                "eventid": {"const": "cowrie.login.failed"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "src_ip": {"type": "string", "format": "ipv4"},
                "message": {"type": "string"},
            },
        },
        "cowrie.command.input": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "command"],
            "properties": {
                "eventid": {"const": "cowrie.command.input"},
                "command": {"type": "string"},
                "input": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.command.failed": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "command"],
            "properties": {
                "eventid": {"const": "cowrie.command.failed"},
                "command": {"type": "string"},
                "input": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.session.file_download": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "url", "shasum"],
            "properties": {
                "eventid": {"const": "cowrie.session.file_download"},
                "url": {"type": "string", "format": "uri"},
                "shasum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "destfile": {"type": "string"},
                "filename": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
                "outfile": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.session.file_upload": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "url", "shasum"],
            "properties": {
                "eventid": {"const": "cowrie.session.file_upload"},
                "url": {"type": "string", "format": "uri"},
                "shasum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
                "filename": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
                "outfile": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.direct-tcpip.request": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "dst_ip", "dst_port"],
            "properties": {
                "eventid": {"const": "cowrie.direct-tcpip.request"},
                "dst_ip": {"type": "string", "format": "ipv4"},
                "dst_port": {"type": "integer", "minimum": 1, "maximum": 65535},
                "src_ip": {"type": "string", "format": "ipv4"},
                "src_port": {"type": "integer", "minimum": 1, "maximum": 65535},
            },
        },
        "cowrie.direct-tcpip.data": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "data"],
            "properties": {
                "eventid": {"const": "cowrie.direct-tcpip.data"},
                "data": {"type": "string"},
                "dst_ip": {"type": "string", "format": "ipv4"},
                "dst_port": {"type": "integer", "minimum": 1, "maximum": 65535},
            },
        },
        "cowrie.client.version": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "version"],
            "properties": {
                "eventid": {"const": "cowrie.client.version"},
                "version": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.client.kex": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "kexAlgs"],
            "properties": {
                "eventid": {"const": "cowrie.client.kex"},
                "kexAlgs": {"type": "array", "items": {"type": "string"}},
                "message": {"type": "string"},
            },
        },
        "cowrie.client.fingerprint": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "fingerprint"],
            "properties": {
                "eventid": {"const": "cowrie.client.fingerprint"},
                "fingerprint": {"type": "string"},
                "message": {"type": "string"},
            },
        },
        "cowrie.log.closed": {
            "type": "object",
            "required": ["eventid", "timestamp", "session", "ttylog"],
            "properties": {
                "eventid": {"const": "cowrie.log.closed"},
                "ttylog": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
                "shasum": {"type": "string", "pattern": "^[a-f0-9]{64}$"},
            },
        },
        "cowrie.system.info": {
            "type": "object",
            "required": ["eventid", "timestamp"],
            "properties": {
                "eventid": {"const": "cowrie.system.info"},
                "message": {"type": "string"},
                "system": {"type": "string"},
                "version": {"type": "string"},
            },
        },
    }

    @classmethod
    def validate_event(cls, event: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a Cowrie event against the appropriate schema.

        Args:
            event: The event dictionary to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # First validate against base schema
        try:
            validate(instance=event, schema=cls.BASE_SCHEMA)
        except ValidationError as e:
            errors.append(f"base_schema_error: {e.message}")

        # Then validate against event-specific schema
        eventid = event.get("eventid")
        if eventid in cls.EVENT_SCHEMAS:
            try:
                validate(instance=event, schema=cls.EVENT_SCHEMAS[eventid])
            except ValidationError as e:
                errors.append(f"event_schema_error: {e.message}")
        elif eventid:
            errors.append(f"unknown_event_type: {eventid}")

        # Additional custom validations
        custom_errors = cls._custom_validations(event)
        errors.extend(custom_errors)

        return len(errors) == 0, errors

    @classmethod
    def _custom_validations(cls, event: Dict[str, Any]) -> List[str]:
        """Perform custom validations beyond JSON schema."""
        errors = []

        # Validate timestamp format
        timestamp = event.get("timestamp")
        if timestamp:
            if not cls._is_valid_timestamp(timestamp):
                errors.append(f"invalid_timestamp_format: {timestamp}")

        # Validate session ID format
        session = event.get("session")
        if session:
            if not cls._is_valid_session_id(session):
                errors.append(f"invalid_session_id_format: {session}")

        # Validate IP addresses
        for ip_field in ["src_ip", "dst_ip"]:
            ip_value = event.get(ip_field)
            if ip_value and not cls._is_valid_ip(ip_value):
                errors.append(f"invalid_{ip_field}: {ip_value}")

        # Validate ports
        for port_field in ["src_port", "dst_port"]:
            port_value = event.get(port_field)
            if port_value is not None:
                try:
                    port = int(port_value)
                    if port < 1 or port > 65535:
                        errors.append(f"invalid_{port_field}: {port_value}")
                except (ValueError, TypeError):
                    errors.append(f"invalid_{port_field}: {port_value}")

        # Validate SHA-256 hashes
        for hash_field in ["shasum"]:
            hash_value = event.get(hash_field)
            if hash_value and not cls._is_valid_sha256(hash_value):
                errors.append(f"invalid_{hash_field}: {hash_value}")

        # Validate URLs
        url_value = event.get("url")
        if url_value and not cls._is_valid_url(url_value):
            errors.append(f"invalid_url: {url_value}")

        return errors

    @staticmethod
    def _is_valid_timestamp(timestamp: str) -> bool:
        """Check if timestamp follows ISO format."""
        try:
            # Try parsing with timezone info
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _is_valid_session_id(session: str) -> bool:
        """Check if session ID follows expected format."""
        # Cowrie session IDs are typically 8-character hex strings
        # Allow "unknown-session" for reconstructed events
        if session == "unknown-session":
            return True
        return bool(re.match(r'^[a-f0-9]{8}$', session))

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Basic IP address validation."""
        # Simple regex for IPv4
        ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        return bool(re.match(ipv4_pattern, ip))

    @staticmethod
    def _is_valid_sha256(hash_value: str) -> bool:
        """Check if value is a valid SHA-256 hash."""
        return bool(re.match(r'^[a-f0-9]{64}$', hash_value))

    @staticmethod
    def _is_valid_url(url: str) -> bool:
        """Basic URL validation."""
        url_pattern = r'^https?://[^\s/$.?#].[^\s]*$'
        return bool(re.match(url_pattern, url))

    @classmethod
    def get_event_schema(cls, eventid: str) -> Optional[Dict[str, Any]]:
        """Get the schema for a specific event type."""
        return cls.EVENT_SCHEMAS.get(eventid)

    @classmethod
    def list_event_types(cls) -> List[str]:
        """Get list of all supported event types."""
        return list(cls.EVENT_SCHEMAS.keys())

    @classmethod
    def get_required_fields(cls, eventid: str) -> List[str]:
        """Get required fields for a specific event type."""
        schema = cls.get_event_schema(eventid)
        if schema:
            return schema.get("required", [])
        return []


class EventRepairer:
    """Repairs common issues in Cowrie events."""

    @classmethod
    def repair_event(cls, event: Dict[str, Any]) -> Dict[str, Any]:
        """Repair common issues in a Cowrie event.

        Args:
            event: The event to repair

        Returns:
            Repaired event
        """
        repaired = event.copy()

        # Fix timestamp format
        timestamp = repaired.get("timestamp")
        if timestamp:
            repaired["timestamp"] = cls._repair_timestamp(timestamp)

        # Fix session ID format
        session = repaired.get("session")
        if session:
            repaired["session"] = cls._repair_session_id(session)

        # Fix IP addresses
        for ip_field in ["src_ip", "dst_ip"]:
            ip_value = repaired.get(ip_field)
            if ip_value:
                repaired[ip_field] = cls._repair_ip_address(ip_value)

        # Fix ports
        for port_field in ["src_port", "dst_port"]:
            port_value = repaired.get(port_field)
            if port_value is not None:
                repaired[port_field] = cls._repair_port(port_value)

        # Fix SHA-256 hashes
        hash_value = repaired.get("shasum")
        if hash_value:
            repaired["shasum"] = cls._repair_sha256(hash_value)

        # Fix URLs
        url_value = repaired.get("url")
        if url_value:
            repaired["url"] = cls._repair_url(url_value)

        return repaired

    @staticmethod
    def _repair_timestamp(timestamp: str) -> str:
        """Repair timestamp format."""
        # Remove any non-standard characters
        timestamp = re.sub(r'[^\d\-\+T:Z.]', '', timestamp)

        # Ensure it ends with Z or timezone
        if not timestamp.endswith(('Z', '+', '-')):
            timestamp += 'Z'

        return timestamp

    @staticmethod
    def _repair_session_id(session: str) -> str:
        """Repair session ID format."""
        # Remove any non-hex characters
        session = re.sub(r'[^a-f0-9]', '', session.lower())

        # Pad or truncate to 8 characters
        if len(session) < 8:
            session = session.ljust(8, '0')
        elif len(session) > 8:
            session = session[:8]

        return session

    @staticmethod
    def _repair_ip_address(ip: str) -> str:
        """Repair IP address format."""
        # Remove any non-numeric characters except dots
        ip = re.sub(r'[^\d.]', '', ip)

        # Basic validation - if it doesn't look like an IP, return 0.0.0.0
        if not re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', ip):
            return "0.0.0.0"

        return ip

    @staticmethod
    def _repair_port(port: Union[str, int]) -> int:
        """Repair port number."""
        try:
            port_int = int(port)
            if 1 <= port_int <= 65535:
                return port_int
            else:
                return 22  # Default SSH port
        except (ValueError, TypeError):
            return 22

    @staticmethod
    def _repair_sha256(hash_value: str) -> str:
        """Repair SHA-256 hash."""
        # Remove any non-hex characters
        hash_value = re.sub(r'[^a-f0-9]', '', hash_value.lower())

        # Pad or truncate to 64 characters
        if len(hash_value) < 64:
            hash_value = hash_value.ljust(64, '0')
        elif len(hash_value) > 64:
            hash_value = hash_value[:64]

        return hash_value

    @staticmethod
    def _repair_url(url: str) -> str:
        """Repair URL format."""
        # Add protocol if missing
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url

        return url


def main():
    """CLI entry point for schema validation."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Validate Cowrie event schemas")
    parser.add_argument("event_file", help="JSON file containing event to validate")
    parser.add_argument("--repair", action="store_true", help="Attempt to repair the event")
    parser.add_argument("--list-types", action="store_true", help="List all supported event types")

    args = parser.parse_args()

    if args.list_types:
        schema = CowrieEventSchema()
        print("Supported Cowrie event types:")
        for event_type in schema.list_event_types():
            print(f"  {event_type}")
        return

    try:
        with open(args.event_file, 'r') as f:
            event = json.load(f)

        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(event)

        if is_valid:
            print("Event is valid!")
        else:
            print("Event validation failed:")
            for error in errors:
                print(f"  {error}")

            if args.repair:
                print("\nAttempting to repair event...")
                repairer = EventRepairer()
                repaired_event = repairer.repair_event(event)

                is_repaired_valid, repair_errors = schema.validate_event(repaired_event)
                if is_repaired_valid:
                    print("Event repaired successfully!")
                    print(json.dumps(repaired_event, indent=2))
                else:
                    print("Repair failed:")
                    for error in repair_errors:
                        print(f"  {error}")

    except FileNotFoundError:
        print(f"Error: File not found: {args.event_file}")
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
