#!/usr/bin/env bash
# Wrapper for orchestrate_sensors.py with unbuffered output and log capture.
set -euo pipefail

LOG_DIR=${LOG_DIR:-debug-logs}
mkdir -p "$LOG_DIR"
STAMP=$(date '+%Y%m%d-%H%M%S')
LOG_FILE="$LOG_DIR/orchestrate-$STAMP.log"

printf 'Debug log: %s\n' "$LOG_FILE"

PYTHONFAULTHANDLER=1 PYTHONUNBUFFERED=1 uv run python -u orchestrate_sensors.py "$@" 2>&1 | tee "$LOG_FILE"
