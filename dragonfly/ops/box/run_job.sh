#!/bin/bash
# Dragonfly box launcher (agent routines call this; no launchd, no cron).
#   run_job.sh prep                       15:30 CT: next session's prep
#   run_job.sh preopen --launch-engine    08:05 CT: READY, then the engine loop detached
#   run_job.sh watchdog                   ~08:28 CT: alert if cards/DONE is missing
# Extra args pass through (--date, --now, --dry-run-roots, ...). Roots come from
# DRAGONFLY_HANDOFF_ROOT / DRAGONFLY_INBOX_ROOT when set (e.g. handoff-boxtest).
# No wall-clock guard: the jobs decide sessions from dragonfly/market_calendar.py,
# and pre-open refuses to launch the engine after the 08:24 window end.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$HERE/box.env"
job="${1:?usage: run_job.sh prep|preopen|watchdog [args]}"; shift
case "$job" in prep|preopen|watchdog) ;; *) echo "unknown job $job" >&2; exit 2 ;; esac
stamp() { date '+%FT%T%z'; }
case "$(cd "$DRAGONFLY_RUN" && pwd -P)" in
  "$(cd "$DRAGONFLY_PIPELINE_ROOT" 2>/dev/null && pwd -P || echo /nonexistent)")
    echo "$(stamp) refusing: $DRAGONFLY_RUN is the site-pipeline checkout" >&2; exit 2 ;;
esac
mkdir -p "$DRAGONFLY_STATE_DIR/logs"
cd "$DRAGONFLY_RUN"
if [ "${DRAGONFLY_NO_PULL:-0}" != "1" ] && ! git pull --ff-only --quiet; then
  echo "$(stamp) run checkout $DRAGONFLY_RUN could not fast-forward; $job not run" >&2
  exit 2
fi
exec "$DRAGONFLY_PYTHON" -m dragonfly.jobs "$job" --repo "$DRAGONFLY_PRIVATE_DIR" "$@"
