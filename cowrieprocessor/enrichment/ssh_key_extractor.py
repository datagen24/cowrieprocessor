"""Extract SSH public keys from Cowrie command events."""

from __future__ import annotations

import base64
import hashlib
import re
from dataclasses import dataclass
from typing import List, Optional, Set

from ..db.models import RawEvent


@dataclass(slots=True)
class ExtractedSSHKey:
    """Represents an extracted SSH public key with metadata."""

    key_type: str  # 'ssh-rsa', 'ssh-ed25519', etc.
    key_data: str  # Base64-encoded key data
    key_comment: Optional[str]  # Optional comment
    key_full: str  # Complete key line
    key_fingerprint: str  # SSH fingerprint (SHA256)
    key_hash: str  # SHA-256 hash for deduplication
    key_bits: Optional[int]  # Key size if determinable
    extraction_method: str  # How we found it
    source_command: str  # Original command
    target_path: Optional[str]  # Target file path


class SSHKeyExtractor:
    """Extract SSH public keys from Cowrie command events.

    Identifies authorized_keys manipulation commands and extracts SSH keys
    for tracking attacker persistence mechanisms and campaign correlation.
    """

    # SSH key type patterns - match key type followed by base64 data
    SSH_KEY_TYPES = {
        'ssh-rsa': r'ssh-rsa\s+([A-Za-z0-9+/=]+)',
        'ssh-ed25519': r'ssh-ed25519\s+([A-Za-z0-9+/=]+)',
        'ecdsa-sha2-nistp256': r'ecdsa-sha2-nistp256\s+([A-Za-z0-9+/=]+)',
        'ecdsa-sha2-nistp384': r'ecdsa-sha2-nistp384\s+([A-Za-z0-9+/=]+)',
        'ecdsa-sha2-nistp521': r'ecdsa-sha2-nistp521\s+([A-Za-z0-9+/=]+)',
        'ssh-dss': r'ssh-dss\s+([A-Za-z0-9+/=]+)',
    }

    # Command patterns that inject SSH keys
    INJECTION_PATTERNS = [
        # echo "key" >> authorized_keys or > authorized_keys
        r'echo\s+["\']?(ssh-[a-z0-9-]+\s+[A-Za-z0-9+/=]+[^"\']*)["\']?\s*>>?\s*([^\s;|&]+authorized_keys\d*)',
        # cat << EOF >> authorized_keys ... EOF
        r'cat\s*<<\s*(\w+)\s*>>?\s*([^\s;|&]+authorized_keys\d*)',
        # printf "key" >> authorized_keys
        r'printf\s+["\']?(ssh-[a-z0-9-]+\s+[A-Za-z0-9+/=]+[^"\']*)["\']?\s*>>?\s*([^\s;|&]+authorized_keys\d*)',
        # tee -a authorized_keys <<< "key"
        r'tee\s+-a\s+([^\s;|&]+authorized_keys\d*).*?(ssh-[a-z0-9-]+\s+[A-Za-z0-9+/=]+)',
    ]

    # Base64 encoded key patterns (obfuscation)
    BASE64_PATTERN = re.compile(r'echo\s+([A-Za-z0-9+/=]{40,})\s*\|\s*base64\s+-d')

    def __init__(self) -> None:
        """Initialize the SSH key extractor."""
        self.compiled_patterns = {
            key_type: re.compile(pattern, re.IGNORECASE | re.DOTALL)
            for key_type, pattern in self.SSH_KEY_TYPES.items()
        }
        self.injection_patterns = [
            re.compile(pattern, re.IGNORECASE | re.DOTALL) for pattern in self.INJECTION_PATTERNS
        ]

    def extract_keys_from_command(self, command: str) -> List[ExtractedSSHKey]:
        """Extract all SSH keys from a command string.

        Args:
            command: The command string to analyze

        Returns:
            List of extracted SSH keys with metadata
        """
        keys: List[ExtractedSSHKey] = []
        seen_hashes: Set[str] = set()

        # Try heredoc patterns first (they are more specific)
        heredoc_keys = self._extract_heredoc_keys(command)
        for key in heredoc_keys:
            if key.key_hash not in seen_hashes:
                keys.append(key)
                seen_hashes.add(key.key_hash)

        # Try direct extraction patterns
        direct_keys = self._extract_direct_keys(command)
        for key in direct_keys:
            if key.key_hash not in seen_hashes:
                keys.append(key)
                seen_hashes.add(key.key_hash)

        # Try base64 encoded keys
        base64_keys = self._extract_base64_keys(command)
        for key in base64_keys:
            if key.key_hash not in seen_hashes:
                keys.append(key)
                seen_hashes.add(key.key_hash)

        return keys

    def _extract_direct_keys(self, command: str) -> List[ExtractedSSHKey]:
        """Extract directly embedded SSH keys from commands.

        Args:
            command: The command string to analyze

        Returns:
            List of extracted SSH keys
        """
        keys = []
        target_path = self._extract_target_path(command)

        for key_type, pattern in self.compiled_patterns.items():
            for match in pattern.finditer(command):
                key_data = match.group(1).strip()

                # Validate key data (should be valid base64)
                if not self._is_valid_base64(key_data):
                    continue

                # Extract the full key line (including potential comment after the key)
                # Look for text after the key data in the command
                key_full = match.group(0)
                
                # Try to find comment by looking for text after the key data
                # Pattern: key_type key_data [comment]
                full_key_pattern = re.compile(
                    rf'{re.escape(key_type)}\s+{re.escape(key_data)}\s+([^\s"\']+(?:\s+[^\s"\']+)*)',
                    re.IGNORECASE
                )
                full_match = full_key_pattern.search(command)
                if full_match:
                    comment = full_match.group(1).strip()
                    key_full = full_match.group(0)
                else:
                    comment = None

                # Calculate fingerprint and hash
                fingerprint = self._calculate_fingerprint(key_type, key_data)
                key_hash = self._calculate_hash(f"{key_type} {key_data}")

                # Determine key bits
                key_bits = self._estimate_key_bits(key_type, key_data)

                keys.append(
                    ExtractedSSHKey(
                        key_type=key_type,
                        key_data=key_data,
                        key_comment=comment,
                        key_full=key_full.strip(),
                        key_fingerprint=fingerprint,
                        key_hash=key_hash,
                        key_bits=key_bits,
                        extraction_method='direct',
                        source_command=command,
                        target_path=target_path,
                    )
                )

        return keys

    def _extract_base64_keys(self, command: str) -> List[ExtractedSSHKey]:
        """Extract base64-encoded SSH keys (obfuscation technique).

        Args:
            command: The command string to analyze

        Returns:
            List of extracted SSH keys
        """
        keys = []

        for match in self.BASE64_PATTERN.finditer(command):
            encoded = match.group(1)
            try:
                decoded = base64.b64decode(encoded).decode('utf-8', errors='ignore')
                # Recursively extract from decoded content
                decoded_keys = self._extract_direct_keys(decoded)
                for key in decoded_keys:
                    key.extraction_method = 'base64_encoded'
                    key.source_command = command
                keys.extend(decoded_keys)
            except Exception:
                # Invalid base64 or decoding error, skip
                continue

        return keys

    def _extract_heredoc_keys(self, command: str) -> List[ExtractedSSHKey]:
        """Extract keys from heredoc patterns (cat << EOF).

        Args:
            command: The command string to analyze

        Returns:
            List of extracted SSH keys
        """
        keys = []

        # Heredoc pattern: cat << EOF ... EOF or similar
        heredoc_pattern = re.compile(
            r'cat\s*<<\s*(\w+)\s*>>?\s*([^\s;|&]+authorized_keys)(.*?)(?:\1|$)', re.IGNORECASE | re.DOTALL
        )

        for match in heredoc_pattern.finditer(command):
            delimiter = match.group(1)
            target_path = match.group(2)
            content = match.group(3)

            # Extract keys from heredoc content
            heredoc_keys = self._extract_direct_keys(content)
            for key in heredoc_keys:
                key.extraction_method = 'heredoc'
                key.source_command = command
                key.target_path = target_path
            keys.extend(heredoc_keys)

        return keys

    def _extract_target_path(self, command: str) -> Optional[str]:
        """Extract the target authorized_keys path from command.

        Args:
            command: The command string to analyze

        Returns:
            The target file path or None
        """
        # Look for authorized_keys file path (including authorized_keys2, etc.)
        path_pattern = re.compile(r'([^\s;|&]+authorized_keys\d*)', re.IGNORECASE)
        match = path_pattern.search(command)
        return match.group(1) if match else None

    def _extract_comment(self, key_line: str) -> Optional[str]:
        """Extract comment from SSH key line.

        Args:
            key_line: The full SSH key line

        Returns:
            The comment portion or None
        """
        # Comments typically appear after the key data
        parts = key_line.split()
        if len(parts) > 2:
            # Join remaining parts as comment
            return ' '.join(parts[2:])
        return None

    def _is_valid_base64(self, data: str) -> bool:
        """Check if string is valid base64.

        Args:
            data: The string to validate

        Returns:
            True if valid base64, False otherwise
        """
        try:
            # SSH keys should decode without padding errors
            base64.b64decode(data, validate=True)
            return True
        except Exception:
            return False

    def _calculate_fingerprint(self, key_type: str, key_data: str) -> str:
        """Calculate SSH key fingerprint (SHA256).

        Args:
            key_type: The SSH key type
            key_data: The base64-encoded key data

        Returns:
            The SSH fingerprint in base64 format
        """
        try:
            # Decode the key data
            key_bytes = base64.b64decode(key_data)
            # Calculate SHA256 fingerprint
            fingerprint = hashlib.sha256(key_bytes).digest()
            # Encode as base64 (SSH standard)
            return base64.b64encode(fingerprint).decode('ascii').rstrip('=')
        except Exception:
            # Fallback to hash of key data
            return hashlib.sha256(key_data.encode()).hexdigest()[:43]

    def _calculate_hash(self, key_string: str) -> str:
        """Calculate deduplication hash for key.

        Args:
            key_string: The full key string (type + data)

        Returns:
            SHA-256 hash in hexadecimal format
        """
        return hashlib.sha256(key_string.encode('utf-8')).hexdigest()

    def _estimate_key_bits(self, key_type: str, key_data: str) -> Optional[int]:
        """Estimate key size from type and data length.

        Args:
            key_type: The SSH key type
            key_data: The base64-encoded key data

        Returns:
            Estimated key size in bits or None
        """
        try:
            # Decode to get byte length
            key_bytes = base64.b64decode(key_data)
            byte_length = len(key_bytes)

            # RSA key size estimation
            if key_type == 'ssh-rsa':
                # Approximate based on common sizes
                if byte_length < 300:
                    return 2048
                elif byte_length < 500:
                    return 3072
                else:
                    return 4096

            # Ed25519 is always 256 bits
            elif key_type == 'ssh-ed25519':
                return 256

            # ECDSA key sizes
            elif 'ecdsa' in key_type:
                if 'nistp256' in key_type:
                    return 256
                elif 'nistp384' in key_type:
                    return 384
                elif 'nistp521' in key_type:
                    return 521

            return None
        except Exception:
            return None

    def extract_keys_from_events(self, events: List[RawEvent]) -> List[ExtractedSSHKey]:
        """Extract SSH keys from all commands in a list of events.

        Args:
            events: List of RawEvent objects to process

        Returns:
            List of unique extracted SSH keys
        """
        all_keys = []
        seen_hashes: Set[str] = set()

        for event in events:
            # Only process command events
            if event.event_type not in {'cowrie.command.input', 'cowrie.command.success'}:
                continue

            if not event.payload:
                continue

            # Get command from payload
            command = event.payload.get('input') or event.payload.get('command', '')
            if not command:
                continue

            # Look for authorized_keys manipulation
            if 'authorized_keys' not in command.lower():
                continue

            # Extract keys from this command
            keys = self.extract_keys_from_command(command)
            for key in keys:
                if key.key_hash not in seen_hashes:
                    all_keys.append(key)
                    seen_hashes.add(key.key_hash)

        return all_keys


__all__ = ['SSHKeyExtractor', 'ExtractedSSHKey']

