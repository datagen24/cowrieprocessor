#!/usr/bin/env bash
# Run process_cowrie.py with unbuffered output and capture logs to a timestamped file.
set -euo pipefail

LOG_DIR=${LOG_DIR:-debug-logs}
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date '+%Y%m%d-%H%M%S')
LOG_FILE="$LOG_DIR/process_cowrie-$TIMESTAMP.log"

printf 'Debug log: %s\n' "$LOG_FILE"

# Ensure Python output is unbuffered so tee captures it in realtime.
PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 uv run python -u process_cowrie.py "$@" 2>&1 | tee "$LOG_FILE"
