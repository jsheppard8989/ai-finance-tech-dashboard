#!/usr/bin/env bash
# Catch-up: if it's after 10pm and we haven't run the evening pipeline today, run it now.
#
# Triggers (see docs/launchd/com.scarcity.pipeline.catchup.plist):
#   - RunAtLoad: once when the LaunchAgent loads (e.g. login). Before 22:00 local, exits immediately.
#   - StartCalendarInterval (if installed): daily ~22:10 backup on always-on machines — RunAtLoad alone
#     does NOT re-fire at 10pm if you never log out.
# If the Mac was asleep at 22:00, the next login after 22:00 can still run the pipeline.
# Requires run_evening_pipeline.sh and last_evening_run.txt written by auto_pipeline.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="$(cd "$SCRIPT_DIR/.." && pwd)"
PIPELINE="$SCRIPT_DIR"
STATE="${PIPELINE}/state"
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
LOG_DIR="${PIPELINE}/logs"
mkdir -p "$LOG_DIR"
nohup "${PIPELINE}/run_evening_pipeline.sh" 120 >> "${LOG_DIR}/pipeline_schedule.out" 2>> "${LOG_DIR}/pipeline_schedule.err" &
exit 0
