"""Rate limiting utilities for enrichment services."""

from __future__ import annotations

import asyncio
import random
import time
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import Any, Callable, Optional, TypeVar

import requests

T = TypeVar('T')


def _get_retry_after_seconds(response: requests.Response) -> Optional[float]:
    """Extract Retry-After header value in seconds.

    Supports both HTTP Retry-After header formats per RFC 7231:
    - Delay-seconds: "Retry-After: 30"
    - HTTP-date: "Retry-After: Wed, 21 Oct 2015 07:28:00 GMT"

    Args:
        response: HTTP response object potentially containing Retry-After header

    Returns:
        Number of seconds to wait before retrying, or None if header not present
        or invalid. Returns 0.0 if the HTTP-date is in the past.

    Examples:
        >>> response = Mock(headers={"Retry-After": "30"})
        >>> _get_retry_after_seconds(response)
        30.0

        >>> response = Mock(headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"})
        >>> _get_retry_after_seconds(response)  # Returns seconds until that time
        ...

        >>> response = Mock(headers={})
        >>> _get_retry_after_seconds(response) is None
        True
    """
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None

    # Try parsing as delay-seconds format first (simpler, more common)
    try:
        return float(retry_after)
    except ValueError:
        pass

    # Try parsing as HTTP-date format
    try:
        retry_datetime = parsedate_to_datetime(retry_after)
        if retry_datetime is None:
            return None

        # Get current time as timezone-aware datetime
        from datetime import datetime, timezone

        current_datetime = datetime.now(timezone.utc)

        delay_seconds = (retry_datetime - current_datetime).total_seconds()
        # Return 0.0 if the date is in the past (server misconfiguration)
        return max(0.0, delay_seconds)
    except (ValueError, TypeError, OverflowError, AttributeError):
        # Invalid HTTP-date format
        return None


class AdaptiveRateLimiter:
    """Adaptive rate limiter that tracks consecutive failures and adjusts backoff.

    This class wraps the standard RateLimiter and adds adaptive behavior based on
    consecutive API failures (401/429 errors). It implements exponential backoff
    that resets on successful requests.

    Attributes:
        rate_limiter: Underlying token bucket rate limiter
        consecutive_failures: Count of consecutive 401/429 errors
        max_backoff_seconds: Maximum backoff delay (default: 1 hour)
        base_backoff_seconds: Base backoff for first failure (default: 60s)
    """

    def __init__(
        self,
        rate: float,
        burst: int,
        base_backoff_seconds: float = 60.0,
        max_backoff_seconds: float = 3600.0,
    ):
        """Initialize adaptive rate limiter.

        Args:
            rate: Tokens per second for normal operation
            burst: Maximum burst capacity
            base_backoff_seconds: Base backoff delay for first failure (default: 60s)
            max_backoff_seconds: Maximum backoff delay cap (default: 1 hour)
        """
        self.rate_limiter = RateLimiter(rate, burst)
        self.consecutive_failures = 0
        self.base_backoff_seconds = base_backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    def apply_backoff(self) -> None:
        """Apply adaptive backoff before making a request.

        Backoff increases exponentially with consecutive failures:
        - 1st failure: 60s
        - 2nd failure: 120s
        - 3rd failure: 240s
        - 4th+ failure: capped at max_backoff_seconds (3600s = 1hr)

        This method should be called BEFORE making an API request when
        there have been previous failures.
        """
        if self.consecutive_failures == 0:
            # No backoff needed on first request or after successful reset
            return

        # Calculate exponential backoff: base * 2^(failures-1)
        backoff_seconds = self.base_backoff_seconds * (2 ** (self.consecutive_failures - 1))
        backoff_seconds = min(backoff_seconds, self.max_backoff_seconds)

        time.sleep(backoff_seconds)

    def record_failure(self) -> None:
        """Record a rate limit failure (401/429 error).

        Increments the consecutive failure counter, which will increase
        backoff delays on subsequent requests.
        """
        self.consecutive_failures += 1

    def record_success(self) -> None:
        """Record a successful request.

        Resets the consecutive failure counter to 0, returning to normal
        operation without adaptive backoff.
        """
        self.consecutive_failures = 0

    def acquire_sync(self) -> None:
        """Acquire a token with adaptive backoff if needed."""
        self.apply_backoff()
        self.rate_limiter.acquire_sync()


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, rate: float, burst: int):
        """Initialize rate limiter.

        Args:
            rate: Tokens per second
            burst: Maximum burst capacity
        """
        self.rate = rate
        self.burst = burst
        self.tokens: float = float(burst)
        self.last_update = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquire a token, waiting if necessary."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1

    def acquire_sync(self) -> None:
        """Synchronous version of acquire for use in non-async contexts."""
        now = time.time()
        elapsed = now - self.last_update
        self.tokens = min(self.burst, self.tokens + elapsed * self.rate)
        self.last_update = now

        if self.tokens < 1:
            wait_time = (1 - self.tokens) / self.rate
            time.sleep(wait_time)
            self.tokens = 0
        else:
            self.tokens -= 1


class RateLimitedSession:
    """Requests session with rate limiting."""

    def __init__(self, rate_limit: float = 4.0, burst: int = 5):
        """Initialize rate-limited session.

        Args:
            rate_limit: Requests per second
            burst: Maximum burst capacity
        """
        self.session = requests.Session()
        self.rate_limiter = RateLimiter(rate_limit, burst)
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Get or create event loop for rate limiting."""
        if self._loop is None or self._loop.is_closed():
            try:
                self._loop = asyncio.get_event_loop()
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                asyncio.set_event_loop(self._loop)
        return self._loop

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        """Rate-limited GET request."""
        # Use synchronous rate limiting to avoid async context issues
        self.rate_limiter.acquire_sync()
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        """Rate-limited POST request."""
        # Use synchronous rate limiting to avoid async context issues
        self.rate_limiter.acquire_sync()
        return self.session.post(url, **kwargs)

    def close(self) -> None:
        """Close the underlying session."""
        self.session.close()


def with_retries(
    max_retries: int = 3,
    backoff_base: float = 1.0,
    backoff_factor: float = 2.0,
    jitter: bool = True,
    respect_retry_after: bool = False,
) -> Callable:
    """Decorator for retry logic with exponential backoff and optional Retry-After support.

    Args:
        max_retries: Maximum number of retry attempts
        backoff_base: Base backoff time in seconds
        backoff_factor: Multiplier for exponential backoff
        jitter: Whether to add random jitter to backoff times
        respect_retry_after: If True, honors HTTP Retry-After headers (recommended
            for DShield and other APIs that provide server-side backoff guidance)

    Returns:
        Decorator function that wraps the target function with retry logic

    Examples:
        @with_retries(max_retries=3, respect_retry_after=True)
        def api_call():
            # Function will honor server Retry-After headers
            ...

        @with_retries(max_retries=5, backoff_base=2.0)
        def flaky_operation():
            # Standard exponential backoff without Retry-After
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (requests.RequestException, ConnectionError, TimeoutError) as e:
                    last_exception = e

                    if attempt == max_retries:
                        break

                    # Calculate backoff with jitter
                    backoff = backoff_base * (backoff_factor**attempt)
                    should_apply_jitter = jitter  # Track if we should apply jitter

                    # Special handling for HTTP errors with respect_retry_after
                    if isinstance(e, requests.HTTPError) and hasattr(e, 'response'):
                        if respect_retry_after and e.response is not None:
                            # Try to get server-provided Retry-After delay
                            retry_after_delay = _get_retry_after_seconds(e.response)
                            if retry_after_delay is not None:
                                # Use server-provided delay (no jitter for explicit server guidance)
                                backoff = retry_after_delay
                                should_apply_jitter = False
                            elif e.response.status_code == 401:
                                # Fallback for 401 without Retry-After header
                                backoff = max(backoff, 60.0)  # At least 60 seconds
                                should_apply_jitter = False  # No jitter for rate limit errors
                            elif e.response.status_code == 429:
                                # Fallback for 429 without Retry-After header
                                backoff = max(backoff, 120.0)  # At least 2 minutes
                                should_apply_jitter = False  # No jitter for rate limit errors
                        else:
                            # Legacy behavior when respect_retry_after=False
                            if e.response.status_code == 401:
                                # Longer backoff for 401 errors (rate limiting)
                                backoff = max(backoff, 60.0)  # At least 60 seconds
                                backoff *= 2  # Double the backoff for 401 errors
                                should_apply_jitter = False  # No jitter for rate limit errors
                            elif e.response.status_code == 429:
                                # Even longer backoff for explicit rate limiting
                                backoff = max(backoff, 120.0)  # At least 2 minutes
                                should_apply_jitter = False  # No jitter for rate limit errors

                    # Apply jitter only if appropriate
                    if should_apply_jitter:
                        backoff *= 0.5 + random.random() * 0.5

                    time.sleep(backoff)

            if last_exception is not None:
                raise last_exception
            else:
                raise RuntimeError("Retry loop completed without exception")

        return wrapper

    return decorator


def create_rate_limited_session_factory(
    rate_limit: float = 4.0,
    burst: int = 5,
) -> Callable[[], RateLimitedSession]:
    """Create a session factory that returns rate-limited sessions."""

    def factory() -> RateLimitedSession:
        return RateLimitedSession(rate_limit, burst)

    return factory


# Service-specific rate limits based on API documentation
SERVICE_RATE_LIMITS = {
    "dshield": {"rate": 1.0, "burst": 2},  # Conservative for DShield
    "virustotal": {"rate": 0.067, "burst": 1},  # VT allows 4 requests/minute = 0.067/sec
    "urlhaus": {"rate": 2.0, "burst": 3},  # Conservative for URLHaus
    "spur": {"rate": 1.0, "burst": 2},  # Conservative for SPUR
    "hibp": {"rate": 0.625, "burst": 1},  # HIBP requires 1.6s between requests = 0.625 req/sec
}


def get_service_rate_limit(service: str) -> tuple[float, int]:
    """Get rate limit configuration for a service."""
    config = SERVICE_RATE_LIMITS.get(service, {"rate": 1.0, "burst": 2})
    return config["rate"], int(config["burst"])
