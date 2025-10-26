"""Test script for enhanced Cowrie repair strategies."""

import json

from cowrieprocessor.loader.dlq_processor import EventStitcher


def test_client_fragment_repair():
    """Test repair of client event fragments without eventid."""
    # Sample malformed content - just array fragments
    malformed_content = '''],
"macCS": [
"hmac-sha1",
"hmac-sha1-96",
"hmac-sha2-256",
"hmac-sha2-512",
"hmac-md5",
"hmac-md5-96",
"hmac-ripemd160",
"hmac-ripemd160@openssh.com",
"umac-64@openssh.com",
"umac-128@openssh.com",
"hmac-sha1-etm@openssh.com",
"hmac-sha1-96-etm@openssh.com",
"hmac-sha2-256-etm@openssh.com",
"hmac-sha2-512-etm@openssh.com",
"hmac-md5-etm@openssh.com",
"hmac-md5-96-etm@openssh.com",
"hmac-ripemd160-etm@openssh.com",
"umac-64-etm@openssh.com",'''

    stitcher = EventStitcher()

    print("Testing client fragment repair...")
    print(f"Original content length: {len(malformed_content)}")
    print(f"Original content preview: {malformed_content[:100]}...")

    # Test the repair
    repaired_event = stitcher.repair_event(malformed_content)

    if repaired_event:
        print("\n✅ Repair successful!")
        print(f"Repaired event: {json.dumps(repaired_event, indent=2)}")

        # Validate the event
        from cowrieprocessor.loader.cowrie_schema import CowrieEventSchema

        schema = CowrieEventSchema()
        is_valid, errors = schema.validate_event(repaired_event)

        if is_valid:
            print("\n✅ Event validation passed!")
        else:
            print(f"\n⚠️  Event validation failed: {errors}")
    else:
        print("\n❌ Repair failed")

    return repaired_event is not None


if __name__ == "__main__":
    success = test_client_fragment_repair()
    print(f"\nTest result: {'PASSED' if success else 'FAILED'}")
