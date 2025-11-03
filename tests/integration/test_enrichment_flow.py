"""Integration tests for DShield adaptive rate limiting (Issue #118, ADR-005 Phase 1A).

This module provides comprehensive integration tests for the with_retries decorator
and its integration with DShield-like enrichment scenarios. Tests verify Retry-After
header support, exponential backoff behavior, and adaptive rate limiting.

Test Coverage:
    - Retry-After header parsing and honoring (delay-seconds and HTTP-date formats)
    - 429/401 error handling with adaptive backoff
    - Success after failure scenarios
    - Fallback behavior when Retry-After headers are missing
    - Exponential backoff for generic network errors

All tests use mocked HTTP sessions and time.sleep to avoid network calls and delays.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
import requests

from cowrieprocessor.enrichment.rate_limiting import _get_retry_after_seconds, with_retries


class TestAdaptiveRateLimitingIntegration:
    """Integration tests for adaptive rate limiting with Retry-After support (Issue #118)."""

    @patch('time.sleep')
    def test_retry_after_delay_seconds_format(self, mock_sleep: Mock) -> None:
        """Test that Retry-After header with delay-seconds format is honored.

        This test verifies RFC 7231 compliance for the simple delay-seconds format.

        Expected behavior:
            1. First request returns 429 with Retry-After: 30
            2. Client sleeps for exactly 30 seconds
            3. Retry succeeds

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """
        # Create a function that fails once with 429, then succeeds
        call_count = 0

        @with_retries(max_retries=3, respect_retry_after=True)
        def mock_api_call():
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 with Retry-After
                response = Mock(spec=requests.Response)
                response.status_code = 429
                response.headers = {"Retry-After": "30"}
                error = requests.HTTPError(response=response)
                error.response = response
                raise error
            else:
                # Second call: success
                return {"success": True}

        # Execute the call
        result = mock_api_call()

        # Verify success
        assert result == {"success": True}

        # Verify Retry-After delay was honored (30 seconds)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert 30.0 in sleep_calls, f"Expected 30s sleep from Retry-After, got {sleep_calls}"

    @patch('time.sleep')
    def test_retry_after_http_date_format(self, mock_sleep: Mock) -> None:
        """Test that Retry-After header with HTTP-date format is honored.

        This test verifies RFC 7231 compliance for the HTTP-date format.

        Expected behavior:
            1. First request returns 429 with Retry-After in HTTP-date format
            2. Client calculates delay from current time to HTTP-date
            3. Client sleeps for calculated delay
            4. Retry succeeds

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """
        # Create a function that fails once with 429 (HTTP-date), then succeeds
        call_count = 0

        # Calculate HTTP-date 45 seconds in the future
        future_time = datetime.now(timezone.utc) + timedelta(seconds=45)
        http_date = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

        @with_retries(max_retries=3, respect_retry_after=True)
        def mock_api_call():
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: return 429 with HTTP-date Retry-After
                response = Mock(spec=requests.Response)
                response.status_code = 429
                response.headers = {"Retry-After": http_date}
                error = requests.HTTPError(response=response)
                error.response = response
                raise error
            else:
                # Second call: success
                return {"success": True}

        # Execute the call
        result = mock_api_call()

        # Verify success
        assert result == {"success": True}

        # Verify delay was calculated from HTTP-date (approximately 45 seconds)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        # Allow variance due to processing time (40-50 seconds)
        assert any(40.0 <= s <= 50.0 for s in sleep_calls), f"Expected ~45s delay from HTTP-date, got {sleep_calls}"

    @patch('time.sleep')
    def test_401_adaptive_backoff_with_retry_after_fallback(self, mock_sleep: Mock) -> None:
        """Test that 401 errors use 60s minimum fallback when Retry-After is missing.

        This test verifies that when a 401 error occurs without a Retry-After header,
        the decorator applies a 60-second minimum backoff per ADR-005 specifications.

        Expected behavior:
            1. First request: 401 without Retry-After → backoff ≥60s
            2. Second request: 401 without Retry-After → backoff ≥60s
            3. Third request: 401 without Retry-After → backoff ≥60s
            4. After max retries: give up

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """

        @with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0, respect_retry_after=True)
        def mock_api_call():
            # Always fail with 401 without Retry-After
            response = Mock(spec=requests.Response)
            response.status_code = 401
            response.headers = {}  # No Retry-After header
            error = requests.HTTPError(response=response)
            error.response = response
            raise error

        # Execute and expect final exception after retries
        with pytest.raises(requests.HTTPError):
            mock_api_call()

        # Verify backoff delays meet 60s minimum for 401 errors
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 3, f"Expected 3 backoff sleeps, got {len(sleep_calls)}"

        # All backoff delays should be >= 60s for 401 errors
        for i, delay in enumerate(sleep_calls):
            assert delay >= 60.0, f"Backoff {i + 1} too short: {delay}s (expected ≥60s for 401)"

    @patch('time.sleep')
    def test_429_adaptive_backoff_with_retry_after_fallback(self, mock_sleep: Mock) -> None:
        """Test that 429 errors use 120s minimum fallback when Retry-After is missing.

        This test verifies that when a 429 error occurs without a Retry-After header,
        the decorator applies a 120-second minimum backoff per ADR-005 specifications.

        Expected behavior:
            1. First request: 429 without Retry-After → backoff ≥120s
            2. Second request: 429 without Retry-After → backoff ≥120s
            3. Third request: 429 without Retry-After → backoff ≥120s
            4. After max retries: give up

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """

        @with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0, respect_retry_after=True)
        def mock_api_call():
            # Always fail with 429 without Retry-After
            response = Mock(spec=requests.Response)
            response.status_code = 429
            response.headers = {}  # No Retry-After header
            error = requests.HTTPError(response=response)
            error.response = response
            raise error

        # Execute and expect final exception after retries
        with pytest.raises(requests.HTTPError):
            mock_api_call()

        # Verify backoff delays meet 120s minimum for 429 errors
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 3, f"Expected 3 backoff sleeps, got {len(sleep_calls)}"

        # All backoff delays should be >= 120s for 429 errors
        for i, delay in enumerate(sleep_calls):
            assert delay >= 120.0, f"Backoff {i + 1} too short: {delay}s (expected ≥120s for 429)"

    @patch('time.sleep')
    def test_success_after_failure_continues_normally(self, mock_sleep: Mock) -> None:
        """Test that successful requests after failures complete normally.

        This test verifies that the retry mechanism properly handles the pattern:
        failure → retry → success (no further retries needed).

        Expected behavior:
            1. First request: 429 with Retry-After: 10
            2. Client sleeps for 10 seconds
            3. Second request: Success
            4. No further retries needed

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """
        call_count = 0

        @with_retries(max_retries=3, respect_retry_after=True)
        def mock_api_call():
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: 429 with Retry-After
                response = Mock(spec=requests.Response)
                response.status_code = 429
                response.headers = {"Retry-After": "10"}
                error = requests.HTTPError(response=response)
                error.response = response
                raise error
            else:
                # Second call: success
                return {"data": "success"}

        # Execute the call
        result = mock_api_call()

        # Verify success
        assert result == {"data": "success"}
        assert call_count == 2, "Expected exactly 2 calls (1 failure + 1 success)"

        # Verify only one sleep (for the retry after failure)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 1, f"Expected 1 sleep, got {len(sleep_calls)}"
        assert sleep_calls[0] == 10.0, f"Expected 10s sleep, got {sleep_calls[0]}"

    @patch('time.sleep')
    def test_exponential_backoff_for_network_errors(self, mock_sleep: Mock) -> None:
        """Test exponential backoff for generic network errors.

        This test verifies that non-HTTP errors (like ConnectionError) still
        trigger exponential backoff according to backoff_base and backoff_factor.

        Expected behavior:
            1. First failure → backoff ~0.5-1.0s (base * 2^0 with jitter)
            2. Second failure → backoff ~1.0-2.0s (base * 2^1 with jitter)
            3. Third failure → backoff ~2.0-4.0s (base * 2^2 with jitter)
            4. After max retries: give up

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """

        @with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0, jitter=True)
        def mock_api_call():
            # Always fail with network error
            raise requests.ConnectionError("Network unreachable")

        # Execute and expect final exception after retries
        with pytest.raises(requests.ConnectionError):
            mock_api_call()

        # Verify exponential backoff pattern with jitter
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 3, f"Expected 3 backoff sleeps, got {len(sleep_calls)}"

        # With jitter, backoff is: base * (factor ** attempt) * (0.5 to 1.0)
        # Verify escalation trend (allowing for jitter variance)
        assert sleep_calls[0] >= 0.5, f"First backoff too small: {sleep_calls[0]}"
        assert sleep_calls[1] >= 1.0, f"Second backoff too small: {sleep_calls[1]}"
        assert sleep_calls[2] >= 2.0, f"Third backoff too small: {sleep_calls[2]}"

    @patch('time.sleep')
    def test_retry_after_overrides_exponential_backoff(self, mock_sleep: Mock) -> None:
        """Test that Retry-After header overrides default exponential backoff.

        This test verifies that when a Retry-After header is present, it takes
        precedence over the standard exponential backoff calculation.

        Expected behavior:
            1. First failure: 429 with Retry-After: 15 → sleep 15s (not exponential)
            2. Second failure: 429 with Retry-After: 25 → sleep 25s (not exponential)
            3. Third request: Success

        Args:
            mock_sleep: Mocked time.sleep to avoid actual delays
        """
        call_count = 0

        @with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0, respect_retry_after=True)
        def mock_api_call():
            nonlocal call_count
            call_count += 1

            if call_count == 1:
                # First call: 429 with Retry-After: 15
                response = Mock(spec=requests.Response)
                response.status_code = 429
                response.headers = {"Retry-After": "15"}
                error = requests.HTTPError(response=response)
                error.response = response
                raise error
            elif call_count == 2:
                # Second call: 429 with Retry-After: 25
                response = Mock(spec=requests.Response)
                response.status_code = 429
                response.headers = {"Retry-After": "25"}
                error = requests.HTTPError(response=response)
                error.response = response
                raise error
            else:
                # Third call: success
                return {"status": "ok"}

        # Execute the call
        result = mock_api_call()

        # Verify success
        assert result == {"status": "ok"}

        # Verify Retry-After values were used (not exponential backoff)
        sleep_calls = [c[0][0] for c in mock_sleep.call_args_list]
        assert len(sleep_calls) == 2, f"Expected 2 sleeps, got {len(sleep_calls)}"
        assert sleep_calls[0] == 15.0, f"First delay should be 15s from Retry-After, got {sleep_calls[0]}"
        assert sleep_calls[1] == 25.0, f"Second delay should be 25s from Retry-After, got {sleep_calls[1]}"


class TestRetryAfterHeaderParsing:
    """Unit tests for Retry-After header parsing utility."""

    def test_parse_delay_seconds_format(self) -> None:
        """Test parsing Retry-After header in delay-seconds format."""
        response = Mock()
        response.headers = {"Retry-After": "30"}
        assert _get_retry_after_seconds(response) == 30.0

        response.headers = {"Retry-After": "120"}
        assert _get_retry_after_seconds(response) == 120.0

    def test_parse_http_date_format(self) -> None:
        """Test parsing Retry-After header in HTTP-date format."""
        # Create a time 60 seconds in the future
        future_time = datetime.now(timezone.utc) + timedelta(seconds=60)
        http_date = future_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

        response = Mock()
        response.headers = {"Retry-After": http_date}

        delay = _get_retry_after_seconds(response)
        assert delay is not None
        # Allow some variance due to processing time (55-65 seconds)
        assert 55.0 <= delay <= 65.0, f"Expected ~60s, got {delay}"

    def test_parse_http_date_in_past(self) -> None:
        """Test that HTTP-dates in the past return 0.0."""
        # Create a time in the past
        past_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        http_date = past_time.strftime("%a, %d %b %Y %H:%M:%S GMT")

        response = Mock()
        response.headers = {"Retry-After": http_date}

        delay = _get_retry_after_seconds(response)
        assert delay == 0.0, "Past HTTP-dates should return 0.0"

    def test_missing_retry_after_header(self) -> None:
        """Test that missing Retry-After header returns None."""
        response = Mock()
        response.headers = {}
        assert _get_retry_after_seconds(response) is None

    def test_invalid_retry_after_format(self) -> None:
        """Test that invalid Retry-After formats return None."""
        response = Mock()

        # Invalid delay-seconds
        response.headers = {"Retry-After": "not-a-number"}
        assert _get_retry_after_seconds(response) is None

        # Invalid HTTP-date
        response.headers = {"Retry-After": "Invalid Date Format"}
        assert _get_retry_after_seconds(response) is None
