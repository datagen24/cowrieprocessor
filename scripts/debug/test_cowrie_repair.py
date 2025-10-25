"""Test script to verify the enhanced Cowrie repair strategies."""

import json

from cowrieprocessor.loader.dlq_processor import EventStitcher


def test_cowrie_repair():
    """Test the Cowrie-specific repair strategies."""
    # Sample malformed content from the DLQ
    malformed_content = '''],
"eventid": "cowrie.client.kex",
"hassh": "f555226df1963d1d3c09daf865abdc9a",
"hasshAlgorithms": (
    "curve25519-sha256,curve25519-sha256@libssh.org,ecdh-sha2-nistp256,"
    "ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group18-sha512,"
    "diffie-hellman-group16-sha512,diffie-hellman-group-exchange-sha256,"
    "diffie-hellman-group14-sha256,diffie-hellman-group14-sha1,"
    "diffie-hellman-group1-sha1,ext-info-c;aes256-gcm@openssh.com,"
    "aes128-gcm@openssh.com,aes256-ctr,aes192-ctr,aes128-ctr,aes256-cbc,"
    "aes192-cbc,aes128-cbc,3des-cbc;hmac-sha2-256-etm@openssh.com,"
    "hmac-sha2-512-etm@openssh.com,hmac-sha1-etm@openssh.com,hmac-sha2-256,"
    "hmac-sha2-512,hmac-sha1;none"
),
"kexAlgs": [
"curve25519-sha256",
"curve25519-sha256@libssh.org",
"ecdh-sha2-nistp256",
"ecdh-sha2-nistp384",
"ecdh-sha2-nistp521",
"diffie-hellman-group18-sha512",
"diffie-hellman-group16-sha512",
"diffie-hellman-group-exchange-sha256",
"diffie-hellman-group14-sha256",
"diffie-hellman-group14-sha1",
"diffie-hellman-group1-sha1",'''

    stitcher = EventStitcher()

    print("Testing Cowrie-specific repair...")
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
    success = test_cowrie_repair()
    print(f"\nTest result: {'PASSED' if success else 'FAILED'}")
