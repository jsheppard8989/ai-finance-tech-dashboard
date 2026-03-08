#!/usr/bin/env bash
# Catch-up: if it's after 10pm and we haven't run the evening pipeline today, run it now.
# Install as a LaunchAgent with RunAtLoad=true so it runs on login/wake; if the Mac was
# asleep at 22:00, the next time you open the laptop it will run the pipeline.
# Requires run_evening_pipeline.sh and last_evening_run.txt written by auto_pipeline.

WORKSPACE="${HOME}/.openclaw/workspace"
STATE="${WORKSPACE}/pipeline/state"
MARKER="${STATE}/last_evening_run.txt"
NOW=$(date +%Y-%m-%d)
HOUR=$(date +%H)

# Only run after 10pm
if [ "$(printf '%d' "$HOUR")" -lt 22 ]; then
  exit 0
fi

# Already ran today?
if [ -f "$MARKER" ]; then
  LAST=$(head -1 "$MARKER" | cut -d' ' -f1)
  if [ "$LAST" = "$NOW" ]; then
    exit 0
  fi
fi

# Run the evening pipeline in the background so we don't block login
# Logs go to the same place as the scheduled run
LOG_DIR="${WORKSPACE}/pipeline/logs"
mkdir -p "$LOG_DIR"
nohup "${WORKSPACE}/pipeline/run_evening_pipeline.sh" 120 >> "${LOG_DIR}/pipeline_schedule.out" 2>> "${LOG_DIR}/pipeline_schedule.err" &
exit 0
