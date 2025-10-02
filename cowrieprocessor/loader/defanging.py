"""Command defanging utilities for safe command analysis.

This module provides intelligent command defanging that preserves investigative
value while preventing accidental execution of dangerous commands.
"""

from __future__ import annotations

import re
from typing import Dict, List, Set, Tuple


class CommandDefanger:
    """Intelligent command defanging that preserves investigative data.

    This class provides sophisticated defanging that:
    1. Preserves original commands for analysis
    2. Creates safe versions that prevent execution
    3. Categorizes commands by risk level
    4. Applies appropriate defanging based on command type
    """

    # Safe commands that don't need defanging
    SAFE_COMMANDS: Set[str] = {
        "ls",
        "pwd",
        "whoami",
        "id",
        "date",
        "uptime",
        "df",
        "free",
        "ps",
        "top",
        "htop",
        "cat",
        "head",
        "tail",
        "grep",
        "find",
        "locate",
        "which",
        "whereis",
        "type",
        "help",
        "man",
        "info",
        "history",
        "echo",
        "print",
        "printf",
        "env",
        "set",
        "unset",
        "alias",
        "cd",
        "dir",
        "tree",
        "file",
        "stat",
        "wc",
        "sort",
        "uniq",
        "cut",
        "awk",
        "sed",
        "tr",
        "rev",
        "tac",
        "less",
        "more",
    }

    # Commands that modify files but are relatively safe
    MODERATE_COMMANDS: Set[str] = {
        "mkdir",
        "rmdir",
        "touch",
        "chmod",
        "chown",
        "ln",
        "cp",
        "mv",
        "tar",
        "zip",
        "unzip",
        "gzip",
        "gunzip",
        "bzip2",
        "bunzip2",
        "rsync",
        "scp",
        "sftp",
        "ftp",
        "telnet",
        "ssh",
        "ping",
        "traceroute",
    }

    # High-risk commands that need aggressive defanging
    DANGEROUS_COMMANDS: Set[str] = {
        "rm",
        "del",
        "format",
        "fdisk",
        "mkfs",
        "dd",
        "shred",
        "wipe",
        "bash",
        "sh",
        "zsh",
        "csh",
        "tcsh",
        "ksh",
        "fish",
        "dash",
        "python",
        "python3",
        "perl",
        "ruby",
        "node",
        "php",
        "java",
        "curl",
        "wget",
        "nc",
        "netcat",
        "ncat",
        "socat",
        "telnet",
        "ssh",
        "scp",
        "rsync",
        "ftp",
        "sftp",
        "wget",
        "curl",
        "aria2c",
        "powershell",
        "cmd",
        "powershell.exe",
        "cmd.exe",
        "rundll32",
        "reg",
        "regedit",
        "gpedit",
        "msconfig",
        "services",
        "taskmgr",
        "schtasks",
        "at",
        "wmic",
        "wscript",
        "cscript",
        "certutil",
        "bitsadmin",
        "vssadmin",
        "wevtutil",
        "bcdedit",
        "diskpart",
    }

    # URL patterns for defanging
    URL_PATTERNS: List[Tuple[str, str]] = [
        (r'https://', 'hxxps://'),
        (r'http://', 'hxxp://'),
        (r'ftp://', 'fxp://'),
        (r'ftps://', 'fxps://'),
        (r'sftp://', 'sfxp://'),
        (r'file://', 'fxle://'),
    ]

    # Dangerous patterns that need defanging
    DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
        (r'&&', '[AND]'),
        (r'\|\|', '[OR]'),
        (r'\|', '[PIPE]'),
        (r';', '[SC]'),
        (r'`([^`]+)`', r'[BACKTICK] \1 [BACKTICK]'),
        (r'\$\(([^)]+)\)', r'[SUBSHELL] \1 [SUBSHELL]'),
        (r'<([^>]+)>', r'[REDIRECT] \1 [REDIRECT]'),
        (r'>>', '[APPEND]'),
        (r'>', '[OUTPUT]'),
        (r'2>&1', '[STDERR]'),
    ]

    # File paths that suggest malicious activity
    SUSPICIOUS_PATHS: List[str] = [
        '/tmp/',
        '/var/tmp/',
        '/dev/shm/',
        '/proc/',
        '/sys/',
        'C:\\temp\\',
        'C:\\windows\\temp\\',
        '%TEMP%',
        '%TMP%',
        '/root/',
        '/home/',
        'C:\\Users\\',
        'C:\\ProgramData\\',
    ]

    def __init__(self) -> None:
        """Initialize the command defanger."""
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for performance."""
        self._url_patterns = [(re.compile(pattern), replacement) for pattern, replacement in self.URL_PATTERNS]
        self._dangerous_patterns = [
            (re.compile(pattern), replacement) for pattern, replacement in self.DANGEROUS_PATTERNS
        ]
        self._suspicious_paths = [re.compile(re.escape(path), re.IGNORECASE) for path in self.SUSPICIOUS_PATHS]

    def analyze_command(self, command: str) -> Dict[str, any]:
        """Analyze a command and determine its risk level and defanging strategy.

        Args:
            command: The command string to analyze

        Returns:
            Dictionary containing analysis results:
            - risk_level: 'safe', 'moderate', 'dangerous'
            - command_type: Type of command detected
            - needs_defanging: Whether defanging is required
            - defanging_strategy: Strategy to use for defanging
        """
        if not command or not isinstance(command, str) or not command.strip():
            return {
                'risk_level': 'safe',
                'command_type': 'empty',
                'needs_defanging': False,
                'defanging_strategy': 'none',
            }

        # Extract the base command (first word)
        base_command = command.strip().split()[0].lower() if command.strip() else ''

        # Determine risk level
        if base_command in self.SAFE_COMMANDS:
            risk_level = 'safe'
            command_type = 'safe_command'
            needs_defanging = False
            strategy = 'none'
        elif base_command in self.MODERATE_COMMANDS:
            risk_level = 'moderate'
            command_type = 'moderate_command'
            needs_defanging = True
            strategy = 'moderate'
        elif base_command in self.DANGEROUS_COMMANDS:
            risk_level = 'dangerous'
            command_type = 'dangerous_command'
            needs_defanging = True
            strategy = 'aggressive'
        else:
            # Unknown command - check for dangerous patterns
            if self._has_dangerous_patterns(command):
                risk_level = 'dangerous'
                command_type = 'unknown_dangerous'
                needs_defanging = True
                strategy = 'aggressive'
            else:
                risk_level = 'moderate'
                command_type = 'unknown_command'
                needs_defanging = True
                strategy = 'moderate'

        # Override risk level if command has dangerous patterns (even if base command is safe)
        if risk_level == 'safe' and self._has_dangerous_patterns(command):
            risk_level = 'moderate'
            needs_defanging = True
            strategy = 'moderate'

        return {
            'risk_level': risk_level,
            'command_type': command_type,
            'needs_defanging': needs_defanging,
            'defanging_strategy': strategy,
        }

    def _has_dangerous_patterns(self, command: str) -> bool:
        """Check if command contains dangerous patterns."""
        command_lower = command.lower()

        # Check for suspicious paths
        for pattern in self._suspicious_paths:
            if pattern.search(command_lower):
                return True

        # Check for dangerous command patterns
        for pattern, _ in self._dangerous_patterns:
            if pattern.search(command):
                return True

        # Check for URLs
        for pattern, _ in self._url_patterns:
            if pattern.search(command):
                return True

        return False

    def defang_command(self, command: str, strategy: str = 'auto') -> str:
        """Defang a command to prevent execution while preserving readability.

        Args:
            command: The command to defang
            strategy: Defanging strategy ('none', 'moderate', 'aggressive', 'auto')

        Returns:
            Defanged version of the command
        """
        if not command or not isinstance(command, str):
            return command

        if strategy == 'auto':
            analysis = self.analyze_command(command)
            strategy = analysis['defanging_strategy']

        if strategy == 'none':
            return command

        defanged = command

        # Apply URL defanging
        for pattern, replacement in self._url_patterns:
            defanged = pattern.sub(replacement, defanged)

        # Apply dangerous pattern defanging
        for pattern, replacement in self._dangerous_patterns:
            defanged = pattern.sub(replacement, defanged)

        if strategy == 'aggressive':
            # For aggressive defanging, defang all dangerous command names
            parts = defanged.split()
            for i, part in enumerate(parts):
                if part.lower() in self.DANGEROUS_COMMANDS:
                    parts[i] = self._defang_command_name(part.lower())
            defanged = ' '.join(parts)

        return defanged.strip()

    def _defang_command_name(self, command_name: str) -> str:
        """Defang a command name to prevent execution.

        Args:
            command_name: The command name to defang

        Returns:
            Defanged command name
        """
        # Common defanging patterns for command names
        defanging_map = {
            'bash': 'bxsh',
            'sh': 'sx',
            'python': 'pythxn',
            'python3': 'pythxn3',
            'perl': 'pxrl',
            'curl': 'cxrl',
            'wget': 'wxgt',
            'nc': 'nx',
            'netcat': 'nxcat',
            'rm': 'rx',
            'del': 'dxl',
            'format': 'fxrmat',
            'dd': 'dx',
            'powershell': 'pxwershell',
            'cmd': 'cxd',
            'rundll32': 'rxndll32',
            'reg': 'rxg',
            'regedit': 'rxgdit',
            'wmic': 'wxic',
            'wscript': 'wxcript',
            'cscript': 'cxript',
            'certutil': 'cxrtutil',
            'bitsadmin': 'bxtsadmin',
            'vssadmin': 'vxsadmin',
            'wevtutil': 'wxvtutil',
            'bcdedit': 'bxdxt',
            'diskpart': 'dxskpart',
        }

        return defanging_map.get(command_name.lower(), command_name)

    def create_safe_command(self, command: str) -> str:
        """Create a safe version of a command that can be displayed without risk.

        This method creates a version that:
        1. Prevents accidental execution
        2. Preserves investigative value
        3. Clearly indicates it's been defanged

        Args:
            command: The original command

        Returns:
            Safe version with defang prefix
        """
        analysis = self.analyze_command(command)

        if not analysis['needs_defanging']:
            return command

        defanged = self.defang_command(command, analysis['defanging_strategy'])

        # Add defang prefix to make it clear this is a safe version
        prefix = f"[defang:{analysis['risk_level']}]"
        return f"{prefix} {defanged}"

    def extract_command_components(self, command: str) -> Dict[str, str]:
        """Extract components of a command for analysis.

        Args:
            command: The command to analyze

        Returns:
            Dictionary with extracted components:
            - base_command: The main command
            - arguments: Command arguments
            - flags: Command flags
            - paths: File paths referenced
            - urls: URLs referenced
        """
        if not command or not isinstance(command, str):
            return {'base_command': '', 'arguments': '', 'flags': '', 'paths': '', 'urls': ''}

        parts = command.strip().split()
        base_command = parts[0] if parts else ''

        # Extract flags (items starting with -)
        flags = [part for part in parts[1:] if part.startswith('-')]

        # Extract URLs
        urls = []
        for pattern, _ in self._url_patterns:
            matches = pattern.findall(command)
            urls.extend(matches)

        # Extract file paths (simplified heuristic)
        paths = []
        for part in parts[1:]:
            if ('/' in part or '\\' in part) and not part.startswith('-'):
                paths.append(part)

        # Remaining arguments
        arguments = [part for part in parts[1:] if not part.startswith('-') and part not in paths]

        return {
            'base_command': base_command,
            'arguments': ' '.join(arguments),
            'flags': ' '.join(flags),
            'paths': ' '.join(paths),
            'urls': ' '.join(urls),
        }


def defang_url(url: str) -> str:
    """Defang a URL to prevent accidental clicking.

    Args:
        url: The URL to defang

    Returns:
        Defanged URL
    """
    if not url or not isinstance(url, str):
        return url

    defanged = url
    for pattern, replacement in CommandDefanger.URL_PATTERNS:
        defanged = re.sub(pattern, replacement, defanged)

    return defanged


def is_safe_command(command: str) -> bool:
    """Check if a command is considered safe for display.

    Args:
        command: The command to check

    Returns:
        True if the command is safe, False otherwise
    """
    if not command or not isinstance(command, str):
        return True

    defanger = CommandDefanger()
    analysis = defanger.analyze_command(command)
    return analysis['risk_level'] == 'safe'


def get_command_risk_score(command: str) -> int:
    """Calculate a risk score for a command (0-100).

    Args:
        command: The command to score

    Returns:
        Risk score from 0 (safe) to 100 (very dangerous)
    """
    if not command or not isinstance(command, str):
        return 0

    defanger = CommandDefanger()
    analysis = defanger.analyze_command(command)

    # Base scores by risk level
    base_scores = {'safe': 0, 'moderate': 30, 'dangerous': 70}

    score = base_scores.get(analysis['risk_level'], 50)

    # Add points for dangerous patterns
    if defanger._has_dangerous_patterns(command):
        score += 20

    return min(score, 100)
