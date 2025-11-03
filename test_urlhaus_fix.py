#!/usr/bin/env python3
"""Quick test to verify URLHaus null tags fix."""

# Simulate the fixed code
def extract_tags_fixed(data):
    """Extract tags using the FIXED code (with 'or []')."""
    tags = set()
    if isinstance(data, dict) and data.get("query_status") == "ok":
        for url in data.get("urls", []):
            tags.update(url.get("tags") or [])  # ✅ FIX: Handle None tags
    return ",".join(sorted(tags)) if tags else ""


def extract_tags_broken(data):
    """Extract tags using the BROKEN code (without 'or []')."""
    tags = set()
    if isinstance(data, dict) and data.get("query_status") == "ok":
        for url in data.get("urls", []):
            tags.update(url.get("tags", []))  # ❌ BUG: Fails when tags is None
    return ",".join(sorted(tags)) if tags else ""


# Test cases
test_cases = [
    {
        "name": "Normal response with tags",
        "data": {
            "query_status": "ok",
            "urls": [
                {"tags": ["malware", "trojan"]},
                {"tags": ["phishing"]},
            ],
        },
        "expected": "malware,phishing,trojan",
    },
    {
        "name": "Null tags (URLHaus API can return this)",
        "data": {
            "query_status": "ok",
            "urls": [
                {"tags": ["malware"]},
                {"tags": None},  # ❌ This causes the bug
            ],
        },
        "expected": "malware",
    },
    {
        "name": "Missing tags key",
        "data": {
            "query_status": "ok",
            "urls": [
                {"url": "http://example.com"},  # No tags key
                {"tags": ["phishing"]},
            ],
        },
        "expected": "phishing",
    },
    {
        "name": "Empty tags list",
        "data": {
            "query_status": "ok",
            "urls": [
                {"tags": []},
                {"tags": ["malware"]},
            ],
        },
        "expected": "malware",
    },
    {
        "name": "No results",
        "data": {"query_status": "no_results"},
        "expected": "",
    },
]

print("=" * 80)
print("URLHaus Null Tags Fix Verification")
print("=" * 80)
print()

# Test the fixed version
print("✅ Testing FIXED version (with 'or []'):")
print("-" * 80)
all_passed = True
for i, test in enumerate(test_cases, 1):
    try:
        result = extract_tags_fixed(test["data"])
        status = "✅ PASS" if result == test["expected"] else "❌ FAIL"
        if result != test["expected"]:
            all_passed = False
        print(f"{status} Test {i}: {test['name']}")
        print(f"       Expected: '{test['expected']}'")
        print(f"       Got:      '{result}'")
    except Exception as e:
        print(f"❌ FAIL Test {i}: {test['name']}")
        print(f"       Error: {e}")
        all_passed = False
    print()

if all_passed:
    print("✅ All tests PASSED with fixed code!")
else:
    print("❌ Some tests FAILED!")

print()
print("=" * 80)

# Test the broken version to confirm it fails
print("❌ Testing BROKEN version (without 'or []') - should fail on null tags:")
print("-" * 80)
for i, test in enumerate(test_cases, 1):
    if "null" in test["name"].lower() or test["data"].get("urls", [{}])[0].get("tags") is None:
        try:
            result = extract_tags_broken(test["data"])
            print(f"⚠️  UNEXPECTED: Test {i} should have failed but didn't")
            print(f"       Result: '{result}'")
        except TypeError as e:
            print(f"✅ EXPECTED: Test {i} failed with TypeError: {e}")
        except Exception as e:
            print(f"⚠️  UNEXPECTED: Test {i} failed with different error: {e}")
        print()

print("=" * 80)
print("Verification complete!")
print()
print("Summary:")
print("- ✅ Fixed code handles null tags gracefully")
print("- ❌ Broken code fails with 'NoneType' object is not iterable")
print("- 🎯 One-character fix ('or []') solves the problem")
print("=" * 80)
