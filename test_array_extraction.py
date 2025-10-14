"""Debug script to test array extraction."""

import re

from cowrieprocessor.loader.dlq_processor import EventStitcher


def test_array_extraction():
    """Test array extraction from malformed content."""
    # Sample content with kexAlgs array
    content = '''],
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

    print("Testing array extraction...")
    print(f"Content contains 'kexAlgs': {'kexAlgs' in content}")

    # Test the array extraction
    kex_algs = stitcher._extract_array_values(content, 'kexAlgs')

    if kex_algs:
        print(f"✅ Extracted kexAlgs: {kex_algs}")
    else:
        print("❌ Failed to extract kexAlgs")

        # Debug the regex
        pattern = '"kexAlgs":\\s*\\[([^\\]]+(?:\\n[^\\]]*)*)\\]'
        match = re.search(pattern, content, re.DOTALL)
        if match:
            print(f"Regex matched: {match.group(1)[:100]}...")
        else:
            print("Regex did not match")

            # Try simpler pattern
            simple_pattern = '"kexAlgs":\\s*\\[([^\\]]+)\\]'
            simple_match = re.search(simple_pattern, content, re.DOTALL)
            if simple_match:
                print(f"Simple regex matched: {simple_match.group(1)[:100]}...")
            else:
                print("Simple regex also failed")

    return kex_algs is not None


if __name__ == "__main__":
    success = test_array_extraction()
    print(f"\nTest result: {'PASSED' if success else 'FAILED'}")
