"""VirusTotal enrichment handler using the official vt-py SDK."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

import vt

from .rate_limiting import with_retries
from .virustotal_quota import VirusTotalQuotaManager

LOGGER = logging.getLogger(__name__)


class VirusTotalHandler:
    """VirusTotal enrichment handler with quota management and caching."""

    def __init__(
        self,
        api_key: str,
        cache_dir: Path,
        timeout: int = 30,
        skip_enrich: bool = False,
        enable_quota_management: bool = True,
        quota_threshold_percent: float = 90.0,
    ) -> None:
        """Initialize VirusTotal handler.

        Args:
            api_key: VirusTotal API key
            cache_dir: Directory for caching responses
            timeout: Request timeout in seconds
            skip_enrich: Skip enrichment if True
            enable_quota_management: Enable quota monitoring and management
            quota_threshold_percent: Don't make requests if usage exceeds this percentage
        """
        self.api_key = api_key
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.skip_enrich = skip_enrich

        # Initialize client
        if api_key and not skip_enrich:
            self.client = vt.Client(api_key, timeout=timeout)
        else:
            self.client = None

        # Initialize quota manager
        if enable_quota_management and api_key and not skip_enrich:
            self.quota_manager = VirusTotalQuotaManager(api_key)
        else:
            self.quota_manager = None

        self.quota_threshold_percent = quota_threshold_percent

        # Ensure cache directory exists
        if hasattr(self.cache_dir, 'mkdir'):
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_cache_path(self, file_hash: str) -> Path:
        """Get cache file path for a file hash."""
        if isinstance(self.cache_dir, Path):
            return self.cache_dir / f"vt_{file_hash}.json"
        else:
            return Path(self.cache_dir) / f"vt_{file_hash}.json"

    def _load_cached_response(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Load cached response for a file hash."""
        cache_path = self._get_cache_path(file_hash)

        if not cache_path.exists():
            return None

        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            LOGGER.debug("Failed to load cached VT response for %s: %s", file_hash, e)
            return None

    def _save_cached_response(self, file_hash: str, response: Dict[str, Any]) -> None:
        """Save response to cache."""
        cache_path = self._get_cache_path(file_hash)

        try:
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(response, f, indent=2, default=str)
        except (OSError, TypeError, ValueError) as e:
            LOGGER.debug("Failed to save cached VT response for %s: %s", file_hash, e)
            raise

    def _check_quota_before_request(self) -> bool:
        """Check if we can make a request based on quota usage."""
        if not self.quota_manager:
            return True

        can_request = self.quota_manager.can_make_request(self.quota_threshold_percent)

        if not can_request:
            quota_summary = self.quota_manager.get_quota_summary()
            LOGGER.warning("VirusTotal quota threshold exceeded: %s", quota_summary)

        return can_request

    def _handle_quota_error(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Handle quota-related errors by implementing backoff."""
        if not self.quota_manager:
            return None

        backoff_time = self.quota_manager.get_backoff_time()
        LOGGER.warning("VirusTotal quota exceeded for %s, backing off for %.1f seconds", file_hash, backoff_time)

        time.sleep(backoff_time)
        return None

    @with_retries(max_retries=3, backoff_base=1.0, backoff_factor=2.0)
    def _fetch_file_info(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Fetch file information from VirusTotal API."""
        if not self.client:
            return None

        try:
            # Check quota before making request
            if not self._check_quota_before_request():
                return self._handle_quota_error(file_hash)

            # Make API request using vt-py SDK
            file_obj = self.client.get_object(f"/files/{file_hash}")

            # Convert to dictionary format compatible with existing code
            # Handle non-serializable objects by converting them to basic types
            def serialize_value(value):
                """Convert vt-py objects to JSON-serializable format."""
                if hasattr(value, 'to_dict'):
                    # If the object has a to_dict method, use it
                    return value.to_dict()
                elif isinstance(value, dict):
                    # Recursively serialize dictionaries
                    return {k: serialize_value(v) for k, v in value.items()}
                elif isinstance(value, list):
                    # Recursively serialize lists
                    return [serialize_value(item) for item in value]
                elif hasattr(value, '__dict__'):
                    # Try to convert object attributes to dict
                    try:
                        return {k: serialize_value(v) for k, v in value.__dict__.items()}
                    except (TypeError, AttributeError):
                        # If that fails, convert to string
                        return str(value)
                else:
                    # For basic types, return as-is
                    return value

            response_data = {
                "data": {
                    "id": serialize_value(file_obj.id if hasattr(file_obj, 'id') else None),
                    "type": serialize_value(file_obj.type if hasattr(file_obj, 'type') else None),
                    "attributes": {
                        "last_analysis_stats": serialize_value(
                            file_obj.last_analysis_stats if hasattr(file_obj, 'last_analysis_stats') else None
                        ),
                        "last_analysis_results": serialize_value(
                            file_obj.last_analysis_results if hasattr(file_obj, 'last_analysis_results') else None
                        ),
                        "first_submission_date": serialize_value(
                            file_obj.first_submission_date if hasattr(file_obj, 'first_submission_date') else None
                        ),
                        "last_submission_date": serialize_value(
                            file_obj.last_submission_date if hasattr(file_obj, 'last_submission_date') else None
                        ),
                        "md5": serialize_value(file_obj.md5 if hasattr(file_obj, 'md5') else None),
                        "sha1": serialize_value(file_obj.sha1 if hasattr(file_obj, 'sha1') else None),
                        "sha256": serialize_value(file_obj.sha256 if hasattr(file_obj, 'sha256') else None),
                        "size": serialize_value(file_obj.size if hasattr(file_obj, 'size') else None),
                        "type_description": serialize_value(
                            file_obj.type_description if hasattr(file_obj, 'type_description') else None
                        ),
                        "names": serialize_value(file_obj.names if hasattr(file_obj, 'names') else None),
                        "tags": serialize_value(file_obj.tags if hasattr(file_obj, 'tags') else None),
                        "reputation": serialize_value(file_obj.reputation if hasattr(file_obj, 'reputation') else None),
                        "total_votes": serialize_value(
                            file_obj.total_votes if hasattr(file_obj, 'total_votes') else None
                        ),
                        "meaningful_name": serialize_value(
                            file_obj.meaningful_name if hasattr(file_obj, 'meaningful_name') else None
                        ),
                    },
                }
            }

            # Cache the response (but don't fail if caching fails)
            try:
                self._save_cached_response(file_hash, response_data)
            except Exception as cache_error:
                LOGGER.debug("Failed to cache VirusTotal response for %s: %s", file_hash, cache_error)
                # Continue execution even if caching fails

            return response_data

        except vt.APIError as e:
            if e.code == "NotFoundError":
                LOGGER.debug("VirusTotal file not found for %s", file_hash)
                return None
            elif e.code == "QuotaExceededError":
                LOGGER.warning("VirusTotal quota exceeded for %s", file_hash)
                return self._handle_quota_error(file_hash)
            else:
                LOGGER.warning("VirusTotal API error for %s: %s", file_hash, e)
                raise
        except Exception as e:
            LOGGER.warning("VirusTotal request failed for %s: %s", file_hash, e)
            raise

    def enrich_file(self, file_hash: str) -> Optional[Dict[str, Any]]:
        """Enrich file hash with VirusTotal information.

        Args:
            file_hash: SHA256 hash of the file

        Returns:
            VirusTotal response data or None if enrichment failed/skipped
        """
        if self.skip_enrich or not self.api_key:
            return None

        # Check cache first
        cached_response = self._load_cached_response(file_hash)
        if cached_response is not None:
            LOGGER.debug("Using cached VirusTotal response for %s", file_hash)
            return cached_response

        # Fetch fresh data
        try:
            response = self._fetch_file_info(file_hash)
            return response
        except Exception as e:
            LOGGER.error("VirusTotal enrichment failed for %s: %s", file_hash, e)
            return None

    def get_quota_status(self) -> Dict[str, Any]:
        """Get current quota status.

        Returns:
            Dictionary with quota status information
        """
        if not self.quota_manager:
            return {"status": "disabled", "message": "Quota management disabled"}

        return self.quota_manager.get_quota_summary()

    def extract_analysis_stats(self, vt_response: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Extract analysis statistics from VirusTotal response.

        Args:
            vt_response: VirusTotal API response

        Returns:
            Dictionary with analysis statistics
        """
        if not vt_response or not isinstance(vt_response, dict):
            return {}

        data = vt_response.get("data")
        if not isinstance(data, dict):
            return {}

        attributes = data.get("attributes")
        if not isinstance(attributes, dict):
            return {}

        stats = attributes.get("last_analysis_stats")
        if not isinstance(stats, dict):
            return {}

        # Extract key statistics (only sum numeric values)
        return {
            "harmless": stats.get("harmless", 0),
            "malicious": stats.get("malicious", 0),
            "suspicious": stats.get("suspicious", 0),
            "undetected": stats.get("undetected", 0),
            "timeout": stats.get("timeout", 0),
            "confirmed_timeout": stats.get("confirmed-timeout", 0),
            "failure": stats.get("failure", 0),
            "type_unsupported": stats.get("type-unsupported", 0),
            "total_scans": sum(v for v in stats.values() if isinstance(v, (int, float))) if stats else 0,
        }

    def is_malicious(self, vt_response: Optional[Dict[str, Any]], threshold: int = 2) -> bool:
        """Check if file is considered malicious based on VirusTotal analysis.

        Args:
            vt_response: VirusTotal API response
            threshold: Minimum number of malicious detections to consider file malicious

        Returns:
            True if file is considered malicious, False otherwise
        """
        stats = self.extract_analysis_stats(vt_response)
        return stats.get("malicious", 0) >= threshold

    def close(self) -> None:
        """Close the VirusTotal client and quota manager."""
        if self.client:
            self.client.close()
        if self.quota_manager:
            self.quota_manager.close()


__all__ = ["VirusTotalHandler"]
