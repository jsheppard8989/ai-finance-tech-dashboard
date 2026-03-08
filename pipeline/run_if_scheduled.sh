#!/usr/bin/env bash
# Run by LaunchDaemon every 5 minutes. If we're in the 10pm or 5am window and
# haven't run in the last 90 minutes, run the pipeline. Multiple chances so we
# don't rely on one exact minute.
set -e
WORKSPACE="${HOME}/.openclaw/workspace"
STATE="${WORKSPACE}/pipeline/state"
MARKER="${STATE}/last_evening_run.txt"
LOG_DIR="${WORKSPACE}/pipeline/logs"
mkdir -p "$LOG_DIR" "$STATE"
exec >> "${LOG_DIR}/pipeline_schedule.out" 2>> "${LOG_DIR}/pipeline_schedule.err"

# Heartbeat: so we can see the daemon is firing (check state/daemon_last_check.txt)
echo "$(date -Iseconds)" > "${STATE}/daemon_last_check.txt"

HOUR=$(date +%H | sed 's/^0//')
MIN=$(date +%M | sed 's/^0//')

# 10pm window: 22:00-22:20
# 5am window: 05:00-05:20
in_window=0
if [ "$HOUR" -eq 22 ] && [ "$MIN" -le 20 ]; then
  in_window=1
fi
if [ "$HOUR" -eq 5 ] && [ "$MIN" -le 20 ]; then
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
"${WORKSPACE}/pipeline/run_evening_pipeline.sh" 120
