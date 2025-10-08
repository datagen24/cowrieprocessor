"""VirusTotal quota management and monitoring utilities."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import vt


@dataclass(frozen=True, slots=True)
class QuotaInfo:
    """VirusTotal quota information."""

    daily_requests_used: int
    daily_requests_limit: int
    hourly_requests_used: int
    hourly_requests_limit: int
    monthly_requests_used: int
    monthly_requests_limit: int
    api_requests_used: int
    api_requests_limit: int

    @property
    def daily_remaining(self) -> int:
        """Get remaining daily requests."""
        return max(0, self.daily_requests_limit - self.daily_requests_used)

    @property
    def hourly_remaining(self) -> int:
        """Get remaining hourly requests."""
        return max(0, self.hourly_requests_limit - self.hourly_requests_used)

    @property
    def api_remaining(self) -> int:
        """Get remaining API requests."""
        return max(0, self.api_requests_limit - self.api_requests_used)

    @property
    def daily_usage_percent(self) -> float:
        """Get daily usage as percentage."""
        if self.daily_requests_limit == 0:
            return 100.0
        return (self.daily_requests_used / self.daily_requests_limit) * 100.0

    @property
    def hourly_usage_percent(self) -> float:
        """Get hourly usage as percentage."""
        if self.hourly_requests_limit == 0:
            return 100.0
        return (self.hourly_requests_used / self.hourly_requests_limit) * 100.0


class VirusTotalQuotaManager:
    """Manages VirusTotal API quota monitoring and enforcement."""

    def __init__(self, api_key: str, cache_ttl: int = 300) -> None:
        """Initialize quota manager.

        Args:
            api_key: VirusTotal API key
            cache_ttl: Cache quota info for this many seconds
        """
        self.api_key = api_key
        self.cache_ttl = cache_ttl
        self._client: Optional[vt.Client] = None
        self._quota_cache: Optional[QuotaInfo] = None
        self._cache_timestamp: float = 0.0

    def _get_client(self) -> vt.Client:
        """Get or create VirusTotal client."""
        if self._client is None:
            self._client = vt.Client(self.api_key)
        return self._client

    def get_quota_info(self, force_refresh: bool = False) -> Optional[QuotaInfo]:
        """Get current quota information.

        Args:
            force_refresh: Force refresh of cached quota info

        Returns:
            Quota information or None if unable to fetch
        """
        now = time.time()

        # Return cached info if still valid and not forcing refresh
        if not force_refresh and self._quota_cache is not None and (now - self._cache_timestamp) < self.cache_ttl:
            return self._quota_cache

        try:
            client = self._get_client()

            # Get user info to access quota endpoints
            user_info = client.get_json("/users/me")
            user_id = user_info.get("data", {}).get("id")

            if not user_id:
                return None

            # Get overall quotas
            quotas_response = client.get_json(f"/users/{user_id}/overall_quotas")
            quotas_data = quotas_response.get("data", {}).get("attributes", {})

            # Get API usage
            usage_response = client.get_json(f"/users/{user_id}/api_usage")
            usage_data = usage_response.get("data", {}).get("attributes", {})

            # Extract quota information
            quota_info = QuotaInfo(
                daily_requests_used=usage_data.get("api_requests_daily", 0),
                daily_requests_limit=quotas_data.get("api_requests_daily", 0),
                hourly_requests_used=usage_data.get("api_requests_hourly", 0),
                hourly_requests_limit=quotas_data.get("api_requests_hourly", 0),
                monthly_requests_used=usage_data.get("api_requests_monthly", 0),
                monthly_requests_limit=quotas_data.get("api_requests_monthly", 0),
                api_requests_used=usage_data.get("api_requests", 0),
                api_requests_limit=quotas_data.get("api_requests", 0),
            )

            # Update cache
            self._quota_cache = quota_info
            self._cache_timestamp = now

            return quota_info

        except Exception:
            # Return cached info if available, even if stale
            return self._quota_cache

    def can_make_request(self, threshold_percent: float = 90.0) -> bool:
        """Check if we can make a request without exceeding quota.

        Args:
            threshold_percent: Don't make requests if usage exceeds this percentage

        Returns:
            True if safe to make request, False otherwise
        """
        quota_info = self.get_quota_info()
        if quota_info is None:
            # If we can't get quota info, be conservative and allow the request
            # The rate limiter will handle the actual API limits
            return True

        # Check daily and hourly limits
        daily_ok = quota_info.daily_usage_percent <= threshold_percent
        hourly_ok = quota_info.hourly_usage_percent <= threshold_percent

        return daily_ok and hourly_ok

    def get_backoff_time(self) -> float:
        """Get recommended backoff time based on quota usage.

        Returns:
            Backoff time in seconds
        """
        quota_info = self.get_quota_info()
        if quota_info is None:
            return 60.0  # Default 1 minute backoff

        # Calculate backoff based on usage percentage
        daily_percent = quota_info.daily_usage_percent
        hourly_percent = quota_info.hourly_usage_percent

        # Use the higher percentage to determine backoff
        max_percent = max(daily_percent, hourly_percent)

        if max_percent >= 95:
            return 3600.0  # 1 hour if very close to limit
        elif max_percent >= 90:
            return 1800.0  # 30 minutes if close to limit
        elif max_percent >= 80:
            return 900.0  # 15 minutes if getting close
        else:
            return 60.0  # 1 minute default

    def get_quota_summary(self) -> Dict[str, Any]:
        """Get a summary of current quota status.

        Returns:
            Dictionary with quota summary information
        """
        quota_info = self.get_quota_info()
        if quota_info is None:
            return {"status": "unknown", "message": "Unable to fetch quota information"}

        summary = {
            "status": "healthy",
            "daily": {
                "used": quota_info.daily_requests_used,
                "limit": quota_info.daily_requests_limit,
                "remaining": quota_info.daily_remaining,
                "usage_percent": quota_info.daily_usage_percent,
            },
            "hourly": {
                "used": quota_info.hourly_requests_used,
                "limit": quota_info.hourly_requests_limit,
                "remaining": quota_info.hourly_remaining,
                "usage_percent": quota_info.hourly_usage_percent,
            },
            "can_make_request": self.can_make_request(),
            "recommended_backoff": self.get_backoff_time(),
        }

        # Adjust status based on usage
        if quota_info.daily_usage_percent >= 95 or quota_info.hourly_usage_percent >= 95:
            summary["status"] = "critical"
        elif quota_info.daily_usage_percent >= 90 or quota_info.hourly_usage_percent >= 90:
            summary["status"] = "warning"

        return summary

    def close(self) -> None:
        """Close the VirusTotal client."""
        if self._client:
            self._client.close()
            self._client = None


__all__ = ["QuotaInfo", "VirusTotalQuotaManager"]
