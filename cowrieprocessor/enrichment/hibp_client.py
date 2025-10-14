"""HIBP (Have I Been Pwned) password breach checking client."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict

import requests

from .cache import EnrichmentCacheManager
from .rate_limiting import RateLimitedSession

logger = logging.getLogger(__name__)


class HIBPPasswordEnricher:
    """Check passwords against Have I Been Pwned using k-anonymity API.
    
    Uses k-anonymity to preserve privacy:
    - Hashes password with SHA-1
    - Sends only first 5 characters to HIBP API
    - Searches response locally for full hash
    
    HIBP API details:
    - Endpoint: https://api.pwnedpasswords.com/range/{hash_prefix}
    - Rate limit: 1 request per 1.6 seconds (enforced by RateLimitedSession)
    - Response: List of hash suffixes with breach counts
    """

    API_BASE_URL = "https://api.pwnedpasswords.com/range/"

    def __init__(
        self,
        cache_manager: EnrichmentCacheManager,
        rate_limiter: RateLimitedSession,
    ):
        """Initialize HIBP password enricher.
        
        Args:
            cache_manager: Cache manager for storing HIBP responses
            rate_limiter: Rate-limited HTTP session
        """
        self.cache_manager = cache_manager
        self.rate_limiter = rate_limiter
        self.stats = {
            'checks': 0,
            'cache_hits': 0,
            'cache_misses': 0,
            'api_calls': 0,
            'breached_found': 0,
            'errors': 0,
        }

    def check_password(self, password: str) -> Dict[str, Any]:
        """Check if password appears in HIBP database using k-anonymity.
        
        Args:
            password: The password to check
            
        Returns:
            Dictionary containing:
                - breached: Whether password appears in breaches (bool)
                - prevalence: Number of times seen in breaches (int)
                - cached: Whether result came from cache (bool)
                - error: Error message if check failed (str or None)
        """
        self.stats['checks'] += 1

        try:
            # Generate SHA-1 hash (HIBP requirement)
            sha1_hash = hashlib.sha1(password.encode('utf-8')).hexdigest().upper()
            prefix = sha1_hash[:5]
            suffix = sha1_hash[5:]

            # Check cache first
            cached_data = self.cache_manager.get_cached("hibp", prefix)
            if cached_data:
                self.stats['cache_hits'] += 1
                result = self._extract_result(cached_data, suffix, cached=True)
                if result['breached']:
                    self.stats['breached_found'] += 1
                return result

            # Cache miss - query HIBP API
            self.stats['cache_misses'] += 1
            self.stats['api_calls'] += 1

            try:
                response = self.rate_limiter.get(
                    f"{self.API_BASE_URL}{prefix}",
                    timeout=30.0,
                )
                response.raise_for_status()
            except requests.RequestException as e:
                logger.error(f"HIBP API request failed: {e}")
                self.stats['errors'] += 1
                return {
                    'breached': False,
                    'prevalence': 0,
                    'cached': False,
                    'error': str(e),
                }

            # Parse response
            hash_data = self._parse_response(response.text)

            # Cache the prefix results for future lookups
            self.cache_manager.store_cached("hibp", prefix, hash_data)

            # Extract result for this specific password
            result = self._extract_result(hash_data, suffix, cached=False)
            if result['breached']:
                self.stats['breached_found'] += 1
            
            return result

        except Exception as e:
            logger.error(f"Password check failed: {e}")
            self.stats['errors'] += 1
            return {
                'breached': False,
                'prevalence': 0,
                'cached': False,
                'error': str(e),
            }

    def _parse_response(self, response_text: str) -> Dict[str, int]:
        """Parse HIBP API response format.
        
        HIBP returns lines like:
            SUFFIX:COUNT
            00D4F6E8FA6EECAD2A3AA415EEC418D38EC:2
            011053FD0102E94D6AE2F8B83D76FAF94F6:1
            
        Args:
            response_text: Raw text from HIBP API
            
        Returns:
            Dictionary mapping hash suffixes to breach counts
        """
        hash_data = {}
        
        for line in response_text.strip().split('\n'):
            if not line or ':' not in line:
                continue
            
            try:
                suffix, count_str = line.split(':', 1)
                hash_data[suffix.strip()] = int(count_str.strip())
            except (ValueError, AttributeError) as e:
                logger.warning(f"Failed to parse HIBP line: {line} - {e}")
                continue
        
        return hash_data

    def _extract_result(
        self,
        hash_data: Dict[str, int],
        suffix: str,
        cached: bool,
    ) -> Dict[str, Any]:
        """Extract result for a specific password hash suffix.
        
        Args:
            hash_data: Dictionary of hash suffixes to breach counts
            suffix: The hash suffix to look up
            cached: Whether this data came from cache
            
        Returns:
            Dictionary with breach information
        """
        if suffix in hash_data:
            return {
                'breached': True,
                'prevalence': hash_data[suffix],
                'cached': cached,
                'error': None,
            }
        
        return {
            'breached': False,
            'prevalence': 0,
            'cached': cached,
            'error': None,
        }

    def get_stats(self) -> Dict[str, int]:
        """Get statistics about HIBP checks.
        
        Returns:
            Dictionary with check statistics
        """
        return dict(self.stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        for key in self.stats:
            self.stats[key] = 0


__all__ = ['HIBPPasswordEnricher']

