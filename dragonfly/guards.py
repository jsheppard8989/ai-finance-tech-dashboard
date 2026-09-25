"""Load guards for Dragonfly data pulls. Dragonfly must never overlap the site pipeline.

Two checks, both fail closed:

1. Pipeline lock. While the site pipeline's lock file is held by a live PID,
   Dragonfly refuses to fetch. Entry points wait a bounded time, then abort.
   Default lock paths (the pipeline writes the first; the second is also
   honoured):
     /Users/jaredsheppard/projects/ai-finance-tech-dashboard/pipeline/state/auto_pipeline.lock
     /Users/jaredsheppard/projects/ai-finance-tech-dashboard/pipeline/auto_pipeline.lock
   Override with DRAGONFLY_PIPELINE_LOCK (one path, or several joined by os.pathsep).
   A lock whose PID cannot be read counts as held. A lock whose PID is dead is stale.

2. Daemon windows. The pipeline daemon runs inside 05:00-07:59, 12:00-14:59 and
   22:00-23:59 America/Chicago. Dragonfly refuses to fetch inside them unless
   DRAGONFLY_ALLOW_DAEMON_WINDOW=1 (or the CLI flag --allow-daemon-window).

`preflight()` runs both at an entry point (bounded wait on the lock).
`before_fetch()` runs both, without waiting, right before every network call,
so a pipeline that starts mid-run stops Dragonfly at the next request.

Recommended pre-open start: 08:05 CT (after the morning window closes and the
morning publish has landed; before the 08:30 CT open).
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

PIPELINE_ROOT = Path("/Users/jaredsheppard/projects/ai-finance-tech-dashboard")
DEFAULT_LOCKS = (
    PIPELINE_ROOT / "pipeline" / "state" / "auto_pipeline.lock",
    PIPELINE_ROOT / "pipeline" / "auto_pipeline.lock",
)
ENV_LOCK = "DRAGONFLY_PIPELINE_LOCK"
ENV_ALLOW_WINDOW = "DRAGONFLY_ALLOW_DAEMON_WINDOW"
ENV_LOCK_WAIT = "DRAGONFLY_LOCK_WAIT_SECONDS"
DEFAULT_LOCK_WAIT_SECONDS = 300
LOCK_POLL_SECONDS = 10
# (start_hour, start_minute, end_hour, end_minute), inclusive, America/Chicago
DAEMON_WINDOWS = ((5, 0, 7, 59), (12, 0, 14, 59), (22, 0, 23, 59))
TZ = "America/Chicago"
RECOMMENDED_PREOPEN_CT = "08:05"


class GuardBlocked(RuntimeError):
    """Reasons: pipeline_running, daemon_window."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        self.detail = detail
        super().__init__(f"{reason}{(': ' + detail) if detail else ''}")


def lock_paths() -> List[Path]:
    raw = os.environ.get(ENV_LOCK)
    if raw:
        return [Path(p) for p in raw.split(os.pathsep) if p]
    return list(DEFAULT_LOCKS)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def lock_holder(path: Path) -> Optional[str]:
    """None when free (missing file or dead PID); otherwise a description."""
    try:
        raw = path.read_text(encoding="utf-8", errors="replace").strip()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{path} unreadable ({exc})"
    first = raw.split()[0] if raw.split() else ""
    if not first.isdigit():
        return f"{path} held (pid unreadable: {raw[:40]!r})"
    pid = int(first)
    return f"{path} held by live pid {pid}" if _pid_alive(pid) else None


def pipeline_busy() -> Optional[str]:
    for path in lock_paths():
        holder = lock_holder(path)
        if holder:
            return holder
    return None


def _now_ct() -> datetime:
    from zoneinfo import ZoneInfo

    return datetime.now(ZoneInfo(TZ))


def daemon_window(now_ct: Optional[datetime] = None) -> Optional[str]:
    now_ct = now_ct or _now_ct()
    hm = (now_ct.hour, now_ct.minute)
    for sh, sm, eh, em in DAEMON_WINDOWS:
        if (sh, sm) <= hm <= (eh, em):
            return f"{sh:02d}:{sm:02d}-{eh:02d}:{em:02d} CT"
    return None


def window_override() -> bool:
    return os.environ.get(ENV_ALLOW_WINDOW, "").strip().lower() in ("1", "true", "yes")


def check_schedule(now_ct: Optional[datetime] = None, allow: Optional[bool] = None) -> None:
    allow = window_override() if allow is None else allow
    if allow:
        return
    window = daemon_window(now_ct)
    if window:
        raise GuardBlocked(
            "daemon_window",
            f"inside pipeline daemon window {window}; set {ENV_ALLOW_WINDOW}=1 to override",
        )


def check_pipeline(
    wait_seconds: float = 0,
    poll_seconds: float = LOCK_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    deadline = clock() + max(0.0, wait_seconds)
    while True:
        busy = pipeline_busy()
        if not busy:
            return
        if clock() >= deadline:
            raise GuardBlocked("pipeline_running", busy)
        sleep(min(poll_seconds, max(0.01, deadline - clock())))


def preflight(
    wait_seconds: Optional[float] = None,
    now_ct: Optional[datetime] = None,
    allow_window: Optional[bool] = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """Entry-point guard: schedule, then a bounded wait on the pipeline lock."""
    if wait_seconds is None:
        wait_seconds = float(os.environ.get(ENV_LOCK_WAIT, DEFAULT_LOCK_WAIT_SECONDS))
    check_schedule(now_ct, allow_window)
    check_pipeline(wait_seconds, sleep=sleep, clock=clock)


def before_fetch() -> None:
    """Per-request guard. No waiting: raise immediately if unsafe."""
    check_schedule()
    check_pipeline(0)
