"""Unit tests for SSH key extraction from Cowrie commands."""

from __future__ import annotations

import base64

import pytest

from cowrieprocessor.db.models import RawEvent
from cowrieprocessor.enrichment.ssh_key_extractor import SSHKeyExtractor

# Sample SSH keys for testing (valid base64 format - random data for testing)
SAMPLE_RSA_KEY = "RuLDinPc4KQAhfl8qtDqql2n6OfzvvLH0TncExH1DvFenNj2ks9vIqyK4s3cPDxIs02HrT915vIM28RXzBI8S7r2D3Gqf1bLZuVSNYSkpb4GhgE7XOvjIcxZNTV0nEOuNZmbAYftpQGEK/i3RdoKXmZlj3EiZX4sXQnfDCt3gIDr8tuamwVDYEeFjJJDD/d6TZniVw9Z6l0GJ+BAj5S5ecb19qoyoM4XvFp1LyyQxJr2Ew+gwRqYl9RWa2Ck/X8LEYvXAk1Njg0="
SAMPLE_ED25519_KEY = "RarSX0dYSvElGT0cJi7CcnugS1aqRv/8tEj9HS5GiP1vTRCVBgxteUwd8ozUs82qxyP0"
SAMPLE_ECDSA_KEY = "RGFtden1RYN3BT/389mQOeKqjN8o1mlxxltzKJ+JXagOdIjLlIRuwwUpiI6bqqfR+oM3P8HoulItMkqMKEW2GRsi59Iis8PwP0IsydPWAE/VpnRPW6ZZPr7etN9p2P+L//St5A=="


class TestSSHKeyExtractor:
    """Test suite for SSHKeyExtractor."""

    def test_init(self) -> None:
        """Test extractor initialization."""
        extractor = SSHKeyExtractor()
        assert extractor is not None
        assert len(extractor.compiled_patterns) > 0
        assert len(extractor.injection_patterns) > 0

    def test_extract_direct_echo_append(self) -> None:
        """Test extraction from direct echo append command."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY} user@host" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_type == 'ssh-rsa'
        assert keys[0].key_data == SAMPLE_RSA_KEY
        assert keys[0].extraction_method == 'direct'
        assert keys[0].target_path == '~/.ssh/authorized_keys'

    def test_extract_direct_echo_overwrite(self) -> None:
        """Test extraction from direct echo overwrite command."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-ed25519 {SAMPLE_ED25519_KEY}" > /root/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_type == 'ssh-ed25519'
        assert keys[0].extraction_method == 'direct'

    def test_extract_heredoc_pattern(self) -> None:
        """Test extraction from heredoc pattern."""
        extractor = SSHKeyExtractor()
        command = f'''cat << EOF >> ~/.ssh/authorized_keys
ssh-rsa {SAMPLE_RSA_KEY} attacker@evil
EOF'''

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_type == 'ssh-rsa'
        assert keys[0].extraction_method == 'heredoc'

    def test_extract_base64_encoded(self) -> None:
        """Test extraction from base64-encoded key."""
        extractor = SSHKeyExtractor()
        # Encode a key injection command
        encoded_command = f'ssh-rsa {SAMPLE_RSA_KEY} user@host'
        encoded = base64.b64encode(encoded_command.encode()).decode()
        command = f'echo {encoded} | base64 -d >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_type == 'ssh-rsa'
        assert keys[0].extraction_method == 'base64_encoded'

    def test_extract_multiple_keys(self) -> None:
        """Test extraction of multiple keys from heredoc."""
        extractor = SSHKeyExtractor()
        command = f'''cat << EOF >> ~/.ssh/authorized_keys
ssh-rsa {SAMPLE_RSA_KEY} user1@host
ssh-ed25519 {SAMPLE_ED25519_KEY} user2@host
EOF'''

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 2
        key_types = {key.key_type for key in keys}
        assert 'ssh-rsa' in key_types
        assert 'ssh-ed25519' in key_types

    def test_extract_with_comment(self) -> None:
        """Test extraction preserves key comment."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY} attacker@evil.com" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_comment is not None
        assert 'attacker@evil.com' in keys[0].key_comment

    def test_no_keys_in_command(self) -> None:
        """Test extraction returns empty list for commands without keys."""
        extractor = SSHKeyExtractor()
        command = 'ls -la /root/.ssh/'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 0

    def test_invalid_base64_ignored(self) -> None:
        """Test that invalid base64 keys are ignored."""
        extractor = SSHKeyExtractor()
        command = 'echo "ssh-rsa INVALID_BASE64!!!" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 0

    def test_deduplication_hash(self) -> None:
        """Test that key hash is generated for deduplication."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_hash is not None
        assert len(keys[0].key_hash) == 64  # SHA-256 hex

    def test_fingerprint_calculation(self) -> None:
        """Test that SSH fingerprint is calculated."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_fingerprint is not None
        assert len(keys[0].key_fingerprint) > 0

    def test_key_bits_estimation_rsa(self) -> None:
        """Test RSA key size estimation."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_bits is not None
        assert keys[0].key_bits in [2048, 3072, 4096]

    def test_key_bits_estimation_ed25519(self) -> None:
        """Test Ed25519 key size is always 256."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-ed25519 {SAMPLE_ED25519_KEY}" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_bits == 256

    def test_extract_from_events(self) -> None:
        """Test extraction from RawEvent objects."""
        extractor = SSHKeyExtractor()

        # Create mock events
        event1 = RawEvent(
            source='/var/log/cowrie/cowrie.json',
            payload={
                'eventid': 'cowrie.command.input',
                'input': f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/authorized_keys',
            },
        )
        event1.event_type = 'cowrie.command.input'

        event2 = RawEvent(
            source='/var/log/cowrie/cowrie.json',
            payload={
                'eventid': 'cowrie.command.input',
                'input': 'ls -la',
            },
        )
        event2.event_type = 'cowrie.command.input'

        keys = extractor.extract_keys_from_events([event1, event2])

        assert len(keys) == 1
        assert keys[0].key_type == 'ssh-rsa'

    def test_extract_from_events_deduplication(self) -> None:
        """Test that duplicate keys are deduplicated."""
        extractor = SSHKeyExtractor()

        # Create events with same key
        event1 = RawEvent(
            source='/var/log/cowrie/cowrie.json',
            payload={
                'eventid': 'cowrie.command.input',
                'input': f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/authorized_keys',
            },
        )
        event1.event_type = 'cowrie.command.input'

        event2 = RawEvent(
            source='/var/log/cowrie/cowrie.json',
            payload={
                'eventid': 'cowrie.command.input',
                'input': f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> /root/.ssh/authorized_keys',
            },
        )
        event2.event_type = 'cowrie.command.input'

        keys = extractor.extract_keys_from_events([event1, event2])

        # Should only return one key despite two commands
        assert len(keys) == 1

    def test_extract_ecdsa_key(self) -> None:
        """Test extraction of ECDSA key."""
        extractor = SSHKeyExtractor()
        command = f'echo "ecdsa-sha2-nistp256 {SAMPLE_ECDSA_KEY}" >> ~/.ssh/authorized_keys'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1
        assert keys[0].key_type == 'ecdsa-sha2-nistp256'
        assert keys[0].key_bits == 256

    def test_case_insensitive_authorized_keys(self) -> None:
        """Test that authorized_keys matching is case-insensitive."""
        extractor = SSHKeyExtractor()
        command = f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> ~/.ssh/AUTHORIZED_KEYS'

        keys = extractor.extract_keys_from_command(command)

        assert len(keys) == 1

    def test_various_path_formats(self) -> None:
        """Test extraction with various authorized_keys path formats."""
        extractor = SSHKeyExtractor()
        paths = [
            '~/.ssh/authorized_keys',
            '/root/.ssh/authorized_keys',
            '/home/user/.ssh/authorized_keys',
            '~/.ssh/authorized_keys2',
        ]

        for path in paths:
            command = f'echo "ssh-rsa {SAMPLE_RSA_KEY}" >> {path}'
            keys = extractor.extract_keys_from_command(command)
            assert len(keys) == 1, f"Failed to extract from path: {path}"
            assert keys[0].target_path == path


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
