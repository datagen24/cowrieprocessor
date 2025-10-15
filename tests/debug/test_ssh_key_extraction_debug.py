from __future__ import annotations

import logging

from cowrieprocessor.enrichment.ssh_key_extractor import SSHKeyExtractor


def test_extractor_on_sample_commands() -> None:
    logging.basicConfig(level=logging.DEBUG)
    extractor = SSHKeyExtractor()

    test_commands = [
        'echo "ssh-rsa AAAAB3NzaC1yc2EAAAABJQAAAQEArDp4cun2lhr4KUhBGE7VvAcwdli2a8dbnrTOrbMz1+5O73fcBOx8NVbUT0bUanUV9tJ2/9p7+vD0EpZ3Tz/+0kX34uAx1RV/75GVOmNx+9EuWOnvNoaJe0QXx mdrfckr" >> ~/.ssh/authorized_keys',
        'printf "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMu6z4vZc9b4yQ0rQW9s4Jb0m7xZQ8wLqW+4wK3tqB8S test@host" >> /root/.ssh/authorized_keys',
        'cat << EOF >> /home/user/.ssh/authorized_keys\nssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABAQC7 example@host\nEOF',
    ]

    for cmd in test_commands:
        keys = extractor.extract_keys_from_command(cmd)
        # We don't assert counts here; this is a debug aid to see extraction flow in CI logs
        for key in keys:
            assert key.key_full
            assert key.extraction_method

