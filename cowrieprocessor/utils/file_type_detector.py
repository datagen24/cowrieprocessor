"""File type detection utility for data ingestion pipelines.

This module provides utilities to detect the actual content type of files
and determine if they should be processed by JSON parsers.
"""

import json
import logging
import re
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


class FileTypeDetector:
    """Detects file types by examining content patterns."""

    # Patterns to identify different log types
    IPTABLES_PATTERN = re.compile(r'^\d+\s+\w+.*kernel:.*DSHIELDINPUT', re.MULTILINE)
    COWRIE_JSON_PATTERN = re.compile(r'^\s*\{.*"eventid"\s*:\s*"cowrie\.', re.MULTILINE)
    WEBHONEYPOT_JSON_PATTERN = re.compile(r'^\s*\{.*"eventid"\s*:\s*"webhoneypot\.', re.MULTILINE)
    GENERIC_JSON_PATTERN = re.compile(r'^\s*\{.*\}', re.MULTILINE)

    @classmethod
    def detect_file_type(cls, file_path: Path, sample_lines: int = 10) -> Tuple[str, str, List[str]]:
        """Detect the type of file by examining its content.

        Args:
            file_path: Path to the file to examine
            sample_lines: Number of lines to sample for detection

        Returns:
            Tuple of (file_type, confidence, sample_content)
            - file_type: 'json', 'iptables', 'unknown', 'error'
            - confidence: 'high', 'medium', 'low'
            - sample_content: List of sample lines from the file
        """
        try:
            # Open and read sample lines
            sample_content = []

            if file_path.suffix == '.bz2':
                import bz2

                with bz2.open(file_path, 'rt', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f):
                        if i >= sample_lines:
                            break
                        sample_content.append(line.strip())
            else:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    for i, line in enumerate(f):
                        if i >= sample_lines:
                            break
                        sample_content.append(line.strip())

            if not sample_content:
                return 'empty', 'high', sample_content

            # Join sample content for pattern matching
            content_text = '\n'.join(sample_content)

            # Check for iptables/kernel logs first (most specific)
            if cls.IPTABLES_PATTERN.search(content_text):
                return 'iptables', 'high', sample_content

            # Check for specific honeypot JSON types
            if cls.COWRIE_JSON_PATTERN.search(content_text):
                return 'cowrie_json', 'high', sample_content

            if cls.WEBHONEYPOT_JSON_PATTERN.search(content_text):
                return 'webhoneypot_json', 'high', sample_content

            # Check for generic JSON - try multiline first, then line-by-line
            # First, try parsing the entire content as a single JSON object (multiline JSON)
            try:
                json.loads(content_text)
                return 'json', 'high', sample_content
            except (json.JSONDecodeError, ValueError):
                pass

            # Check for multiline JSON patterns (prettified JSON objects)
            # Look for lines starting with { or ending with } which indicate JSON structure
            has_json_structure = False
            if any(line.strip().startswith('{') for line in sample_content):
                # Count lines that look like JSON structure
                json_like_lines = sum(
                    1 for line in sample_content
                    if any(pattern in line for pattern in ['{', '}', '": ', '",', '":', ': "', ': {', ': ['])
                )
                if json_like_lines >= len(sample_content) * 0.5:
                    has_json_structure = True

            if has_json_structure:
                return 'json', 'medium', sample_content

            # Fall back to line-by-line JSON parsing
            json_valid_lines = 0
            for line in sample_content:
                if line.strip():
                    try:
                        json.loads(line)
                        json_valid_lines += 1
                    except (json.JSONDecodeError, ValueError):
                        pass

            if json_valid_lines > 0:
                confidence = 'high' if json_valid_lines >= len(sample_content) * 0.8 else 'medium'
                return 'json', confidence, sample_content

            # Check if it looks like structured log data
            if any(' ' in line and len(line.split()) >= 3 for line in sample_content):
                return 'structured_log', 'medium', sample_content

            return 'unknown', 'low', sample_content

        except Exception as e:
            logger.warning(f"Error detecting file type for {file_path}: {e}")
            return 'error', 'low', []

    @classmethod
    def should_process_as_json(cls, file_path: Path, sample_lines: int = 10) -> Tuple[bool, str, str]:
        """Determine if a file should be processed as JSON.

        Args:
            file_path: Path to the file to examine
            sample_lines: Number of lines to sample for detection

        Returns:
            Tuple of (should_process, file_type, reason)
        """
        file_type, confidence, sample_content = cls.detect_file_type(file_path, sample_lines)

        if file_type in ['cowrie_json', 'webhoneypot_json']:
            return True, file_type, f"Valid {file_type} content detected"

        if file_type == 'json' and confidence in ['high', 'medium']:
            return True, file_type, f"Valid JSON content detected (confidence: {confidence})"

        if file_type == 'iptables':
            return False, file_type, "iptables/kernel log detected - should be processed separately"

        if file_type == 'structured_log':
            return False, file_type, "Structured log detected - not JSON format"

        if file_type == 'empty':
            return False, file_type, "Empty file"

        if file_type == 'error':
            return False, file_type, "Error reading file"

        return False, file_type, f"Unknown content type (confidence: {confidence})"

    @classmethod
    def suggest_correct_directory(cls, file_path: Path, file_type: str) -> Optional[Path]:
        """Suggest the correct directory for a mislocated file.

        Args:
            file_path: Current path of the file
            file_type: Detected file type

        Returns:
            Suggested correct path, or None if no suggestion
        """
        if file_type == 'iptables':
            # Move to iptables directory
            parent = file_path.parent
            if 'NSM' in str(parent):
                # Replace the last directory component with 'iptables'
                parts = list(parent.parts)
                if len(parts) > 1:
                    parts[-1] = 'iptables'
                    return Path(*parts) / file_path.name

        return None


def detect_file_type(file_path: Path, sample_lines: int = 10) -> Tuple[str, str, List[str]]:
    """Convenience function for file type detection."""
    return FileTypeDetector.detect_file_type(file_path, sample_lines)


def should_process_as_json(file_path: Path, sample_lines: int = 10) -> Tuple[bool, str, str]:
    """Convenience function to check if file should be processed as JSON."""
    return FileTypeDetector.should_process_as_json(file_path, sample_lines)
