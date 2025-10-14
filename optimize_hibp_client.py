#!/usr/bin/env python3
"""Optimize HIBP client with better error handling and retry logic."""

from __future__ import annotations


def improve_hibp_client():
    """Add retry logic and better error handling to HIBP client."""
    # Create a patch for the HIBP client's check_password method
    patch_code = '''
def check_password_with_retry(self, password: str) -> Dict[str, Any]:
    """Check password with retry logic for connection errors."""
    self.stats['checks'] += 1

    try:
        # Generate SHA-1 hash (HIBP requirement)
        import hashlib
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

        # Cache miss - query HIBP API with retry
        self.stats['cache_misses'] += 1
        self.stats['api_calls'] += 1

        max_retries = 3
        retry_delay = 2.0  # Start with 2 seconds

        for attempt in range(max_retries):
            try:
                response = self.rate_limiter.get(
                    f"{self.API_BASE_URL}{prefix}",
                    timeout=30.0,
                )
                response.raise_for_status()
                
                # Success - parse and cache response
                hash_data = self._parse_response(response.text)
                self.cache_manager.store_cached("hibp", prefix, hash_data)
                
                result = self._extract_result(hash_data, suffix, cached=False)
                if result['breached']:
                    self.stats['breached_found'] += 1
                return result
                
            except (requests.exceptions.ConnectionError, 
                    requests.exceptions.Timeout,
                    ConnectionResetError) as e:
                if attempt < max_retries - 1:
                    # Exponential backoff with jitter
                    import random
                    delay = retry_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
        f"HIBP API connection error (attempt {attempt + 1}/{max_retries}): {e}. "
        f"Retrying in {delay:.1f}s..."
    )
                    time.sleep(delay)
                    continue
                else:
                    # Final attempt failed
                    logger.error(f"HIBP API request failed after {max_retries} attempts: {e}")
                    self.stats['errors'] += 1
                    return {
                        'breached': False,
                        'prevalence': 0,
                        'cached': False,
                        'error': str(e),
                    }
            except requests.RequestException as e:
                # Non-retryable error (e.g., 4xx, 5xx status codes)
                logger.error(f"HIBP API request failed: {e}")
                self.stats['errors'] += 1
                return {
                    'breached': False,
                    'prevalence': 0,
                    'cached': False,
                    'error': str(e),
                }

    except Exception as e:
        logger.error(f"Unexpected error in password check: {e}")
        self.stats['errors'] += 1
        return {
            'breached': False,
            'prevalence': 0,
            'cached': False,
            'error': str(e),
        }
'''
    
    print("HIBP Client Optimization Patch:")
    print("=" * 50)
    print(patch_code)
    print("=" * 50)
    print()
    print("This patch adds:")
    print("• Retry logic for connection errors (3 attempts)")
    print("• Exponential backoff with jitter")
    print("• Better error categorization")
    print("• Detailed logging of retry attempts")
    print()
    print("To apply this optimization:")
    print("1. Stop the current enrichment process (Ctrl+C)")
    print("2. Apply this patch to cowrieprocessor/enrichment/hibp_client.py")
    print("3. Restart the enrichment process")
    print()
    print("The process will continue from where it left off with better resilience.")


if __name__ == "__main__":
    improve_hibp_client()
