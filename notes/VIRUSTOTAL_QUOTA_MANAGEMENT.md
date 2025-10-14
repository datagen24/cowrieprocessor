# VirusTotal Quota Management Implementation

## Summary

This document describes the comprehensive improvements made to VirusTotal enrichment, including quota monitoring, better rate limiting, and integration with the official vt-py SDK.

## Changes Implemented

### 1. Added vt-py SDK Dependency
- Added `vt-py==0.21.0` to project dependencies
- Provides official VirusTotal API client with better error handling

### 2. Created VirusTotal Quota Management Module
**File:** `cowrieprocessor/enrichment/virustotal_quota.py`

**Features:**
- `QuotaInfo` dataclass: Tracks daily, hourly, and monthly quota usage
- `VirusTotalQuotaManager`: Monitors API quota via v3 endpoints
  - `/users/{id}/overall_quotas` - Get quota limits
  - `/users/{id}/api_usage` - Get current usage
  - Caching of quota information (default 5 minutes TTL)
  - Intelligent backoff recommendations based on usage percentage
  - Quota status reporting (healthy/warning/critical)

**Key Methods:**
- `get_quota_info()`: Fetch current quota usage
- `can_make_request()`: Check if safe to make API call (default 90% threshold)
- `get_backoff_time()`: Get recommended wait time based on usage
- `get_quota_summary()`: Get comprehensive quota status report

### 3. Created VirusTotal Handler with SDK Integration
**File:** `cowrieprocessor/enrichment/virustotal_handler.py`

**Features:**
- Uses official vt-py SDK for API calls
- Integrated quota management
- Enhanced caching (saves responses as `vt_{hash}.json`)
- Proper error handling for:
  - `NotFoundError` - File not in VirusTotal database
  - `QuotaExceededError` - Quota limit reached
  - Other API errors with retry logic
- Automatic backoff when quota threshold exceeded

**Key Methods:**
- `enrich_file()`: Main enrichment method with caching
- `extract_analysis_stats()`: Extract key statistics from VT response
- `is_malicious()`: Determine if file is malicious (configurable threshold)
- `get_quota_status()`: Get current quota status

### 4. Fixed Rate Limiting Implementation
**File:** `cowrieprocessor/enrichment/rate_limiting.py`

**Improvements:**
- Added synchronous `acquire_sync()` method to avoid async context issues
- Fixed rate limiter to work properly in both async and sync contexts
- Proper token bucket implementation with burst handling

**Rate Limits:**
- VirusTotal: 0.067 requests/sec (4 per minute) with burst of 1
- DShield: 1.0 requests/sec with burst of 2
- URLHaus: 2.0 requests/sec with burst of 3
- SPUR: 1.0 requests/sec with burst of 2

### 5. Updated EnrichmentService Integration
**File:** `enrichment_handlers.py`

**Changes:**
- Added `enable_vt_quota_management` parameter (default: True)
- Integrated `VirusTotalHandler` for file enrichment
- Added `get_vt_quota_status()` method
- Added `close()` method for proper cleanup
- Backward compatible with existing code

**Usage:**
```python
service = EnrichmentService(
    cache_dir=cache_dir,
    vt_api="your-api-key",
    dshield_email=None,
    urlhaus_api=None,
    spur_api=None,
    enable_vt_quota_management=True,  # Enable quota monitoring
)

# Check quota status
quota_status = service.get_vt_quota_status()
print(f"Status: {quota_status['status']}")
print(f"Daily remaining: {quota_status['daily']['remaining']}")
print(f"Hourly remaining: {quota_status['hourly']['remaining']}")

# Enrich file
result = service.enrich_file(file_hash, filename)

# Cleanup
service.close()
```

### 6. Comprehensive Test Coverage
**Test Files:**
- `tests/unit/test_virustotal_quota.py` - Quota management tests (10 tests, all passing)
- `tests/unit/test_virustotal_handler.py` - Handler tests (24 tests, all passing)
- `tests/integration/test_virustotal_integration.py` - Integration tests

**Test Coverage:**
- Quota info retrieval and caching
- Quota threshold checking
- Backoff time calculation
- File enrichment with caching
- Error handling (NotFound, QuotaExceeded, etc.)
- Analysis stats extraction
- Malicious file detection

## Benefits

### 1. Proactive Quota Management
- Monitor quota usage in real-time
- Prevent hitting API limits
- Intelligent backoff when approaching limits
- Avoid service disruptions

### 2. Better Rate Limiting
- Fixed async context issues
- Proper token bucket implementation
- Per-service rate limiting
- Burst handling for occasional spikes

### 3. Improved Error Handling
- Specific handling for quota errors
- Exponential backoff for retries
- Graceful degradation when quota exceeded
- Better logging and diagnostics

### 4. Enhanced Caching
- Persistent caching of VT responses
- Reduces API calls
- Faster lookups for known hashes
- Cache format: `vt_{hash}.json`

### 5. Official SDK Benefits
- Better API client implementation
- Automatic handling of API changes
- Improved error messages
- Community-maintained

## Monitoring Quota Usage

### Check Current Status
```python
from enrichment_handlers import EnrichmentService

service = EnrichmentService(
    cache_dir="/path/to/cache",
    vt_api="your-api-key",
    enable_vt_quota_management=True,
)

quota_status = service.get_vt_quota_status()

print(f"Status: {quota_status['status']}")  # healthy/warning/critical
print(f"Daily: {quota_status['daily']['used']}/{quota_status['daily']['limit']}")
print(f"Hourly: {quota_status['hourly']['used']}/{quota_status['hourly']['limit']}")
print(f"Can make request: {quota_status['can_make_request']}")
print(f"Recommended backoff: {quota_status['recommended_backoff']}s")
```

### Quota Thresholds
- **Healthy**: < 80% usage
- **Warning**: 80-95% usage (30-minute backoff)
- **Critical**: ≥ 95% usage (1-hour backoff)

### Daily Limits
- **Public API**: 500 requests/day, 4 requests/minute
- Monitor usage to stay within limits
- Cache aggressively to reduce API calls
- Use quota monitoring to prevent overages

## Migration Guide

### Existing Code
No changes required! The new implementation is backward compatible with existing code.

### New Code
To use the new quota management features:

```python
# Enable quota management (default: True)
service = EnrichmentService(
    cache_dir=cache_dir,
    vt_api=api_key,
    enable_vt_quota_management=True,
)

# Check quota before batch operations
quota_status = service.get_vt_quota_status()
if quota_status['can_make_request']:
    # Safe to proceed
    result = service.enrich_file(file_hash, filename)
else:
    # Quota threshold exceeded, wait or skip
    backoff_time = quota_status['recommended_backoff']
    print(f"Waiting {backoff_time}s before retry...")
```

## Configuration

### Environment Variables
```bash
# VirusTotal API key
export COWRIEPROC_VT_API="your-api-key"

# Cache directory (optional)
export COWRIEPROC_CACHE_DIR="/path/to/cache"
```

### Quota Threshold
Default: 90% (don't make requests if usage exceeds 90%)

To customize:
```python
from cowrieprocessor.enrichment.virustotal_handler import VirusTotalHandler

handler = VirusTotalHandler(
    api_key=api_key,
    cache_dir=cache_dir,
    quota_threshold_percent=85.0,  # Custom threshold
)
```

## Troubleshooting

### Quota Exceeded Errors
1. Check quota status: `service.get_vt_quota_status()`
2. Wait for recommended backoff time
3. Consider reducing enrichment rate
4. Use caching aggressively

### Rate Limiting Issues
1. Verify rate limits in `SERVICE_RATE_LIMITS`
2. Check burst settings
3. Monitor request timing
4. Adjust rate limits if needed

### Cache Issues
1. Verify cache directory exists and is writable
2. Check disk space
3. Clear old cache files if needed
4. Cache files are named: `vt_{sha256}.json`

## Performance Considerations

### Cache Hit Rate
- High cache hit rate = fewer API calls
- Monitor cache effectiveness
- Adjust cache TTL if needed

### Quota Usage
- Monitor daily/hourly usage
- Stay well below limits (< 80%)
- Use quota warnings to adjust behavior
- Plan batch operations carefully

### Rate Limiting
- Respect API rate limits
- Use burst capacity sparingly
- Distribute requests over time
- Consider async processing for large batches

## Future Enhancements

1. **Persistent Quota Tracking**
   - Store quota history in database
   - Track usage patterns over time
   - Predictive quota management

2. **Multi-Key Support**
   - Rotate between multiple API keys
   - Load balancing across keys
   - Increased throughput

3. **Smarter Caching**
   - TTL-based cache expiration
   - LRU cache eviction
   - Cache warmup strategies

4. **Enhanced Monitoring**
   - Prometheus metrics
   - Grafana dashboards
   - Alert integration

5. **Batch Operations**
   - Bulk file submissions
   - Batch quota checking
   - Optimized API usage

## References

- [VirusTotal API v3 Documentation](https://docs.virustotal.com/reference/overview)
- [vt-py GitHub Repository](https://github.com/VirusTotal/vt-py)
- [Quota Consumption Guide](https://virustotal.readme.io/docs/quota-consumption)
- [API Usage Endpoint](https://virustotal.readme.io/docs/user-object-api-quota-group)

## Testing

### Run Unit Tests
```bash
uv run pytest tests/unit/test_virustotal_quota.py -v
uv run pytest tests/unit/test_virustotal_handler.py -v
```

### Run Integration Tests
```bash
uv run pytest tests/integration/test_virustotal_integration.py -v
```

### Coverage
```bash
uv run pytest --cov=cowrieprocessor.enrichment --cov-report=html
```

## Support

For issues or questions:
1. Check this documentation
2. Review test cases for usage examples
3. Check logs for error details
4. Open an issue with details

## Changelog

### Version 1.0 (Current)
- Initial implementation of quota management
- Integration of vt-py SDK
- Fixed rate limiting issues
- Added comprehensive tests
- Backward compatible with existing code
