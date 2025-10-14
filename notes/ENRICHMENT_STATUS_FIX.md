# Enrichment Refresh Status File Fix

## Issue
The `enrichment_refresh.py` utility was not updating status files, causing `monitor_progress.py` to not show any changes while the enrichment refresh was running.

## Root Cause
The `enrichment_refresh.py` script was only updating the database directly and printing progress to stdout. It was not using the `StatusEmitter` class to create status files that `monitor_progress.py` could monitor.

The `monitor_progress.py` script looks for JSON status files in `/mnt/dshield/data/logs/status/` and expects them to have specific structure with phases, metrics, and progress information.

## Solution
Added `StatusEmitter` integration to `enrichment_refresh.py` to create status files that can be monitored by `monitor_progress.py`.

### Changes Made

#### 1. Import StatusEmitter
```python
from cowrieprocessor.status_emitter import StatusEmitter
```

#### 2. Initialize StatusEmitter
```python
# Initialize status emitter for progress monitoring
status_emitter = StatusEmitter("enrichment_refresh")
```

#### 3. Record Initial Status
```python
# Record initial status
status_emitter.record_metrics({
    "sessions_processed": 0,
    "files_processed": 0,
    "sessions_total": session_limit if session_limit > 0 else "unlimited",
    "files_total": file_limit if file_limit > 0 else "unlimited",
})
```

#### 4. Update Status During Processing
Added status updates every 10 items or every 30 seconds during both session and file processing:

```python
# Update status every 10 items or every 30 seconds
if (session_count % 10 == 0 or 
    time.time() - last_status_update > 30):
    status_emitter.record_metrics({
        "sessions_processed": session_count,
        "files_processed": file_count,
        "sessions_total": session_limit if session_limit > 0 else "unlimited",
        "files_total": file_limit if file_limit > 0 else "unlimited",
    })
    last_status_update = time.time()
```

#### 5. Record Final Status
```python
# Record final status
status_emitter.record_metrics({
    "sessions_processed": session_count,
    "files_processed": file_count,
    "sessions_total": session_limit if session_limit > 0 else "unlimited",
    "files_total": file_limit if file_limit > 0 else "unlimited",
    "cache_snapshot": cache_manager.snapshot(),
})
```

## Status File Structure
The status files will now be created at `/mnt/dshield/data/logs/status/enrichment_refresh.json` with the following structure:

```json
{
  "phase": "enrichment_refresh",
  "ingest_id": null,
  "last_updated": "2025-01-XX...",
  "metrics": {
    "sessions_processed": 150,
    "files_processed": 38,
    "sessions_total": "unlimited",
    "files_total": "unlimited"
  },
  "checkpoint": {},
  "dead_letter": {"total": 0}
}
```

## Benefits
1. **Real-time Monitoring**: `monitor_progress.py` can now track progress in real-time
2. **Consistent Interface**: Uses the same status file format as other scripts
3. **Detailed Metrics**: Shows both session and file processing progress
4. **Non-intrusive**: Doesn't change existing functionality, only adds status updates

## Testing
To verify the fix works:

1. **Run enrichment refresh**:
   ```bash
   uv run scripts/enrichment_refresh.py --cache-dir /mnt/dshield/data/cache --files 10
   ```

2. **Monitor progress in another terminal**:
   ```bash
   python3 monitor_progress.py
   ```

3. **Check status file directly**:
   ```bash
   cat /mnt/dshield/data/logs/status/enrichment_refresh.json
   ```

## Expected Behavior
- `monitor_progress.py` should now show updates every 10 processed items or every 30 seconds
- Status file should be created and updated during processing
- Final status should show completion with total counts
- No impact on existing functionality or performance

## Files Modified
- `scripts/enrichment_refresh.py`: Added StatusEmitter integration

## Related Files
- `monitor_progress.py`: Monitors status files (no changes needed)
- `cowrieprocessor/status_emitter.py`: Provides status file functionality (no changes needed)
