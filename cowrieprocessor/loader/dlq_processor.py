"""Dead Letter Queue processor for reconstructing malformed Cowrie events.

This module provides intelligent analysis and repair of malformed JSON events
that were sent to the DLQ due to parsing failures. It implements various
strategies for reconstructing complete Cowrie events from fragmented data.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..db.engine import create_engine_from_settings, create_session_maker
from ..db.models import DeadLetterEvent, RawEvent
from ..settings import DatabaseSettings, load_database_settings


class CowrieEventValidator:
    """Validates Cowrie event structure against known patterns."""

    # Core Cowrie event types based on documentation
    EVENT_TYPES = {
        "cowrie.session.connect",
        "cowrie.session.closed",
        "cowrie.login.success",
        "cowrie.login.failed",
        "cowrie.command.input",
        "cowrie.command.failed",
        "cowrie.session.file_download",
        "cowrie.session.file_upload",
        "cowrie.direct-tcpip.request",
        "cowrie.direct-tcpip.data",
        "cowrie.client.version",
        "cowrie.client.kex",
        "cowrie.client.fingerprint",
        "cowrie.log.closed",
        "cowrie.system.info",
    }

    # Required fields for each event type
    REQUIRED_FIELDS = {
        "cowrie.session.connect": ["session", "src_ip", "timestamp"],
        "cowrie.session.closed": ["session", "timestamp"],
        "cowrie.login.success": ["session", "username", "password", "timestamp"],
        "cowrie.login.failed": ["session", "username", "password", "timestamp"],
        "cowrie.command.input": ["session", "command", "timestamp"],
        "cowrie.command.failed": ["session", "command", "timestamp"],
        "cowrie.session.file_download": ["session", "url", "shasum", "timestamp"],
        "cowrie.session.file_upload": ["session", "url", "shasum", "timestamp"],
        "cowrie.direct-tcpip.request": ["session", "dst_ip", "dst_port", "timestamp"],
        "cowrie.direct-tcpip.data": ["session", "data", "timestamp"],
        "cowrie.client.version": ["session", "version", "timestamp"],
        "cowrie.client.kex": ["session", "kexAlgs", "timestamp"],
        "cowrie.client.fingerprint": ["session", "fingerprint", "timestamp"],
        "cowrie.log.closed": ["session", "ttylog", "timestamp"],
        "cowrie.system.info": ["timestamp"],
    }

    @classmethod
    def validate_event(cls, event: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate a Cowrie event against known patterns.

        Args:
            event: The event dictionary to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Check eventid
        eventid = event.get("eventid")
        if not eventid:
            errors.append("missing_eventid")
        elif eventid not in cls.EVENT_TYPES:
            errors.append(f"unknown_eventid: {eventid}")

        # Check required fields
        if eventid in cls.REQUIRED_FIELDS:
            for field in cls.REQUIRED_FIELDS[eventid]:
                if field not in event:
                    errors.append(f"missing_required_field: {field}")

        # Validate timestamp format
        timestamp = event.get("timestamp")
        if timestamp:
            if not cls._is_valid_timestamp(timestamp):
                errors.append(f"invalid_timestamp_format: {timestamp}")

        # Validate session ID format
        session = event.get("session")
        if session and not cls._is_valid_session_id(session):
            errors.append(f"invalid_session_id_format: {session}")

        # Validate IP addresses
        src_ip = event.get("src_ip")
        if src_ip and not cls._is_valid_ip(src_ip):
            errors.append(f"invalid_src_ip: {src_ip}")

        return len(errors) == 0, errors

    @staticmethod
    def _is_valid_timestamp(timestamp: str) -> bool:
        """Check if timestamp follows ISO format."""
        try:
            datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            return True
        except (ValueError, AttributeError):
            return False

    @staticmethod
    def _is_valid_session_id(session: str) -> bool:
        """Check if session ID follows expected format."""
        # Cowrie session IDs are typically 8-character hex strings
        return bool(re.match(r'^[a-f0-9]{8}$', session))

    @staticmethod
    def _is_valid_ip(ip: str) -> bool:
        """Basic IP address validation."""
        # Simple regex for IPv4
        ipv4_pattern = r'^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$'
        return bool(re.match(ipv4_pattern, ip))


class JSONRepairStrategies:
    """Collection of strategies for repairing malformed JSON."""

    @staticmethod
    def fix_unclosed_strings(content: str) -> str:
        """Fix unclosed strings in JSON content."""
        # Count quotes and add closing quote if odd
        single_quotes = content.count("'")
        double_quotes = content.count('"')

        if single_quotes % 2 == 1:
            content += "'"
        if double_quotes % 2 == 1:
            content += '"'

        return content

    @staticmethod
    def fix_unclosed_braces(content: str) -> str:
        """Fix unclosed braces and brackets in JSON content."""
        open_braces = content.count('{')
        close_braces = content.count('}')
        open_brackets = content.count('[')
        close_brackets = content.count(']')

        # Add missing closing braces
        while open_braces > close_braces:
            content += '}'
            close_braces += 1

        # Add missing closing brackets
        while open_brackets > close_brackets:
            content += ']'
            close_brackets += 1

        return content

    @staticmethod
    def fix_trailing_commas(content: str) -> str:
        """Remove trailing commas before closing braces/brackets."""
        # Remove trailing commas before }
        content = re.sub(r',\s*}', '}', content)
        # Remove trailing commas before ]
        content = re.sub(r',\s*]', ']', content)
        return content

    @staticmethod
    def fix_unescaped_quotes(content: str) -> str:
        """Fix unescaped quotes in string values."""
        import re

        # Handle simple case: quote in middle of string value
        # Pattern: "key": "value"with"quote"
        # Replace with: "key": "value\"with\"quote"

        # Look for string values with unescaped quotes
        # This regex finds: "key": "value"with"quote"
        pattern = r'("[\w_]+"\s*:\s*")([^"]*")([^"]*")([^"]*")'

        def fix_quote_match(match):
            key_part = match.group(1)  # "key": "
            value_start = match.group(2)  # "value"
            middle_part = match.group(3)  # "with"
            value_end = match.group(4)  # "quote"

            # Reconstruct with escaped quotes
            fixed_value = value_start[:-1] + '\\"' + middle_part[1:-1] + '\\"' + value_end[1:]
            return key_part + fixed_value

        # Apply the fix
        content = re.sub(pattern, fix_quote_match, content)

        # Fallback: simple line-by-line approach for other cases
        lines = content.split('\n')
        fixed_lines = []

        for line in lines:
            # Simple heuristic: if line has odd number of quotes, try to fix
            quote_count = line.count('"')
            if quote_count % 2 == 1 and ':' in line:
                # Try to escape quotes in string values
                # Look for pattern: "key": "value"with"quote"
                if ': "' in line and line.count('"') >= 4:
                    # Find the value part after the colon
                    colon_pos = line.find(': "')
                    if colon_pos != -1:
                        key_part = line[: colon_pos + 3]  # Include ': "'
                        value_part = line[colon_pos + 3 :]

                        # Escape quotes in the value part, but preserve the closing quote
                        if value_part.endswith('"'):
                            value_part = value_part[:-1]  # Remove closing quote
                            value_part = value_part.replace('"', '\\"')
                            line = key_part + value_part + '"'
                        else:
                            value_part = value_part.replace('"', '\\"')
                            line = key_part + value_part

            fixed_lines.append(line)

        return '\n'.join(fixed_lines)

    @classmethod
    def repair_json(cls, content: str) -> str:
        """Apply all repair strategies to malformed JSON content."""
        from ..utils.unicode_sanitizer import UnicodeSanitizer

        # First sanitize Unicode control characters
        content = UnicodeSanitizer.sanitize_unicode_string(content, strict=False)

        # Apply repairs in order
        content = cls.fix_unescaped_quotes(content)
        content = cls.fix_trailing_commas(content)
        content = cls.fix_unclosed_strings(content)
        content = cls.fix_unclosed_braces(content)

        return content


class EventStitcher:
    """Stitches fragmented events into complete Cowrie events."""

    def __init__(self):
        """Initialize the event stitcher."""
        self.validator = CowrieEventValidator()
        self.repair_strategies = JSONRepairStrategies()

    def analyze_dlq_content(self, malformed_content: str) -> Dict[str, Any]:
        """Analyze malformed content to determine repair strategy.

        Args:
            malformed_content: The malformed JSON content from DLQ

        Returns:
            Analysis results with suggested repair strategy
        """
        analysis = {
            "content_length": len(malformed_content),
            "line_count": len(malformed_content.splitlines()),
            "has_opening_brace": '{' in malformed_content,
            "has_closing_brace": '}' in malformed_content,
            "brace_balance": malformed_content.count('{') - malformed_content.count('}'),
            "has_eventid": '"eventid"' in malformed_content or "'eventid'" in malformed_content,
            "has_session": '"session"' in malformed_content or "'session'" in malformed_content,
            "has_timestamp": '"timestamp"' in malformed_content or "'timestamp'" in malformed_content,
            "suggested_strategy": None,
        }

        # Determine repair strategy
        if analysis["brace_balance"] > 0:
            analysis["suggested_strategy"] = "fix_unclosed_braces"
        elif analysis["brace_balance"] < 0:
            analysis["suggested_strategy"] = "fix_overclosed_braces"
        elif not analysis["has_closing_brace"]:
            analysis["suggested_strategy"] = "add_closing_brace"
        elif '"' in malformed_content and malformed_content.count('"') % 2 == 1:
            analysis["suggested_strategy"] = "fix_unclosed_strings"
        else:
            analysis["suggested_strategy"] = "comprehensive_repair"

        return analysis

    def repair_event(self, malformed_content: str) -> Optional[Dict[str, Any]]:
        """Attempt to repair a malformed Cowrie event.

        Args:
            malformed_content: The malformed JSON content

        Returns:
            Repaired event dictionary or None if repair failed
        """
        # Try different repair strategies
        repair_attempts = [
            malformed_content,  # Try as-is first
            self.repair_strategies.repair_json(malformed_content),
            self._attempt_cowrie_specific_repair(malformed_content),  # New Cowrie-specific repair
            self._attempt_single_line_extraction(malformed_content),
            self._attempt_multiline_reconstruction(malformed_content),
        ]

        for attempt_content in repair_attempts:
            try:
                # Sanitize Unicode control characters before parsing
                from ..utils.unicode_sanitizer import UnicodeSanitizer

                sanitized_content = UnicodeSanitizer.sanitize_json_string(attempt_content)

                # Try to parse the repaired content
                event = json.loads(sanitized_content)

                # Validate the parsed event
                is_valid, errors = self.validator.validate_event(event)

                if is_valid:
                    return event
                elif len(errors) <= 2:  # Allow minor validation errors
                    # Add missing fields with defaults
                    event = self._fill_missing_fields(event, errors)
                    return event

            except (json.JSONDecodeError, ValueError):
                continue

        return None

    def _attempt_single_line_extraction(self, content: str) -> str:
        """Extract the first complete JSON object from multiline content."""
        lines = content.splitlines()

        # Look for the first line that starts with {
        for i, line in enumerate(lines):
            if line.strip().startswith('{'):
                # Try to find the matching closing brace
                brace_count = 0
                extracted_lines = []

                for j in range(i, len(lines)):
                    line_content = lines[j]
                    extracted_lines.append(line_content)

                    brace_count += line_content.count('{')
                    brace_count -= line_content.count('}')

                    if brace_count == 0:
                        return '\n'.join(extracted_lines)

                # If we didn't find a closing brace, return what we have
                return '\n'.join(extracted_lines)

        return content

    def _attempt_multiline_reconstruction(self, content: str) -> str:
        """Attempt to reconstruct a complete JSON object from fragments."""
        # Remove any leading/trailing whitespace
        content = content.strip()

        # Ensure it starts with {
        if not content.startswith('{'):
            content = '{' + content

        # Ensure it ends with }
        if not content.endswith('}'):
            content = content + '}'

        return content

    def _fill_missing_fields(self, event: Dict[str, Any], errors: List[str]) -> Dict[str, Any]:
        """Fill missing fields with reasonable defaults."""
        filled_event = event.copy()

        for error in errors:
            if error.startswith("missing_required_field:"):
                field = error.split(":", 1)[1].strip()

                if field == "timestamp":
                    filled_event["timestamp"] = datetime.now(timezone.utc).isoformat()
                elif field == "session":
                    filled_event["session"] = "unknown-session"
                elif field == "src_ip":
                    filled_event["src_ip"] = "0.0.0.0"
                elif field == "username":
                    filled_event["username"] = "unknown"
                elif field == "password":
                    filled_event["password"] = "unknown"
                elif field == "command":
                    filled_event["command"] = "unknown"
                elif field == "url":
                    filled_event["url"] = "unknown"
                elif field == "shasum":
                    filled_event["shasum"] = "0" * 64  # Default empty hash

        return filled_event

    def _attempt_cowrie_specific_repair(self, content: str) -> str:
        """Attempt Cowrie-specific repairs for common log patterns."""
        # Look for common Cowrie patterns and fix them

        # Pattern 1: Content that starts with array closing and field definitions
        # This is likely a fragment of a larger JSON object
        if content.strip().startswith('],') and '"eventid"' in content:
            # Try to reconstruct a complete Cowrie event
            content = self._reconstruct_cowrie_event_fragment(content)

        # Pattern 2: Content that starts with array closing but no eventid
        # This is likely a fragment of a Cowrie client event
        elif content.strip().startswith('],') and '"eventid"' not in content:
            # Try to reconstruct a client event from the fragment
            content = self._reconstruct_client_event_fragment(content)

        # Pattern 3: Content that looks like array elements without opening brace
        elif content.strip().startswith('"') and not content.strip().startswith('{'):
            # This might be a field value that got separated
            content = self._reconstruct_field_value(content)

        # Pattern 4: Content with trailing commas and incomplete arrays
        elif content.count('[') > content.count(']'):
            # Add missing closing brackets
            missing_brackets = content.count('[') - content.count(']')
            content += ']' * missing_brackets

        # Apply standard repairs
        content = self.repair_strategies.repair_json(content)

        return content

    def _reconstruct_cowrie_event_fragment(self, content: str) -> str:
        """Reconstruct a complete Cowrie event from a fragment."""
        # Extract the eventid to determine the event type
        eventid_match = re.search(r'"eventid":\s*"([^"]+)"', content)
        if not eventid_match:
            return content

        eventid = eventid_match.group(1)

        # Create a basic event structure based on the eventid
        if eventid == "cowrie.client.kex":
            return self._reconstruct_kex_event(content)
        elif eventid.startswith("cowrie.client"):
            return self._reconstruct_client_event(content, eventid)
        else:
            return self._reconstruct_generic_event(content, eventid)

    def _reconstruct_kex_event(self, content: str) -> str:
        """Reconstruct a cowrie.client.kex event."""
        # Extract key fields
        hassh_match = re.search(r'"hassh":\s*"([^"]+)"', content)
        hassh_algorithms_match = re.search(r'"hasshAlgorithms":\s*"([^"]+)"', content)

        # Extract arrays
        kex_algs = self._extract_array_values(content, 'kexAlgs')
        key_algs = self._extract_array_values(content, 'keyAlgs')
        enc_cs = self._extract_array_values(content, 'encCS')
        mac_cs = self._extract_array_values(content, 'macCS')
        lang_cs = self._extract_array_values(content, 'langCS')

        # Build complete event
        event = {
            "eventid": "cowrie.client.kex",
            "timestamp": self._get_current_timestamp(),
            "session": "unknown-session",  # Default value
        }

        if hassh_match:
            event["hassh"] = hassh_match.group(1)
        if hassh_algorithms_match:
            event["hasshAlgorithms"] = hassh_algorithms_match.group(1)
        if kex_algs:
            event["kexAlgs"] = kex_algs
        if key_algs:
            event["keyAlgs"] = key_algs
        if enc_cs:
            event["encCS"] = enc_cs
        if mac_cs:
            event["macCS"] = mac_cs
        if lang_cs:
            event["langCS"] = lang_cs

        return json.dumps(event)

    def _reconstruct_client_event(self, content: str, eventid: str) -> str:
        """Reconstruct a generic client event."""
        event = {
            "eventid": eventid,
            "timestamp": self._get_current_timestamp(),
            "session": "unknown-session",
        }

        # Extract any other fields that might be present
        for field in ["version", "fingerprint", "message"]:
            match = re.search(f'"{field}":\\s*"([^"]+)"', content)
            if match:
                event[field] = match.group(1)

        return json.dumps(event)

    def _reconstruct_client_event_fragment(self, content: str) -> str:
        """Reconstruct a client event from a fragment without eventid."""
        # This is likely a fragment of a cowrie.client.kex event
        # Extract arrays that might be present
        kex_algs = self._extract_array_values(content, 'kexAlgs')
        key_algs = self._extract_array_values(content, 'keyAlgs')
        enc_cs = self._extract_array_values(content, 'encCS')
        mac_cs = self._extract_array_values(content, 'macCS')
        lang_cs = self._extract_array_values(content, 'langCS')

        # Build complete event
        event = {
            "eventid": "cowrie.client.kex",
            "timestamp": self._get_current_timestamp(),
            "session": "unknown-session",
        }

        if kex_algs:
            event["kexAlgs"] = kex_algs
        if key_algs:
            event["keyAlgs"] = key_algs
        if enc_cs:
            event["encCS"] = enc_cs
        if mac_cs:
            event["macCS"] = mac_cs
        if lang_cs:
            event["langCS"] = lang_cs

        return json.dumps(event)

    def _reconstruct_generic_event(self, content: str, eventid: str) -> str:
        """Reconstruct a generic Cowrie event."""
        event = {
            "eventid": eventid,
            "timestamp": self._get_current_timestamp(),
            "session": "unknown-session",
        }

        # Try to extract common fields
        for field in ["src_ip", "username", "password", "command", "url", "message"]:
            match = re.search(f'"{field}":\\s*"([^"]+)"', content)
            if match:
                event[field] = match.group(1)

        return json.dumps(event)

    def _reconstruct_field_value(self, content: str) -> str:
        """Reconstruct a field value that got separated."""
        # This is likely a string value that needs to be wrapped in an object
        content = content.strip()

        # Remove leading/trailing quotes if present
        if content.startswith('"') and content.endswith('"'):
            content = content[1:-1]

        # Create a simple event with this as a message
        event = {
            "eventid": "cowrie.system.info",
            "timestamp": self._get_current_timestamp(),
            "message": content,
        }

        return json.dumps(event)

    def _extract_array_values(self, content: str, field_name: str) -> Optional[List[str]]:
        """Extract array values from content."""
        # Look for the field and extract its array values
        # Handle both complete and incomplete arrays

        # First try complete arrays
        complete_pattern = f'"{field_name}":\\s*\\[([^\\]]+(?:\\n[^\\]]*)*)\\]'
        match = re.search(complete_pattern, content, re.DOTALL)

        if not match:
            # Try incomplete arrays (no closing bracket)
            incomplete_pattern = f'"{field_name}":\\s*\\[([^\\]]+(?:\\n[^\\]]*)*)'
            match = re.search(incomplete_pattern, content, re.DOTALL)

        if not match:
            return None

        array_content = match.group(1)
        # Split by commas and clean up values
        values = []
        for line in array_content.split(','):
            line = line.strip()
            # Remove quotes and newlines
            line = line.replace('\n', '').replace('\r', '')
            if line.startswith('"') and line.endswith('"'):
                values.append(line[1:-1])
            elif line.startswith('"'):
                values.append(line[1:])
            elif line:  # Non-empty line without quotes
                values.append(line)

        return values if values else None

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        return datetime.now(timezone.utc).isoformat()


def _load_database_settings_from_sensors(db_path: Optional[str] = None) -> DatabaseSettings:
    """Load database settings from sensors.toml or use provided path.

    Args:
        db_path: Optional explicit database path

    Returns:
        DatabaseSettings configured from sensors.toml or explicit path
    """
    if db_path:
        # Use explicit database path
        return load_database_settings(config={"url": f"sqlite:///{db_path}"})

    # Try to load from sensors.toml
    sensors_file = Path("sensors.toml")
    if sensors_file.exists():
        try:
            # Try tomllib first (Python 3.11+)
            try:
                import tomllib
            except ImportError:
                # Fall back to tomli for older Python versions
                import tomli as tomllib

            with sensors_file.open("rb") as handle:
                data = tomllib.load(handle)

            # Check for global database configuration
            global_config = data.get("global", {})
            db_url = global_config.get("db")
            if db_url:
                return load_database_settings(config={"url": db_url})

        except Exception as e:
            print(f"Warning: Could not load database config from sensors.toml: {e}")

    # Fall back to default settings
    return DatabaseSettings()


class DLQProcessor:
    """Main processor for handling Dead Letter Queue events."""

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the DLQ processor."""
        self.db_path = db_path
        self.stitcher = EventStitcher()
        self.processed_count = 0
        self.repaired_count = 0
        self.failed_count = 0

    def process_dlq_events(self, limit: Optional[int] = None, reason_filter: Optional[str] = None) -> Dict[str, int]:
        """Process events from the Dead Letter Queue.

        Args:
            limit: Maximum number of events to process
            reason_filter: Only process events with this reason

        Returns:
            Statistics about processing results
        """
        stats = {
            "processed": 0,
            "repaired": 0,
            "failed": 0,
            "skipped": 0,
        }

        # Create database connection using sensors.toml or explicit path
        settings = _load_database_settings_from_sensors(self.db_path)
        engine = create_engine_from_settings(settings)
        session_factory = create_session_maker(engine)

        with session_factory() as session:
            # Query DLQ events
            query = session.query(DeadLetterEvent).filter(not DeadLetterEvent.resolved)

            if reason_filter:
                query = query.filter(DeadLetterEvent.reason == reason_filter)

            if limit:
                query = query.limit(limit)

            dlq_events = query.all()

            for dlq_event in dlq_events:
                stats["processed"] += 1

                # Extract malformed content
                malformed_content = self._extract_malformed_content(dlq_event)

                if not malformed_content:
                    stats["skipped"] += 1
                    continue

                # Attempt to repair the event
                repaired_event = self.stitcher.repair_event(malformed_content)

                if repaired_event:
                    # Insert repaired event into raw_events table
                    success = self._insert_repaired_event(session, dlq_event, repaired_event)

                    if success:
                        # Mark DLQ event as resolved
                        dlq_event.resolved = True
                        dlq_event.resolved_at = datetime.now(timezone.utc)
                        stats["repaired"] += 1
                    else:
                        stats["failed"] += 1
                else:
                    stats["failed"] += 1

            session.commit()

        return stats

    def _extract_malformed_content(self, dlq_event: DeadLetterEvent) -> Optional[str]:
        """Extract malformed content from DLQ event."""
        payload = dlq_event.payload

        if isinstance(payload, dict):
            return payload.get("malformed_content")

        return None

    def _insert_repaired_event(self, session, dlq_event: DeadLetterEvent, repaired_event: Dict[str, Any]) -> bool:
        """Insert repaired event into raw_events table with duplicate handling."""
        try:
            from sqlalchemy.dialects.postgresql import insert

            # Create raw event record data
            event_data = {
                "ingest_id": dlq_event.ingest_id,
                "source": dlq_event.source or "dlq-repair",
                "source_offset": dlq_event.source_offset,
                "source_inode": dlq_event.source,
                "source_generation": 0,
                "payload": repaired_event,
                "risk_score": 50,  # Medium risk for repaired events
                "quarantined": False,  # Repaired events are no longer quarantined
                "session_id": repaired_event.get("session"),
                "event_type": repaired_event.get("eventid"),
                "event_timestamp": repaired_event.get("timestamp"),
            }

            # Use PostgreSQL UPSERT (ON CONFLICT DO UPDATE)
            # This will update the existing record with repaired data
            stmt = insert(RawEvent.__table__).values(**event_data)
            stmt = stmt.on_conflict_do_update(
                index_elements=['source', 'source_inode', 'source_generation', 'source_offset'],
                set_={
                    'payload': stmt.excluded.payload,
                    'risk_score': stmt.excluded.risk_score,
                    'quarantined': stmt.excluded.quarantined,
                    'session_id': stmt.excluded.session_id,
                    'event_type': stmt.excluded.event_type,
                    'event_timestamp': stmt.excluded.event_timestamp,
                    'ingest_at': stmt.excluded.ingest_at,
                },
            )

            session.execute(stmt)

            # Always consider this a success since we either inserted or updated
            return True

        except Exception:
            # If we're not using PostgreSQL, fall back to check-then-insert
            try:
                from sqlalchemy import select

                existing_query = select(RawEvent).where(
                    RawEvent.source == dlq_event.source,
                    RawEvent.source_offset == dlq_event.source_offset,
                    RawEvent.source_inode == dlq_event.source,
                    RawEvent.source_generation == 0,
                )

                existing_event = session.execute(existing_query).first()

                if existing_event:
                    # Event already exists, update it with repaired data
                    existing_raw_event = existing_event[0]
                    existing_raw_event.payload = repaired_event
                    existing_raw_event.risk_score = 50
                    existing_raw_event.quarantined = False
                    existing_raw_event.session_id = repaired_event.get("session")
                    existing_raw_event.event_type = repaired_event.get("eventid")
                    existing_raw_event.event_timestamp = repaired_event.get("timestamp")
                    # Update the ingest timestamp to reflect the repair
                    from datetime import datetime

                    existing_raw_event.ingest_at = datetime.utcnow()
                    return True

                # Create new raw event record
                raw_event = RawEvent(
                    ingest_id=dlq_event.ingest_id,
                    source=dlq_event.source or "dlq-repair",
                    source_offset=dlq_event.source_offset,
                    source_inode=dlq_event.source,
                    payload=repaired_event,
                    risk_score=50,  # Medium risk for repaired events
                    quarantined=False,  # Repaired events are no longer quarantined
                    session_id=repaired_event.get("session"),
                    event_type=repaired_event.get("eventid"),
                    event_timestamp=repaired_event.get("timestamp"),
                )

                session.add(raw_event)
                return True

            except Exception as fallback_error:
                print(f"Failed to insert repaired event: {fallback_error}")
                return False

    def analyze_dlq_patterns(self) -> Dict[str, Any]:
        """Analyze patterns in DLQ events to understand common issues."""
        patterns = {
            "total_events": 0,
            "by_reason": {},
            "by_source": {},
            "common_issues": [],
        }

        # Create database connection using sensors.toml or explicit path
        settings = _load_database_settings_from_sensors(self.db_path)
        engine = create_engine_from_settings(settings)
        session_factory = create_session_maker(engine)

        with session_factory() as session:
            dlq_events = session.query(DeadLetterEvent).filter(not DeadLetterEvent.resolved).all()

            patterns["total_events"] = len(dlq_events)

            for event in dlq_events:
                # Count by reason
                reason = event.reason or "unknown"
                patterns["by_reason"][reason] = patterns["by_reason"].get(reason, 0) + 1

                # Count by source
                source = event.source or "unknown"
                patterns["by_source"][source] = patterns["by_source"].get(source, 0) + 1

                # Analyze content for common issues
                malformed_content = self._extract_malformed_content(event)
                if malformed_content:
                    analysis = self.stitcher.analyze_dlq_content(malformed_content)
                    patterns["common_issues"].append(analysis)

        return patterns


def main():
    """CLI entry point for DLQ processing."""
    import argparse

    parser = argparse.ArgumentParser(description="Process Dead Letter Queue events")
    parser.add_argument("--db-path", help="Path to SQLite database")
    parser.add_argument("--limit", type=int, help="Maximum events to process")
    parser.add_argument("--reason", help="Only process events with this reason")
    parser.add_argument("--analyze", action="store_true", help="Analyze DLQ patterns")

    args = parser.parse_args()

    processor = DLQProcessor(args.db_path)

    if args.analyze:
        patterns = processor.analyze_dlq_patterns()
        print(json.dumps(patterns, indent=2))
    else:
        stats = processor.process_dlq_events(args.limit, args.reason)
        print(f"Processed: {stats['processed']}")
        print(f"Repaired: {stats['repaired']}")
        print(f"Failed: {stats['failed']}")
        print(f"Skipped: {stats['skipped']}")


if __name__ == "__main__":
    main()
