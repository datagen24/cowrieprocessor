"""Unicode sanitization utilities for handling control characters in JSON data.

This module provides centralized utilities for sanitizing Unicode control characters
that can cause issues with PostgreSQL JSON processing and database operations.
"""

import json
import logging
import re
from typing import Any, Dict, Union

logger = logging.getLogger(__name__)


class UnicodeSanitizer:
    """Centralized Unicode sanitization for JSON and text data."""

    # Control characters that cause issues with PostgreSQL JSON
    # \u0000-\u001F (C0 controls) and \u007F-\u009F (DEL and C1 controls)
    CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x1F\x7F-\x9F]')
    
    # More restrictive pattern for critical fields that must be clean
    STRICT_CONTROL_CHAR_PATTERN = re.compile(r'[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]')
    
    # Characters that are safe to preserve
    SAFE_WHITESPACE = {'\t', '\n', '\r', ' '}  # tab, newline, carriage return, space

    @classmethod
    def sanitize_unicode_string(
        cls, 
        text: str, 
        strict: bool = False,
        replacement: str = '',
        preserve_whitespace: bool = True
    ) -> str:
        """Sanitize Unicode control characters from a string.
        
        Args:
            text: Input string to sanitize
            strict: If True, use stricter control character filtering
            replacement: String to replace control characters with
            preserve_whitespace: If True, preserve safe whitespace characters
            
        Returns:
            Sanitized string with control characters removed or replaced
        """
        if not isinstance(text, str):
            return text
            
        if not text:
            return text
            
        pattern = cls.STRICT_CONTROL_CHAR_PATTERN if strict else cls.CONTROL_CHAR_PATTERN
        
        def replace_char(match):
            char = match.group(0)
            if preserve_whitespace and char in cls.SAFE_WHITESPACE:
                return char
            return replacement
            
        sanitized = pattern.sub(replace_char, text)
        
        # Log if we found and removed control characters
        if sanitized != text:
            control_chars_found = []
            for char in text:
                if pattern.match(char) and (not preserve_whitespace or char not in cls.SAFE_WHITESPACE):
                    control_chars_found.append(f"\\u{ord(char):04X}")
            
            logger.debug(
                f"Sanitized Unicode control characters: {', '.join(set(control_chars_found))}"
            )
            
        return sanitized

    @classmethod
    def sanitize_json_string(cls, json_str: str) -> str:
        """Sanitize JSON string by removing problematic Unicode control characters.
        
        This method specifically targets control characters that cause PostgreSQL
        JSON processing errors while preserving the JSON structure.
        
        Args:
            json_str: Raw JSON string that may contain control characters
            
        Returns:
            Sanitized JSON string safe for PostgreSQL processing
        """
        if not isinstance(json_str, str):
            return json_str
            
        # First, try to parse and re-serialize to validate JSON structure
        try:
            parsed = json.loads(json_str)
            # Recursively sanitize all string values in the JSON
            sanitized_obj = cls._sanitize_json_object(parsed)
            return json.dumps(sanitized_obj, ensure_ascii=False, separators=(',', ':'))
        except json.JSONDecodeError:
            # If JSON is malformed, try JSON repair strategies first
            logger.warning("Malformed JSON detected, attempting repair strategies")
            
            # Try JSON repair strategies
            try:
                from ..loader.dlq_processor import JSONRepairStrategies
                repaired_json = JSONRepairStrategies.repair_json(json_str)
                
                # Test if repair was successful
                json.loads(repaired_json)
                logger.info("JSON repair successful")
                return repaired_json
                
            except (json.JSONDecodeError, ImportError):
                # If repair fails, fall back to string-level sanitization
                logger.warning("JSON repair failed, applying string-level sanitization")
                return cls.sanitize_unicode_string(json_str, strict=True, replacement='')

    @classmethod
    def _sanitize_json_object(cls, obj: Any) -> Any:
        """Recursively sanitize Unicode control characters in JSON object.
        
        Args:
            obj: JSON object (dict, list, or primitive)
            
        Returns:
            Sanitized JSON object with control characters removed
        """
        if isinstance(obj, dict):
            return {
                cls._sanitize_json_object(key): cls._sanitize_json_object(value)
                for key, value in obj.items()
            }
        elif isinstance(obj, list):
            return [cls._sanitize_json_object(item) for item in obj]
        elif isinstance(obj, str):
            # Sanitize string values, preserving safe whitespace
            return cls.sanitize_unicode_string(obj, strict=False, replacement='', preserve_whitespace=True)
        else:
            return obj

    @classmethod
    def sanitize_filename(cls, filename: str) -> str:
        """Sanitize filename by removing dangerous control characters.
        
        Args:
            filename: Raw filename that may contain control characters
            
        Returns:
            Sanitized filename safe for filesystem operations
        """
        if not filename:
            return ""
            
        # Remove null bytes and other dangerous control characters
        sanitized = cls.sanitize_unicode_string(
            filename, 
            strict=True, 
            replacement='',
            preserve_whitespace=False  # Don't preserve whitespace in filenames
        ).strip()
        
        # Remove path traversal attempts
        sanitized = sanitized.replace("../", "").replace("..\\", "")
        
        # Limit length to prevent issues
        if len(sanitized) > 512:
            sanitized = sanitized[:512]
            
        return sanitized

    @classmethod
    def sanitize_url(cls, url: str) -> str:
        """Sanitize URL by removing control characters.
        
        Args:
            url: Raw URL that may contain control characters
            
        Returns:
            Sanitized URL safe for HTTP operations
        """
        if not url:
            return ""
            
        # Remove control characters, preserving safe whitespace
        sanitized = cls.sanitize_unicode_string(
            url,
            strict=True,
            replacement='',
            preserve_whitespace=False  # URLs shouldn't have whitespace
        ).strip()
        
        # Limit length
        if len(sanitized) > 1024:
            sanitized = sanitized[:1024]
            
        return sanitized

    @classmethod
    def sanitize_command(cls, command: str) -> str:
        """Sanitize command string by removing control characters.
        
        Args:
            command: Raw command string that may contain control characters
            
        Returns:
            Sanitized command string safe for processing
        """
        if not command:
            return ""
            
        # Use less strict sanitization for commands to preserve formatting
        sanitized = cls.sanitize_unicode_string(
            command,
            strict=False,
            replacement='',
            preserve_whitespace=True  # Preserve tabs, newlines in commands
        )
        
        return sanitized

    @classmethod
    def is_safe_for_postgres_json(cls, text: str) -> bool:
        """Check if text is safe for PostgreSQL JSON processing.
        
        Args:
            text: Text to check for problematic characters
            
        Returns:
            True if text is safe for PostgreSQL JSON, False otherwise
        """
        if not isinstance(text, str):
            return True
            
        # Check for the most problematic characters that cause PostgreSQL errors
        dangerous_chars = ['\x00', '\x01', '\x02', '\x03', '\x04', '\x05', '\x06', '\x07',
                          '\x08', '\x0B', '\x0C', '\x0E', '\x0F', '\x10', '\x11', '\x12',
                          '\x13', '\x14', '\x15', '\x16', '\x17', '\x18', '\x19', '\x1A',
                          '\x1B', '\x1C', '\x1D', '\x1E', '\x1F', '\x7F']
        
        return not any(char in text for char in dangerous_chars)

    @classmethod
    def validate_and_sanitize_payload(cls, payload: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Validate and sanitize JSON payload for database storage.
        
        Args:
            payload: JSON payload as string or dict
            
        Returns:
            Sanitized payload as dict
            
        Raises:
            ValueError: If payload cannot be parsed or sanitized
        """
        if isinstance(payload, str):
            try:
                # First sanitize the JSON string
                sanitized_json = cls.sanitize_json_string(payload)
                parsed_payload = json.loads(sanitized_json)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON payload: {e}")
        elif isinstance(payload, dict):
            parsed_payload = cls._sanitize_json_object(payload)
        else:
            raise ValueError(f"Invalid payload type: {type(payload)}")
            
        # Validate that the payload is safe for PostgreSQL
        payload_str = json.dumps(parsed_payload, ensure_ascii=False)
        if not cls.is_safe_for_postgres_json(payload_str):
            logger.warning("Payload contains characters unsafe for PostgreSQL, applying additional sanitization")
            # Apply more aggressive sanitization
            parsed_payload = cls._sanitize_json_object(parsed_payload)
            
        return parsed_payload


def sanitize_unicode_string(text: str, **kwargs) -> str:
    """Convenience function for Unicode string sanitization."""
    return UnicodeSanitizer.sanitize_unicode_string(text, **kwargs)


def sanitize_json_payload(payload: Union[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Convenience function for JSON payload sanitization."""
    return UnicodeSanitizer.validate_and_sanitize_payload(payload)


def is_safe_for_database(text: str) -> bool:
    """Convenience function to check if text is safe for database operations."""
    return UnicodeSanitizer.is_safe_for_postgres_json(text)

