#!/usr/bin/env bash
# Wrapper for evening pipeline: prevent sleep during run, then run auto_pipeline.
# Used by launchd so the Mac stays awake for the full duration.
# Usage: run_evening_pipeline.sh [max_minutes]
# Default max: 120 minutes (2 hours).

set -e
WORKSPACE="${HOME}/.openclaw/workspace"
PIPELINE="${WORKSPACE}/pipeline"
MAX_MINUTES="${1:-120}"

cd "$PIPELINE"
# -s = prevent system sleep; -i = prevent idle sleep; -t = timeout seconds
exec /usr/bin/caffeinate -s -i -t $((MAX_MINUTES * 60)) -- /usr/bin/env python3 "$PIPELINE/auto_pipeline.py"
