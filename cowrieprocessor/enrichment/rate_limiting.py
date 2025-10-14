"""Rate limiting utilities for enrichment services."""

from __future__ import annotations

import asyncio
import random
import time
from functools import wraps
from typing import Any, Callable, TypeVar

import requests

T = TypeVar('T')


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
        self.tokens = burst
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
        self._loop = None

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
) -> Callable:
    """Decorator for retry logic with exponential backoff."""

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

                    # Special handling for 401 errors (often rate limiting)
                    if isinstance(e, requests.HTTPError) and hasattr(e, 'response'):
                        if e.response.status_code == 401:
                            # Longer backoff for 401 errors (rate limiting)
                            backoff = max(backoff, 60.0)  # At least 60 seconds
                            backoff *= 2  # Double the backoff for 401 errors
                        elif e.response.status_code == 429:
                            # Even longer backoff for explicit rate limiting
                            backoff = max(backoff, 120.0)  # At least 2 minutes

                    if jitter:
                        backoff *= 0.5 + random.random() * 0.5

                    time.sleep(backoff)

            raise last_exception

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
    return config["rate"], config["burst"]
