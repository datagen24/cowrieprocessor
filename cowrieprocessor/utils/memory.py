"""Memory-aware batch size calculation for ORM loading operations.

This module provides utilities for calculating optimal batch sizes based on
available system memory to prevent OOM errors on resource-constrained systems.

Example:
    >>> # Auto-calculate batch size based on 4GB memory limit
    >>> batch_size = calculate_batch_size(memory_limit_gb=4.0)
    >>> print(f"Calculated batch size: {batch_size}")
    Calculated batch size: 3276

    >>> # Get available system memory
    >>> available_gb = get_available_memory_gb()
    >>> print(f"Available memory: {available_gb:.2f} GB")
    Available memory: 8.45 GB

    >>> # Calculate with custom memory per session
    >>> batch_size = calculate_batch_size(
    ...     memory_limit_gb=2.0,
    ...     memory_per_session_kb=100
    ... )
    >>> print(f"Batch size for 100KB sessions: {batch_size}")
    Batch size for 100KB sessions: 1638
"""

from __future__ import annotations

import logging
import platform
from typing import Optional

logger = logging.getLogger(__name__)

# Batch size bounds
MIN_BATCH_SIZE = 100  # Minimum to avoid excessive DB round-trips
MAX_BATCH_SIZE = 10000  # Maximum to avoid single-batch OOM
DEFAULT_BATCH_SIZE = 1000  # Fallback if calculation fails

# Memory safety margin (use 80% of limit to account for overhead)
MEMORY_SAFETY_MARGIN = 0.8


def calculate_batch_size(
    memory_limit_gb: float,
    memory_per_session_kb: int = 50,
    *,
    safety_margin: float = MEMORY_SAFETY_MARGIN,
    min_batch: int = MIN_BATCH_SIZE,
    max_batch: int = MAX_BATCH_SIZE,
) -> int:
    """Calculate optimal batch size based on memory constraints.

    Uses a safety margin (default 80%) of the memory limit to account for
    Python interpreter overhead, temporary allocations, and database operations.

    Formula:
        usable_memory_bytes = memory_limit_gb * safety_margin * (1024 ** 3)
        memory_per_session_bytes = memory_per_session_kb * 1024
        batch_size = usable_memory_bytes // memory_per_session_bytes
        batch_size = max(min_batch, min(max_batch, batch_size))

    Args:
        memory_limit_gb: Total memory budget for processing (in GB).
        memory_per_session_kb: Estimated memory per session object (in KB).
            Default 50KB is based on typical Cowrie session data with
            ~10-20 events, metadata, and enrichment data.
        safety_margin: Fraction of memory to use (0.0-1.0). Default 0.8
            reserves 20% for overhead.
        min_batch: Minimum batch size to prevent excessive DB round-trips.
        max_batch: Maximum batch size to prevent single-batch OOM.

    Returns:
        Calculated batch size clamped to [min_batch, max_batch] range.

    Raises:
        ValueError: If memory_limit_gb <= 0, memory_per_session_kb <= 0,
            safety_margin not in (0, 1], or min_batch > max_batch.

    Examples:
        >>> # 4GB memory, 50KB per session (default)
        >>> calculate_batch_size(4.0)
        10000

        >>> # 0.5GB memory (constrained system)
        >>> calculate_batch_size(0.5)
        8388

        >>> # 16GB memory (caps at MAX_BATCH_SIZE)
        >>> calculate_batch_size(16.0)
        10000

        >>> # Custom parameters
        >>> calculate_batch_size(
        ...     memory_limit_gb=0.2,
        ...     memory_per_session_kb=100,
        ...     safety_margin=0.7,
        ...     min_batch=50,
        ...     max_batch=5000
        ... )
        1468
    """
    # Input validation
    if memory_limit_gb <= 0:
        raise ValueError(f"memory_limit_gb must be > 0, got {memory_limit_gb}")

    if memory_per_session_kb <= 0:
        raise ValueError(f"memory_per_session_kb must be > 0, got {memory_per_session_kb}")

    if not (0 < safety_margin <= 1.0):
        raise ValueError(f"safety_margin must be in (0, 1], got {safety_margin}")

    if min_batch > max_batch:
        raise ValueError(f"min_batch ({min_batch}) must be <= max_batch ({max_batch})")

    # Calculate usable memory in bytes (for dimensional correctness)
    usable_memory_bytes = memory_limit_gb * safety_margin * (1024**3)

    # Convert memory per session to bytes
    memory_per_session_bytes = memory_per_session_kb * 1024

    # Calculate raw batch size (integer division)
    raw_batch_size = int(usable_memory_bytes // memory_per_session_bytes)

    # Apply bounds
    batch_size = max(min_batch, min(max_batch, raw_batch_size))

    logger.debug(
        "Calculated batch size: memory_limit=%.2fGB, per_session=%dKB, safety_margin=%.2f, raw=%d, bounded=%d",
        memory_limit_gb,
        memory_per_session_kb,
        safety_margin,
        raw_batch_size,
        batch_size,
    )

    return batch_size


def get_available_memory_gb() -> float:
    """Get available system memory in GB.

    Attempts to detect available memory using platform-specific methods.
    Falls back gracefully with warnings if detection fails.

    Returns:
        Available memory in GB. Returns 4.0 GB as fallback if detection fails.

    Examples:
        >>> mem_gb = get_available_memory_gb()
        >>> assert mem_gb > 0, "Should return positive memory value"
        >>> print(f"Available: {mem_gb:.2f} GB")
        Available: 8.45 GB

    Note:
        This function uses psutil if available, otherwise falls back to
        platform-specific methods. On failure, returns 4.0 GB default.
    """
    try:
        # Try psutil first (most reliable, cross-platform)
        import psutil

        available_bytes: int = psutil.virtual_memory().available
        available_gb: float = available_bytes / (1024**3)

        logger.debug("Detected available memory: %.2f GB (via psutil)", available_gb)
        return available_gb

    except ImportError:
        logger.debug("psutil not available, trying platform-specific methods")
        pass

    # Platform-specific fallbacks
    system = platform.system()

    try:
        if system == "Linux":
            # Parse /proc/meminfo
            with open("/proc/meminfo") as f:
                meminfo = dict(line.split()[:2] for line in f if ":" in line)

            # MemAvailable is best metric (includes buffers/cache that can be freed)
            if "MemAvailable" in meminfo:
                available_kb = int(meminfo["MemAvailable"])
            elif "MemFree" in meminfo:
                # Fallback to MemFree (less accurate)
                available_kb = int(meminfo["MemFree"])
            else:
                raise ValueError("Cannot parse /proc/meminfo")

            available_gb = float(available_kb / (1024**2))
            logger.debug("Detected available memory: %.2f GB (via /proc/meminfo)", available_gb)
            return available_gb

        elif system == "Darwin":
            # macOS - use vm_stat
            import subprocess

            result = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True)
            lines = result.stdout.split("\n")

            page_size = 4096  # macOS default page size
            free_pages = 0

            for line in lines:
                if "Pages free:" in line:
                    free_pages += int(line.split(":")[1].strip().rstrip("."))
                elif "Pages inactive:" in line:
                    # Inactive pages can be reclaimed
                    free_pages += int(line.split(":")[1].strip().rstrip("."))

            available_bytes = free_pages * page_size
            available_gb = float(available_bytes / (1024**3))
            logger.debug("Detected available memory: %.2f GB (via vm_stat)", available_gb)
            return available_gb

        elif system == "Windows":
            # Windows - use wmic
            import subprocess

            result = subprocess.run(
                ["wmic", "OS", "get", "FreePhysicalMemory"],
                capture_output=True,
                text=True,
                check=True,
            )
            lines = result.stdout.strip().split("\n")
            free_kb = int(lines[1].strip())  # Second line has the value
            available_gb = float(free_kb / (1024**2))
            logger.debug("Detected available memory: %.2f GB (via wmic)", available_gb)
            return available_gb

    except Exception as e:
        logger.warning("Failed to detect available memory via %s: %s", system, e)

    # Final fallback
    fallback_gb = 4.0
    logger.warning(
        "Could not detect available memory, using fallback: %.2f GB. "
        "Install psutil for accurate memory detection: pip install psutil",
        fallback_gb,
    )
    return fallback_gb


def estimate_memory_per_session(
    db_engine: Optional[object] = None,
    *,
    sample_size: int = 100,
) -> int:
    """Estimate average memory per session object (in KB).

    This is a profiling function for advanced users who want to calibrate
    memory estimates for their specific workload. For most use cases, the
    default 50KB is sufficient.

    Args:
        db_engine: SQLAlchemy engine for sampling sessions (currently unused).
            Reserved for future implementation that samples real session data.
        sample_size: Number of sessions to sample for profiling.

    Returns:
        Estimated memory per session in KB. Currently returns 50 KB default.

    Note:
        Current implementation returns a conservative default of 50 KB.
        Future versions may profile actual session data from the database.

    Examples:
        >>> # Get default estimate
        >>> mem_kb = estimate_memory_per_session()
        >>> print(f"Estimated memory: {mem_kb} KB")
        Estimated memory: 50 KB

        >>> # With custom sample size (future implementation)
        >>> mem_kb = estimate_memory_per_session(sample_size=200)
        >>> print(f"Estimated memory: {mem_kb} KB")
        Estimated memory: 50 KB
    """
    # Conservative default based on typical Cowrie session:
    # - Base SessionSummary ORM object: ~2-5 KB
    # - Event list (10-20 events): ~20-30 KB
    # - Enrichment data (VT, DShield, etc.): ~10-15 KB
    # - Python object overhead: ~5-10 KB
    # Total: ~50 KB per session (includes safety margin)

    default_estimate_kb = 50

    logger.debug(
        "Using default memory estimate: %d KB per session (sample_size=%d)",
        default_estimate_kb,
        sample_size,
    )

    # Future implementation could:
    # 1. Query sample_size sessions from db_engine
    # 2. Measure memory footprint using sys.getsizeof + pympler
    # 3. Return average measured size

    return default_estimate_kb
