"""Unit tests for memory utility functions."""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import pytest

from cowrieprocessor.utils.memory import (
    MAX_BATCH_SIZE,
    MIN_BATCH_SIZE,
    calculate_batch_size,
    estimate_memory_per_session,
    get_available_memory_gb,
)


class TestCalculateBatchSize:
    """Test batch size calculation logic."""

    def test_default_parameters(self) -> None:
        """Test with default parameters (4GB memory, 50KB per session)."""
        batch_size = calculate_batch_size(memory_limit_gb=4.0)

        # Expected: Raw = 67108, capped at MAX_BATCH_SIZE = 10000
        assert batch_size == MAX_BATCH_SIZE
        assert MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE

    def test_small_memory_limit(self) -> None:
        """Test with constrained memory (0.5GB)."""
        batch_size = calculate_batch_size(memory_limit_gb=0.5)

        # Expected: Raw = 8388, within bounds
        assert batch_size == 8388
        assert MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE

    def test_large_memory_limit_caps_at_max(self) -> None:
        """Test that large memory limits cap at MAX_BATCH_SIZE."""
        batch_size = calculate_batch_size(memory_limit_gb=16.0)

        # Raw calculation would be 13107, but should cap at MAX_BATCH_SIZE
        assert batch_size == MAX_BATCH_SIZE

    def test_very_small_memory_enforces_minimum(self) -> None:
        """Test that very small memory limits enforce MIN_BATCH_SIZE."""
        # Memory too small to support even min batch
        batch_size = calculate_batch_size(memory_limit_gb=0.001)

        # Should enforce minimum
        assert batch_size == MIN_BATCH_SIZE

    def test_custom_memory_per_session(self) -> None:
        """Test with custom memory per session estimate."""
        # 2GB memory, 100KB per session
        batch_size = calculate_batch_size(memory_limit_gb=2.0, memory_per_session_kb=100)

        # Expected: Raw = 16777, capped at MAX_BATCH_SIZE = 10000
        assert batch_size == MAX_BATCH_SIZE

    def test_custom_safety_margin(self) -> None:
        """Test with custom safety margin."""
        # 4GB memory, 70% safety margin
        batch_size = calculate_batch_size(memory_limit_gb=4.0, safety_margin=0.7)

        # Expected: Raw = 58720, capped at MAX_BATCH_SIZE = 10000
        assert batch_size == MAX_BATCH_SIZE

    def test_custom_bounds(self) -> None:
        """Test with custom min/max bounds."""
        batch_size = calculate_batch_size(
            memory_limit_gb=0.2,
            memory_per_session_kb=100,
            safety_margin=0.7,
            min_batch=50,
            max_batch=5000,
        )

        # Expected: Raw = 1468, within custom bounds [50, 5000]
        assert batch_size == 1468
        assert 50 <= batch_size <= 5000

    def test_edge_case_minimum_memory(self) -> None:
        """Test edge case with very small memory value."""
        batch_size = calculate_batch_size(memory_limit_gb=0.01)

        # Even 0.01GB (10MB) * 0.8 = 8MB allows 146 batches at 50KB each
        assert batch_size == 167

    def test_edge_case_large_per_session_memory(self) -> None:
        """Test edge case with large per-session memory."""
        # 4GB memory, but 1MB per session
        batch_size = calculate_batch_size(memory_limit_gb=4.0, memory_per_session_kb=1024)

        # Expected: Raw = 3276, within bounds
        assert batch_size == 3276

    def test_validation_negative_memory_limit(self) -> None:
        """Test validation rejects negative memory limit."""
        with pytest.raises(ValueError, match="memory_limit_gb must be > 0"):
            calculate_batch_size(memory_limit_gb=-1.0)

    def test_validation_zero_memory_limit(self) -> None:
        """Test validation rejects zero memory limit."""
        with pytest.raises(ValueError, match="memory_limit_gb must be > 0"):
            calculate_batch_size(memory_limit_gb=0.0)

    def test_validation_negative_memory_per_session(self) -> None:
        """Test validation rejects negative memory per session."""
        with pytest.raises(ValueError, match="memory_per_session_kb must be > 0"):
            calculate_batch_size(memory_limit_gb=4.0, memory_per_session_kb=-10)

    def test_validation_zero_memory_per_session(self) -> None:
        """Test validation rejects zero memory per session."""
        with pytest.raises(ValueError, match="memory_per_session_kb must be > 0"):
            calculate_batch_size(memory_limit_gb=4.0, memory_per_session_kb=0)

    def test_validation_invalid_safety_margin_zero(self) -> None:
        """Test validation rejects zero safety margin."""
        with pytest.raises(ValueError, match="safety_margin must be in"):
            calculate_batch_size(memory_limit_gb=4.0, safety_margin=0.0)

    def test_validation_invalid_safety_margin_negative(self) -> None:
        """Test validation rejects negative safety margin."""
        with pytest.raises(ValueError, match="safety_margin must be in"):
            calculate_batch_size(memory_limit_gb=4.0, safety_margin=-0.5)

    def test_validation_invalid_safety_margin_too_large(self) -> None:
        """Test validation rejects safety margin > 1.0."""
        with pytest.raises(ValueError, match="safety_margin must be in"):
            calculate_batch_size(memory_limit_gb=4.0, safety_margin=1.5)

    def test_validation_min_greater_than_max(self) -> None:
        """Test validation rejects min_batch > max_batch."""
        with pytest.raises(ValueError, match="min_batch .* must be <= max_batch"):
            calculate_batch_size(memory_limit_gb=4.0, min_batch=1000, max_batch=500)

    def test_various_memory_limits(self) -> None:
        """Test a range of realistic memory limits."""
        test_cases = [
            (0.5, 8388),  # 512MB
            (1.0, MAX_BATCH_SIZE),  # 1GB (raw=16777, capped)
            (2.0, MAX_BATCH_SIZE),  # 2GB (raw=33554, capped)
            (4.0, MAX_BATCH_SIZE),  # 4GB (raw=67108, capped)
            (8.0, MAX_BATCH_SIZE),  # 8GB (raw=134217, capped)
            (16.0, MAX_BATCH_SIZE),  # 16GB (capped)
            (32.0, MAX_BATCH_SIZE),  # 32GB (capped)
        ]

        for memory_gb, expected_batch in test_cases:
            batch_size = calculate_batch_size(memory_limit_gb=memory_gb)
            assert batch_size == expected_batch, (
                f"Failed for {memory_gb}GB: expected {expected_batch}, got {batch_size}"
            )


class TestGetAvailableMemory:
    """Test system memory detection."""

    def test_psutil_available(self) -> None:
        """Test memory detection via psutil."""
        # Import psutil within test to create a mock
        with patch.dict("sys.modules", {"psutil": MagicMock()}):
            import sys

            mock_vm = MagicMock()
            mock_vm.available = 8 * 1024**3  # 8GB in bytes
            sys.modules["psutil"].virtual_memory.return_value = mock_vm

            available_gb = get_available_memory_gb()

            assert available_gb == 8.0
            sys.modules["psutil"].virtual_memory.assert_called_once()

    @pytest.mark.skipif("psutil" in __import__("sys").modules, reason="psutil installed, skipping fallback test")
    def test_linux_fallback(self) -> None:
        """Test Linux fallback using /proc/meminfo."""
        meminfo_content = """MemTotal:       16384000 kB
MemFree:         8192000 kB
MemAvailable:    10240000 kB
Buffers:          512000 kB
Cached:          2048000 kB
"""

        # Patch platform and file open
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", mock_open(read_data=meminfo_content)):
                available_gb = get_available_memory_gb()

                # MemAvailable: 10240000 kB = 10000 MB = 9.765625 GB
                assert abs(available_gb - 9.765625) < 0.001

    @pytest.mark.skipif("psutil" in __import__("sys").modules, reason="psutil installed, skipping fallback test")
    def test_linux_fallback_no_memavailable(self) -> None:
        """Test Linux fallback when MemAvailable is missing."""
        meminfo_content = """MemTotal:       16384000 kB
MemFree:         8192000 kB
Buffers:          512000 kB
Cached:          2048000 kB
"""

        # Patch platform and file open
        with patch("platform.system", return_value="Linux"):
            with patch("builtins.open", mock_open(read_data=meminfo_content)):
                available_gb = get_available_memory_gb()

                # MemFree: 8192000 kB = 8000 MB = 7.8125 GB
                assert abs(available_gb - 7.8125) < 0.001

    @patch("platform.system", return_value="Darwin")
    @patch("subprocess.run")
    def test_macos_fallback(self, mock_run: MagicMock, mock_system: MagicMock) -> None:
        """Test macOS fallback using vm_stat."""
        vm_stat_output = """Mach Virtual Memory Statistics: (page size of 4096 bytes)
Pages free:                              1048576.
Pages active:                            2097152.
Pages inactive:                           524288.
Pages speculative:                        131072.
"""

        mock_result = MagicMock()
        mock_result.stdout = vm_stat_output
        mock_run.return_value = mock_result

        # Mock psutil as not available
        with patch.dict("sys.modules", {"psutil": None}):
            available_gb = get_available_memory_gb()

            # Free: 1048576 pages, Inactive: 524288 pages
            # Total: 1572864 pages * 4096 bytes/page = 6442450944 bytes
            # = 6.0 GB
            assert abs(available_gb - 6.0) < 0.01

    @patch("platform.system", return_value="Windows")
    @patch("subprocess.run")
    def test_windows_fallback(self, mock_run: MagicMock, mock_system: MagicMock) -> None:
        """Test Windows fallback using wmic."""
        wmic_output = """FreePhysicalMemory
8388608
"""

        mock_result = MagicMock()
        mock_result.stdout = wmic_output
        mock_run.return_value = mock_result

        # Mock psutil as not available
        with patch.dict("sys.modules", {"psutil": None}):
            available_gb = get_available_memory_gb()

            # 8388608 KB = 8192 MB = 8.0 GB
            assert available_gb == 8.0

    @patch("platform.system", return_value="UnknownOS")
    def test_unknown_platform_fallback(self, mock_system: MagicMock) -> None:
        """Test fallback to default when platform is unknown."""
        # Mock psutil as not available
        with patch.dict("sys.modules", {"psutil": None}):
            available_gb = get_available_memory_gb()

            # Should return 4.0 GB fallback
            assert available_gb == 4.0

    @patch("platform.system", return_value="Linux")
    def test_linux_fallback_file_error(self, mock_system: MagicMock) -> None:
        """Test fallback when /proc/meminfo cannot be read."""
        # Mock psutil as not available
        with patch.dict("sys.modules", {"psutil": None}):
            with patch("builtins.open", side_effect=FileNotFoundError("/proc/meminfo not found")):
                available_gb = get_available_memory_gb()

                # Should return 4.0 GB fallback
                assert available_gb == 4.0


class TestEstimateMemoryPerSession:
    """Test session memory estimation."""

    def test_default_estimate(self) -> None:
        """Test default memory estimate."""
        mem_kb = estimate_memory_per_session()

        assert mem_kb == 50  # Conservative default

    def test_with_custom_sample_size(self) -> None:
        """Test with custom sample size (currently returns default)."""
        mem_kb = estimate_memory_per_session(sample_size=200)

        assert mem_kb == 50  # Still returns default

    def test_with_db_engine(self) -> None:
        """Test with mock db_engine (currently unused)."""
        mock_engine = MagicMock()
        mem_kb = estimate_memory_per_session(db_engine=mock_engine)

        assert mem_kb == 50  # Still returns default


class TestIntegration:
    """Integration tests combining multiple functions."""

    def test_full_workflow_auto_detect_memory(self) -> None:
        """Test full workflow with auto-detected memory."""
        # Get available memory
        available_gb = get_available_memory_gb()
        assert available_gb > 0

        # Calculate batch size based on available memory
        batch_size = calculate_batch_size(memory_limit_gb=available_gb)
        assert MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE

    def test_full_workflow_with_custom_estimate(self) -> None:
        """Test workflow with custom memory estimate."""
        # Estimate memory per session
        mem_per_session_kb = estimate_memory_per_session()
        assert mem_per_session_kb > 0

        # Calculate batch size using estimate
        batch_size = calculate_batch_size(
            memory_limit_gb=4.0,
            memory_per_session_kb=mem_per_session_kb,
        )
        assert MIN_BATCH_SIZE <= batch_size <= MAX_BATCH_SIZE

    def test_constrained_system_workflow(self) -> None:
        """Test workflow for resource-constrained system."""
        # Simulate 0.1GB (100MB) memory limit for truly constrained system
        batch_size = calculate_batch_size(memory_limit_gb=0.1)

        # Should be conservative but still functional
        assert batch_size >= MIN_BATCH_SIZE
        assert batch_size < 2000  # Should be modest for 100MB

    def test_high_memory_system_workflow(self) -> None:
        """Test workflow for high-memory system."""
        # Simulate 32GB memory limit
        batch_size = calculate_batch_size(memory_limit_gb=32.0)

        # Should cap at maximum
        assert batch_size == MAX_BATCH_SIZE
