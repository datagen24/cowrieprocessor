"""Defanging-aware command normalizer for semantic vectorization.

This module provides normalization that reverses defanging patterns and applies
semantic normalization for consistent command vectorization in threat detection.
"""

from __future__ import annotations

import re
from typing import Pattern


class DefangingAwareNormalizer:
    """Normalizes defanged commands back to semantic form for vectorization.

    This class handles the complete normalization pipeline:
    1. Reverses defanging patterns applied by CommandDefanger
    2. Applies semantic normalization (URLs, IPs, paths)
    3. Ensures idempotency (running twice produces same result)

    The normalization enables consistent vectorization for snowshoe spam detection
    and other ML-based threat analysis, where semantic equivalence matters more
    than exact string matching.

    Examples:
        >>> normalizer = DefangingAwareNormalizer()
        >>> normalizer.normalize("cxrl hxxp://evil.com")
        'curl [URL]'
        >>> normalizer.normalize("bxsh script.sh")
        'bash script.sh'
        >>> normalizer.normalize("rx -rf /")
        'rm -rf [PATH:1]'
    """

    # URL scheme patterns for semantic normalization
    # Exclude closing backticks, parens, and brackets to prevent consuming them
    URL_PATTERN: Pattern[str] = re.compile(r'\b(?:https?|ftp|ftps|sftp)://[^\s)`\]]+', re.IGNORECASE)

    # IP address pattern (IPv4)
    IP_PATTERN: Pattern[str] = re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b')

    # Path patterns (Unix and Windows, including paths after = like if=/dev/zero)
    PATH_PATTERN: Pattern[str] = re.compile(
        r'(?:(?:^|(?<=\s)|(?<==))(?:/[^\s]*|[A-Za-z]:[/\\][^\s]*))',
    )

    def __init__(self) -> None:
        """Initialize the defanging-aware normalizer."""
        pass

    def normalize(self, command: str) -> str:
        """Normalize a command through defanging reversal and semantic normalization.

        This is the main entry point for command normalization. It applies
        the complete normalization pipeline while maintaining idempotency.

        Args:
            command: The command string to normalize (may be defanged or normal)

        Returns:
            Normalized command with semantic placeholders

        Examples:
            >>> normalizer = DefangingAwareNormalizer()
            >>> normalizer.normalize("cxrl hxxp://evil.com")
            'curl [URL]'
            >>> normalizer.normalize("curl http://evil.com")  # Idempotent
            'curl [URL]'
            >>> normalizer.normalize("")
            ''
        """
        if not command or not command.strip():
            return ""

        # Check if already normalized (idempotency)
        if self._is_already_normalized(command):
            return command

        # Step 1: Reverse defanging patterns
        cmd = self._reverse_defanging(command)

        # Step 2: Apply semantic normalization
        cmd = self._normalize_semantically(cmd)

        return cmd.strip()

    def _reverse_defanging(self, cmd: str) -> str:
        """Reverse all defanging patterns back to executable form.

        Reverses the 6 defanging pattern categories:
        1. URL schemes (hxxp → http, etc.)
        2. Command names (bxsh → bash, etc.)
        3. Operators ([AND] → &&, etc.)
        4. Subshell markers ([SUBSHELL]...[SUBSHELL] → $(...))
        5. Backtick markers ([BACKTICK]...[BACKTICK] → `...`)
        6. Risk prefix ([defang:dangerous] → removed)

        Args:
            cmd: Command with potential defanging patterns

        Returns:
            Command with defanging patterns reversed

        Examples:
            >>> normalizer = DefangingAwareNormalizer()
            >>> normalizer._reverse_defanging("cxrl hxxp://evil.com")
            'curl http://evil.com'
            >>> normalizer._reverse_defanging("[defang:dangerous] bxsh script.sh")
            'bash script.sh'
        """
        # Pattern 6: Remove risk prefix
        cmd = re.sub(r'\[defang:\w+\]\s*', '', cmd)

        # Pattern 1: URL schemes (case-insensitive)
        cmd = re.sub(r'hxxps://', 'https://', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'hxxp://', 'http://', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'fxps://', 'ftps://', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'fxp://', 'ftp://', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'sfxp://', 'sftp://', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'fxle://', 'file://', cmd, flags=re.IGNORECASE)

        # Pattern 2: Command names (order matters - longer patterns first)
        # Must preserve word boundaries to avoid partial replacements
        # Use case-insensitive matching with re.IGNORECASE
        cmd = re.sub(r'\bpythxn3\b', 'python3', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bpythxn\b', 'python', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bpxwershell\b', 'powershell', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bbxtsadmin\b', 'bitsadmin', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bcxrtutil\b', 'certutil', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\brxndll32\b', 'rundll32', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bvxsadmin\b', 'vssadmin', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bwxvtutil\b', 'wevtutil', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bdxskpart\b', 'diskpart', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bwxcript\b', 'wscript', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bcxript\b', 'cscript', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bfxrmat\b', 'format', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\brxgdit\b', 'regedit', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bnxcat\b', 'netcat', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bbxsh\b', 'bash', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bcxrl\b', 'curl', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bwxgt\b', 'wget', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bpxrl\b', 'perl', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bwxic\b', 'wmic', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\brxg\b', 'reg', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bcxd\b', 'cmd', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bdxl\b', 'del', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\brx\b', 'rm', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bdx\b', 'dd', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bnx\b', 'nc', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bsx\b', 'sh', cmd, flags=re.IGNORECASE)
        cmd = re.sub(r'\bbxdxt\b', 'bcdedit', cmd, flags=re.IGNORECASE)

        # Pattern 3: Operators
        cmd = cmd.replace('[AND]', '&&')
        cmd = cmd.replace('[OR]', '||')
        cmd = cmd.replace('[PIPE]', '|')
        cmd = cmd.replace('[SC]', ';')
        cmd = cmd.replace('[APPEND]', '>>')
        cmd = cmd.replace('[OUTPUT]', '>')
        cmd = cmd.replace('[STDERR]', '2>&1')
        cmd = cmd.replace('[REDIRECT]', '<')

        # Pattern 4: Subshell markers
        cmd = re.sub(r'\[SUBSHELL\]\s*(.*?)\s*\[SUBSHELL\]', r'$(\1)', cmd)

        # Pattern 5: Backtick markers
        cmd = re.sub(r'\[BACKTICK\]\s*(.*?)\s*\[BACKTICK\]', r'`\1`', cmd)

        return cmd

    def _normalize_semantically(self, cmd: str) -> str:
        """Apply semantic normalization to create consistent command vectors.

        Replaces specific values with semantic placeholders:
        - URLs → [URL]
        - IP addresses → [IP]
        - File paths → [PATH:depth] where depth is directory depth

        This enables commands with different URLs/IPs/paths to map to the
        same vector for semantic similarity detection.

        Args:
            cmd: Command with reversed defanging (normal executable form)

        Returns:
            Command with semantic placeholders

        Examples:
            >>> normalizer = DefangingAwareNormalizer()
            >>> normalizer._normalize_semantically("curl http://evil.com")
            'curl [URL]'
            >>> normalizer._normalize_semantically("ping 192.168.1.1")
            'ping [IP]'
            >>> normalizer._normalize_semantically("rm -rf /tmp/malware")
            'rm -rf [PATH:2]'
        """
        # Normalize URLs first (before IPs, as URLs may contain IPs)
        cmd = self.URL_PATTERN.sub('[URL]', cmd)

        # Normalize IP addresses
        cmd = self.IP_PATTERN.sub('[IP]', cmd)

        # Normalize file paths with depth calculation
        def replace_path(match: re.Match[str]) -> str:
            path = match.group(0).strip()
            # Remove leading = if present (for cases like if=/dev/zero)
            if path.startswith('='):
                path = path[1:]
            # Count path components (split by / or \, filter empty strings)
            # For Unix: /tmp -> ['', 'tmp'] -> 1, /etc/passwd -> ['', 'etc', 'passwd'] -> 2
            # For Windows: C:\Windows -> ['C:', 'Windows'] -> 1
            separators = '/' if '/' in path else '\\'
            components = [c for c in path.split(separators) if c and c != '']
            depth = len(components)
            # Minimum depth of 1 for any path
            depth = max(1, depth)
            return f'[PATH:{depth}]'

        cmd = self.PATH_PATTERN.sub(replace_path, cmd)

        return cmd

    def _is_already_normalized(self, cmd: str) -> bool:
        """Check if command is already normalized (idempotency check).

        A command is considered normalized if it contains any semantic
        placeholders ([URL], [IP], [PATH:N]). This prevents redundant
        normalization and ensures idempotent behavior.

        Args:
            cmd: Command to check for normalization

        Returns:
            True if command appears to be already normalized

        Examples:
            >>> normalizer = DefangingAwareNormalizer()
            >>> normalizer._is_already_normalized("curl [URL]")
            True
            >>> normalizer._is_already_normalized("curl http://evil.com")
            False
            >>> normalizer._is_already_normalized("ping [IP]")
            True
        """
        # Check for semantic placeholders
        return bool('[URL]' in cmd or '[IP]' in cmd or re.search(r'\[PATH:\d+\]', cmd))
