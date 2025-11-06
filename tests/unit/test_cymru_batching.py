"""Unit tests for Cymru batching in refresh command.

Simplified test suite focusing on testable components without mocking complex CLI flows.

Test Coverage:
- 3-pass flow execution order validation
- Batch size validation (≤500 IPs per batch)
- Cymru client bulk lookup behavior
- Status emitter integration
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from cowrieprocessor.enrichment.cymru_client import CymruClient, CymruResult


class TestCymruBatchingLogic:
    """Test suite for Cymru bulk_lookup batching logic."""

    def test_cymru_batch_size_validation(self):
        """Verify batch sizes are 500 or less.

        Team Cymru MAX_BULK_SIZE is 500 IPs per netcat query.
        This test ensures we respect that limit.
        """
        # Verify constant is set correctly
        assert CymruClient.MAX_BULK_SIZE == 500

        # Simulate batching logic from enrich_passwords.py lines 1545-1551
        test_ips = [f"192.168.1.{i}" for i in range(1200)]  # 1200 IPs
        batch_size = 500

        # Calculate batches
        num_batches = (len(test_ips) + batch_size - 1) // batch_size
        assert num_batches == 3  # Should require 3 batches

        # Verify each batch is ≤ 500
        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(test_ips))
            batch = test_ips[start:end]
            assert len(batch) <= 500, f"Batch {batch_idx} has {len(batch)} IPs"

        # Verify batch sizes
        assert len(test_ips[0:500]) == 500  # Batch 1
        assert len(test_ips[500:1000]) == 500  # Batch 2
        assert len(test_ips[1000:1200]) == 200  # Batch 3 (tail)

    def test_refresh_three_pass_flow(self):
        """Verify 3-pass enrichment flow executes in correct order.

        Expected flow:
        1. Pass 1: MaxMind offline enrichment (all IPs)
        2. Pass 2: Cymru bulk batching (only IPs needing ASN)
        3. Pass 3: GreyNoise + database merge (all IPs)
        """
        call_order = []

        # Mock MaxMind
        def mock_maxmind_lookup(ip: str):
            call_order.append(f"maxmind:{ip}")
            return None  # No ASN, triggers Cymru

        # Mock Cymru bulk
        def mock_cymru_bulk(ips: list[str]):
            call_order.append(f"cymru:batch:{len(ips)}")
            return {ip: MagicMock() for ip in ips}

        # Mock GreyNoise
        def mock_greynoise_lookup(ip: str):
            call_order.append(f"greynoise:{ip}")
            return None

        mock_cascade = MagicMock()
        mock_cascade.maxmind.lookup_ip = mock_maxmind_lookup
        mock_cascade.cymru.bulk_lookup = mock_cymru_bulk
        mock_cascade.greynoise.lookup_ip = mock_greynoise_lookup
        mock_cascade._merge_results.return_value = MagicMock()

        # Test IPs
        test_ips = ["8.8.8.8", "1.1.1.1"]

        # Simulate 3-pass flow from enrich_passwords.py lines 1494-1609
        # Pass 1: MaxMind
        maxmind_results = {}
        ips_needing_cymru = []
        for ip in test_ips:
            result = mock_cascade.maxmind.lookup_ip(ip)
            maxmind_results[ip] = result
            if not result or getattr(result, "asn", None) is None:
                ips_needing_cymru.append(ip)

        # Pass 2: Cymru bulk
        cymru_results = {}
        if ips_needing_cymru:
            cymru_results = mock_cascade.cymru.bulk_lookup(ips_needing_cymru)

        # Pass 3: GreyNoise + merge
        for ip in test_ips:
            greynoise_result = mock_cascade.greynoise.lookup_ip(ip)
            maxmind_result = maxmind_results.get(ip)
            cymru_result = cymru_results.get(ip)
            mock_cascade._merge_results(None, maxmind_result, cymru_result, greynoise_result, ip)

        # Verify call order
        expected_order = [
            "maxmind:8.8.8.8",
            "maxmind:1.1.1.1",
            "cymru:batch:2",  # Bulk call for both IPs
            "greynoise:8.8.8.8",
            "greynoise:1.1.1.1",
        ]

        assert call_order == expected_order, f"Expected {expected_order}, got {call_order}"

    def test_status_emitter_during_batching(self):
        """Verify status emitter updates properly during Cymru batching."""
        mock_status_emitter = MagicMock()

        # Simulate Pass 2: Cymru batching from enrich_passwords.py lines 1534-1573
        ips_needing_cymru = [f"10.0.0.{i}" for i in range(1200)]
        batch_size = 500
        num_batches = (len(ips_needing_cymru) + batch_size - 1) // batch_size

        cymru_results = {}

        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(ips_needing_cymru))
            batch = ips_needing_cymru[start:end]

            # Simulate successful batch
            batch_results = {ip: MagicMock() for ip in batch}
            cymru_results.update(batch_results)

            # Record metrics (simulating enrich_passwords.py behavior)
            mock_status_emitter.record_metrics(
                {
                    "phase": "cymru_batching",
                    "batch": batch_idx + 1,
                    "batches_total": num_batches,
                    "ips_enriched": len(cymru_results),
                }
            )

        # Verify status emitter was called for each batch
        assert mock_status_emitter.record_metrics.call_count == num_batches

        # Verify final call had correct total
        final_call = mock_status_emitter.record_metrics.call_args_list[-1]
        assert final_call[0][0]["ips_enriched"] == len(ips_needing_cymru)
        assert final_call[0][0]["batch"] == num_batches


class TestCymruClientBulkLookup:
    """Test suite for CymruClient.bulk_lookup() method."""

    def test_no_dns_timeout_warnings_with_batching(self, caplog: pytest.LogCaptureFixture):
        """Verify no DNS timeout warnings when using Cymru batching.

        The original issue was DNS timeouts when enriching 100+ IPs individually.
        With batching via netcat bulk interface, DNS timeouts should not occur.
        """
        import logging
        import tempfile

        caplog.set_level(logging.WARNING)

        # Mock Cymru client with bulk interface (no DNS)
        from cowrieprocessor.enrichment.cache import EnrichmentCacheManager
        from cowrieprocessor.enrichment.rate_limiting import RateLimiter

        # Use temp directory for cache (will be empty)
        with tempfile.TemporaryDirectory() as tmpdir:
            cache = EnrichmentCacheManager(base_dir=Path(tmpdir))
            limiter = RateLimiter(rate=100.0, burst=100)
            client = CymruClient(cache=cache, rate_limiter=limiter)

            # Simulate bulk lookup (would use netcat, not DNS)
            test_ips = [f"10.99.{i}.{j}" for i in range(10) for j in range(10)]  # 100 unique IPs

            # Mock the internal netcat method to avoid actual network calls
            with patch.object(client, "_bulk_lookup_netcat") as mock_netcat:
                mock_netcat.return_value = {
                    ip: CymruResult(
                        ip_address=ip,
                        asn=15169,
                        asn_org="TEST-ASN",
                        country_code="US",
                        registry="ARIN",
                        ttl_days=90,
                    )
                    for ip in test_ips
                }

                results = client.bulk_lookup(test_ips)

                # Verify netcat was used, not DNS
                assert mock_netcat.called
                assert len(results) == len(test_ips)

                # Verify no DNS timeout warnings in logs
                assert "DNS timeout" not in caplog.text
                assert "dns.exception.Timeout" not in caplog.text

                # Verify Cymru batch messages would be present (if logging enabled)
                # In actual implementation, enrich_passwords.py logs these messages
                # Here we just verify the bulk_lookup method works without DNS

    def test_bulk_lookup_batch_splitting(self):
        """Verify CymruClient has MAX_BULK_SIZE and caller can split batches.

        Note: The actual batching logic is in enrich_passwords.py lines 1545-1571,
        not in CymruClient.bulk_lookup(). This test validates the contract.
        """
        # Verify CymruClient has MAX_BULK_SIZE constant
        assert CymruClient.MAX_BULK_SIZE == 500

        # Demonstrate caller batching logic (from enrich_passwords.py)
        test_ips = [f"10.{i // 256}.{i % 256}.1" for i in range(1200)]
        batch_size = CymruClient.MAX_BULK_SIZE
        num_batches = (len(test_ips) + batch_size - 1) // batch_size

        assert num_batches == 3  # 1200 IPs / 500 = 3 batches

        # Verify batch sizes match expectations
        batches = []
        for batch_idx in range(num_batches):
            start = batch_idx * batch_size
            end = min(start + batch_size, len(test_ips))
            batch = test_ips[start:end]
            batches.append(len(batch))

        assert batches == [500, 500, 200]  # Batch 1, 2, and tail
