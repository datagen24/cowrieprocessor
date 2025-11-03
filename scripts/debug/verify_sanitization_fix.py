#!/usr/bin/env python3
"""Verification script for PostgreSQL JSON escape sequence detection bug fix.

This script demonstrates the bug where is_safe_for_postgres_json() was missing
JSON Unicode escape sequences (like \u0000) that appear when PostgreSQL casts
JSONB to text.

Bug: https://github.com/datagen24/cowrieprocessor/issues/XXX
"""

from cowrieprocessor.utils.unicode_sanitizer import UnicodeSanitizer


def main() -> int:
    """Verify the sanitization fix detects both byte and escape sequence patterns."""
    print("=" * 80)
    print("VERIFICATION: PostgreSQL JSON Escape Sequence Detection")
    print("=" * 80)
    print()

    # Simulate what PostgreSQL payload::text returns
    test_cases = [
        # (description, text, should_be_safe)
        ("Normal JSON", '{"username": "test"}', True),
        ("Safe whitespace (tab)", '{"data": "\\u0009"}', True),
        ("Safe whitespace (newline)", '{"data": "\\u000a"}', True),
        ("Safe whitespace (CR)", '{"data": "\\u000d"}', True),
        ("NULL byte escape", '{"username": "\\u0000test"}', False),
        ("SOH control char", '{"data": "attack\\u0001data"}', False),
        ("Backspace char", '{"cmd": "echo\\u0008test"}', False),
        ("DEL character", '{"value": "test\\u007f"}', False),
        ("Actual null byte", '{"data": "test\x00byte"}', False),
        ("Mixed patterns", 'text\x00with byte and \\u0001escape', False),
    ]

    print("Testing Detection Logic:")
    print("-" * 80)

    passed = 0
    failed = 0

    for description, text, should_be_safe in test_cases:
        is_safe = UnicodeSanitizer.is_safe_for_postgres_json(text)
        status = "✅ PASS" if is_safe == should_be_safe else "❌ FAIL"

        if is_safe == should_be_safe:
            passed += 1
        else:
            failed += 1

        print(f"{status} | {description:30s} | Expected: {str(should_be_safe):5s} | Got: {str(is_safe):5s}")
        if is_safe != should_be_safe:
            print(f"       | Text preview: {repr(text[:50])}")

    print("-" * 80)
    print(f"Results: {passed} passed, {failed} failed")
    print()

    if failed == 0:
        print("✅ All tests passed! The bug is fixed.")
        print()
        print("The sanitizer now correctly detects:")
        print("  1. Actual control character bytes (\\x00, \\x01, etc.)")
        print("  2. JSON Unicode escape sequences (\\u0000, \\u0001, etc.)")
        print()
        print("This means 'cowrie-db sanitize' will now properly identify and fix")
        print("records with problematic Unicode characters in PostgreSQL JSONB fields.")
    else:
        print("❌ Some tests failed! The fix may not be working correctly.")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
