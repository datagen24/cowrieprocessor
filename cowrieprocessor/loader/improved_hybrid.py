"""Improved hybrid JSON processor for Cowrie logs.

This module provides a robust hybrid processor that can handle both single-line
and multiline JSON formats without the failures present in the original implementation.
It uses intelligent buffering and repair strategies to minimize DLQ events.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterator, List, Optional, Tuple

from .dlq_processor import EventStitcher, JSONRepairStrategies


class ImprovedHybridProcessor:
    """Improved hybrid processor that handles mixed JSON formats robustly."""

    def __init__(self, max_buffer_lines: int = 50, repair_threshold: int = 3):
        """Initialize the improved hybrid processor.

        Args:
            max_buffer_lines: Maximum lines to buffer before giving up
            repair_threshold: Number of repair attempts before sending to DLQ
        """
        self.max_buffer_lines = max_buffer_lines
        self.repair_threshold = repair_threshold
        self.stitcher = EventStitcher()
        self.repair_strategies = JSONRepairStrategies()

        # Statistics
        self.stats = {
            "single_line_parsed": 0,
            "multiline_parsed": 0,
            "repaired_parsed": 0,
            "dlq_sent": 0,
            "total_lines": 0,
        }

    def process_lines(self, lines: Iterator[str]) -> Iterator[Tuple[int, Any]]:
        """Process lines with improved hybrid logic.

        Args:
            lines: Iterator of input lines

        Yields:
            Tuple of (line_offset, parsed_event_or_dlq_event)
        """
        buffer: List[str] = []
        buffer_start_offset = 0

        for line_offset, line in enumerate(lines):
            self.stats["total_lines"] += 1
            stripped = line.strip()

            if not stripped:
                continue

            # Try single-line parsing first
            single_line_result = self._try_single_line_parse(stripped)
            if single_line_result is not None:
                # Clear any accumulated buffer
                if buffer:
                    # Send buffered content to DLQ
                    yield buffer_start_offset, self._make_dlq_event("\n".join(buffer), "buffer_cleared_for_single_line")
                    buffer = []

                yield line_offset, single_line_result
                self.stats["single_line_parsed"] += 1
                continue

            # Single-line parsing failed, add to buffer
            if not buffer:
                buffer_start_offset = line_offset

            buffer.append(stripped)

            # Try to parse accumulated buffer
            buffer_result = self._try_buffer_parse(buffer)
            if buffer_result is not None:
                yield buffer_start_offset, buffer_result
                self.stats["multiline_parsed"] += 1
                buffer = []
                continue

            # Check if buffer is too large
            if len(buffer) >= self.max_buffer_lines:
                # Try repair strategies before giving up
                repaired_result = self._try_repair_buffer(buffer)
                if repaired_result is not None:
                    yield buffer_start_offset, repaired_result
                    self.stats["repaired_parsed"] += 1
                    buffer = []
                else:
                    # Send to DLQ
                    yield buffer_start_offset, self._make_dlq_event("\n".join(buffer), "buffer_too_large")
                    self.stats["dlq_sent"] += 1
                    buffer = []

        # Handle remaining buffer
        if buffer:
            # Try repair strategies for remaining buffer
            repaired_result = self._try_repair_buffer(buffer)
            if repaired_result is not None:
                yield buffer_start_offset, repaired_result
                self.stats["repaired_parsed"] += 1
            else:
                yield buffer_start_offset, self._make_dlq_event("\n".join(buffer), "end_of_file_buffer")
                self.stats["dlq_sent"] += 1

    def _try_single_line_parse(self, line: str) -> Optional[dict]:
        """Try to parse a single line as JSON."""
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            return None

    def _try_buffer_parse(self, buffer: List[str]) -> Optional[dict]:
        """Try to parse accumulated buffer as JSON."""
        try:
            content = "\n".join(buffer)
            return json.loads(content)
        except json.JSONDecodeError:
            return None

    def _try_repair_buffer(self, buffer: List[str]) -> Optional[dict]:
        """Try to repair and parse buffer using various strategies."""
        content = "\n".join(buffer)

        # Try different repair strategies
        repair_attempts = [
            content,  # Try as-is
            self.repair_strategies.repair_json(content),
            self._attempt_smart_repair(content),
            self._attempt_cowrie_specific_repair(content),
        ]

        for attempt in repair_attempts:
            try:
                result = json.loads(attempt)
                # Basic validation - check if it looks like a Cowrie event
                if self._is_likely_cowrie_event(result):
                    return result
            except json.JSONDecodeError:
                continue

        return None

    def _attempt_smart_repair(self, content: str) -> str:
        """Attempt smart repair based on content analysis."""
        # Remove any non-JSON content at the beginning
        content = content.strip()

        # Find the first opening brace
        first_brace = content.find('{')
        if first_brace > 0:
            content = content[first_brace:]

        # Find the last closing brace
        last_brace = content.rfind('}')
        if last_brace > 0 and last_brace < len(content) - 1:
            content = content[: last_brace + 1]

        # Apply standard repairs
        content = self.repair_strategies.repair_json(content)

        return content

    def _attempt_cowrie_specific_repair(self, content: str) -> str:
        """Attempt Cowrie-specific repairs."""
        # Look for common Cowrie patterns and fix them

        # Fix common Cowrie timestamp issues
        content = re.sub(r'"timestamp":\s*"([^"]*)"', r'"timestamp": "\1"', content)

        # Fix common Cowrie session ID issues
        content = re.sub(r'"session":\s*"([^"]*)"', r'"session": "\1"', content)

        # Fix common Cowrie eventid issues
        content = re.sub(r'"eventid":\s*"([^"]*)"', r'"eventid": "\1"', content)

        # Apply standard repairs
        content = self.repair_strategies.repair_json(content)

        return content

    def _is_likely_cowrie_event(self, event: dict) -> bool:
        """Check if parsed event looks like a Cowrie event."""
        if not isinstance(event, dict):
            return False

        # Check for Cowrie-specific fields
        cowrie_indicators = [
            "eventid",
            "session",
            "timestamp",
            "src_ip",
            "protocol",
        ]

        indicator_count = sum(1 for indicator in cowrie_indicators if indicator in event)

        # Must have at least 2 Cowrie indicators
        return indicator_count >= 2

    def _make_dlq_event(self, content: str, reason: str) -> dict:
        """Create a dead letter event."""
        return {
            "_dead_letter": True,
            "_reason": reason,
            "_malformed_content": content,
            "_timestamp": self._get_current_timestamp(),
            "_processor": "improved_hybrid",
        }

    def _get_current_timestamp(self) -> str:
        """Get current timestamp in ISO format."""
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def get_stats(self) -> dict:
        """Get processing statistics."""
        return self.stats.copy()


class RobustJSONIterator:
    """Robust iterator that handles file reading with error recovery."""

    def __init__(self, file_path: str, encoding: str = "utf-8"):
        """Initialize the iterator.

        Args:
            file_path: Path to the file to read
            encoding: File encoding
        """
        self.file_path = file_path
        self.encoding = encoding
        self.line_count = 0
        self.error_count = 0

    def __iter__(self) -> Iterator[str]:
        """Iterate through file lines with error recovery."""
        try:
            with open(self.file_path, 'r', encoding=self.encoding, errors='replace') as f:
                for line in f:
                    self.line_count += 1
                    yield line.rstrip('\n\r')
        except Exception as e:
            print(f"Error reading file {self.file_path}: {e}")
            self.error_count += 1

    def get_stats(self) -> dict:
        """Get reading statistics."""
        return {
            "line_count": self.line_count,
            "error_count": self.error_count,
        }


def process_cowrie_file_hybrid(file_path: str) -> Iterator[Tuple[int, Any]]:
    """Process a Cowrie log file using the improved hybrid processor.

    Args:
        file_path: Path to the Cowrie log file

    Yields:
        Tuple of (line_offset, parsed_event_or_dlq_event)
    """
    processor = ImprovedHybridProcessor()
    iterator = RobustJSONIterator(file_path)

    yield from processor.process_lines(iterator)


def main():
    """CLI entry point for testing the improved hybrid processor."""
    import argparse

    parser = argparse.ArgumentParser(description="Test improved hybrid JSON processor")
    parser.add_argument("file_path", help="Path to Cowrie log file")
    parser.add_argument("--stats", action="store_true", help="Show processing statistics")

    args = parser.parse_args()

    processor = ImprovedHybridProcessor()
    iterator = RobustJSONIterator(args.file_path)

    processed_count = 0
    for line_offset, event in processor.process_lines(iterator):
        processed_count += 1

        if args.stats and processed_count % 1000 == 0:
            stats = processor.get_stats()
            print(f"Processed {processed_count} events: {stats}")

    # Final statistics
    stats = processor.get_stats()
    print("\nFinal Statistics:")
    print(f"Total lines: {stats['total_lines']}")
    print(f"Single-line parsed: {stats['single_line_parsed']}")
    print(f"Multiline parsed: {stats['multiline_parsed']}")
    print(f"Repaired parsed: {stats['repaired_parsed']}")
    print(f"DLQ sent: {stats['dlq_sent']}")
    print(
        f"Success rate: {((stats['single_line_parsed'] + stats['multiline_parsed'] + stats['repaired_parsed']) / max(stats['total_lines'], 1)) * 100:.1f}%"
    )


if __name__ == "__main__":
    main()
