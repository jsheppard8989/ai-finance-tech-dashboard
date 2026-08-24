#!/usr/bin/env bash
# Run by com.scarcity.pipeline.daemon every 45 minutes. If we're inside a run
# window and the pipeline has not run in the last 90 minutes, run it. Wide windows
# + frequent checks avoid missing the narrow slot when the clock ticks.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
PIPELINE="$SCRIPT_DIR"
STATE="${PIPELINE}/state"
MARKER="${STATE}/last_evening_run.txt"
LOG_DIR="${PIPELINE}/logs"
mkdir -p "$LOG_DIR" "$STATE"
exec >> "${LOG_DIR}/pipeline_schedule.out" 2>> "${LOG_DIR}/pipeline_schedule.err"

# Heartbeat: so we can see the daemon is firing (check state/daemon_last_check.txt)
echo "$(date -Iseconds)" > "${STATE}/daemon_last_check.txt"

HOUR=$(date +%H | sed 's/^0//')
MIN=$(date +%M | sed 's/^0//')

# Morning: 05:00–07:59
# Midday: 12:00–14:59
# Evening: 22:00–23:59
in_window=0
if [ "$HOUR" -ge 5 ] && [ "$HOUR" -le 7 ]; then
  in_window=1
fi
if [ "$HOUR" -ge 12 ] && [ "$HOUR" -le 14 ]; then
  in_window=1
fi
if [ "$HOUR" -ge 22 ] && [ "$HOUR" -le 23 ]; then
  in_window=1
fi
[ "$in_window" -eq 0 ] && exit 0

# Already ran in last 90 minutes?
if [ -f "$MARKER" ]; then
  # Marker has "YYYY-MM-DD HH:MM" - get mtime or parse
  mtime=$(stat -f %m "$MARKER" 2>/dev/null || stat -c %Y "$MARKER" 2>/dev/null || echo 0)
  now=$(date +%s)
  if [ $((now - mtime)) -lt 5400 ]; then
    exit 0
  fi
fi

echo "$(date -Iseconds) run_if_scheduled: in window, running pipeline"
"${PIPELINE}/run_evening_pipeline.sh" 120
