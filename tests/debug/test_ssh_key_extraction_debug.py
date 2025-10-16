"""Debug test for SSH key extraction to verify patterns work correctly."""

from __future__ import annotations

import logging

from cowrieprocessor.enrichment.ssh_key_extractor import SSHKeyExtractor


def test_extractor_on_sample_commands() -> None:
    """Test SSH key extractor with sample commands to verify extraction patterns."""
    logging.basicConfig(level=logging.DEBUG)
    extractor = SSHKeyExtractor()

    test_commands = [
        'echo "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQC7vbqajDhA... user@example.com" >> ~/.ssh/authorized_keys',
        (
            'printf "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMu6z4vZc9b4yQ0rQW9s4Jb0m7xZQ8wLqW+4wK3tqB8S test@host" '
            '>> /root/.ssh/authorized_keys'
        ),
        'cat << EOF >> /home/user/.ssh/authorized_keys\nssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 example@host\nEOF',
    ]

    for cmd in test_commands:
        keys = extractor.extract_keys_from_command(cmd)
        # We don't assert counts here; this is a debug aid to see extraction flow in CI logs
        for key in keys:
            assert key.key_full
            assert key.extraction_method
