"""One-shot box session: `run_job.sh session` (Ditka 2026-09-28).

A routine fires ONE command any time from ~07:10 to 07:45 CT on the session
day. It returns in seconds; a fully detached chain (double fork + setsid) then
runs, in order:

  1. prep     (skipped when <root>/<date>/prep.json already exists)
  2. preopen --launch-engine   (quotes, book, READY, then the engine runner,
     detached; the engine pushes ENGINE_STARTED at once and sleeps until the
     08:08 window, cards until the 08:20 cutoff, DONE, exits by 08:24)
  3. watchdog at the window end + 3 min (08:27 CT)

The box runs pre-open early on purpose: box.env sets DRAGONFLY_DAEMON_WINDOWS
=none (no Mac pipeline here), and the pre-open job has no earliest-time rule,
so ENGINE_STARTED is pushed ~1 minute after the fire, well before 07:50, while
the engine still honours the 08:08 window and 08:20 cutoff. Pre-market quotes
are the ones fetched at the fire (quotes.json fetched_at_real says when).

Idempotent: a fire is refused when this date/root already has a session marker
(state/engine/session-<date>.<root>.json, created O_EXCL), a live runner, or
an ENGINE_STARTED (local clone or origin). The live handoff/ root is refused.

`session-stop` kills the chain, the runner (SIGKILL first, so it cannot push
ENGINE_EXIT) and the engine; `session-status` shows it all.
--sim-start ISO runs the same chain on a shifted clock (smoke tests).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional

from dragonfly.engine import core
from dragonfly.jobs import engine_runner

WATCH_AFTER_END = engine_runner.WATCHDOG_GRACE
SLEEP_CHUNK = 15.0


class SessionRefused(core.EngineError):
    pass


def marker_file(state: Path, session_date: date, handoff_root: str) -> Path:
    return Path(state) / "engine" / f"session-{session_date.isoformat()}.{handoff_root}.json"


def session_log(state: Path, session_date: date, handoff_root: str) -> Path:
    return Path(state) / "logs" / f"session-{session_date.isoformat()}.{handoff_root}.log"


def _read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write(path: Path, doc: dict) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(core.dumps(doc), encoding="utf-8")
    os.replace(tmp, path)


def started_rel(session_date: date, handoff_root: str) -> str:
    return f"{handoff_root}/{session_date.isoformat()}/cards/ENGINE_STARTED"


def engine_started(repo: Path, session_date: date, handoff_root: str, remote: bool = True) -> Optional[str]:
    """Where ENGINE_STARTED exists for this date/root: 'local', 'origin', or None."""
    rel = started_rel(session_date, handoff_root)
    if (Path(repo) / rel).exists():
        return "local"
    if remote:
        subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin"], capture_output=True, timeout=60)
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "origin/HEAD"],
                              capture_output=True, text=True).stdout.strip() or "origin/main"
        if subprocess.run(["git", "-C", str(repo), "cat-file", "-e", f"{head}:{rel}"],
                          capture_output=True).returncode == 0:
            return "origin"
    return None


def check_can_fire(repo: Path, session_date: date, handoff_root: str, state: Path, remote: bool = True) -> None:
    if handoff_root == core.DEFAULT_HANDOFF_ROOT:
        raise SessionRefused("refusing the live handoff/ root on the box (set DRAGONFLY_HANDOFF_ROOT, e.g. handoff-practice)")
    mf = marker_file(state, session_date, handoff_root)
    if mf.exists():
        raise SessionRefused(f"a session for {session_date} / {handoff_root} was already fired: {mf} "
                             f"({_read(mf).get('status', '?')}); not starting a second one")
    info = _read(engine_runner.runner_file(state, session_date, handoff_root))
    if engine_runner._alive(info.get("runner_pid")):
        raise SessionRefused(f"a runner for {session_date} / {handoff_root} is alive (pid {info['runner_pid']})")
    where = engine_started(repo, session_date, handoff_root, remote=remote)
    if where:
        raise SessionRefused(f"{started_rel(session_date, handoff_root)} already exists ({where}); refusing")


def _claim(mf: Path, doc: dict) -> None:
    mf.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(str(mf), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise SessionRefused(f"a session marker appeared concurrently: {mf}") from exc
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(core.dumps(doc))


def fire(repo: Path, session_date: date, handoff_root: str, inbox_root: str, state: Path, *,
         sim_start: Optional[str] = None, python: Optional[str] = None, spawn: Callable = engine_runner.spawn_detached,
         real_now: Callable[[], datetime] = core.now_ct, remote: bool = True) -> dict:
    """Refuse or claim, then start the detached chain. Returns in seconds."""
    check_can_fire(repo, session_date, handoff_root, state, remote=remote)
    python = python or sys.executable
    mf = marker_file(state, session_date, handoff_root)
    log = session_log(state, session_date, handoff_root)
    fired = core.iso(real_now().replace(microsecond=0))
    doc = {"marker": "SESSION", "session_date": session_date.isoformat(), "handoff_root": handoff_root,
           "inbox_root": inbox_root, "fired_at": fired, "sim_start": sim_start, "status": "starting",
           "log": str(log), "engine_log": str(engine_runner.default_log(state, session_date, handoff_root)),
           "engine_started": started_rel(session_date, handoff_root)}
    _claim(mf, doc)
    argv = [python, "-m", "dragonfly.jobs", "session-chain", "--repo", str(repo), "--date", session_date.isoformat(),
            "--state-dir", str(state), "--fired-at", fired]
    if sim_start:
        argv += ["--sim-start", sim_start]
    env = dict(os.environ, DRAGONFLY_STATE_DIR=str(state), DRAGONFLY_HANDOFF_ROOT=handoff_root,
               DRAGONFLY_INBOX_ROOT=inbox_root)
    try:
        pid = spawn(argv, log, core.ROOT, env)
    except Exception:
        doc["status"] = "spawn_failed"
        _write(mf, doc)
        raise
    doc.update(chain_pid=pid, status="running")
    _write(mf, doc)
    return doc


# ------------------------------------------------------------------ chain
def _sim(sim_start: Optional[str], fired_at: datetime, real: datetime) -> Optional[datetime]:
    if not sim_start:
        return None
    return core.parse_iso(sim_start) + (real - fired_at)


def run_chain(repo: Path, session_date: date, state: Path, fired_at: str, sim_start: Optional[str] = None,
              python: Optional[str] = None, run: Callable = subprocess.run,
              real_now: Callable[[], datetime] = core.now_ct, sleep: Callable[[float], None] = time.sleep) -> int:
    python = python or sys.executable
    handoff_root, inbox_root = core.resolve_roots(None, None, False)
    mf = marker_file(state, session_date, handoff_root)
    ds = session_date.isoformat()
    fired = core.parse_iso(fired_at)

    def say(msg: str) -> None:
        print(f"{core.iso(real_now().replace(microsecond=0))} session {ds} {handoff_root}: {msg}", flush=True)

    def mark(**kw) -> None:
        doc = _read(mf)
        doc.update(kw)
        _write(mf, doc)

    def job(name: str, *extra: str) -> int:
        argv = [python, "-m", "dragonfly.jobs", name, "--repo", str(repo), "--date", ds, "--state-dir", str(state), *extra]
        sim = _sim(sim_start, fired, real_now())
        if sim is not None and name != "prep":
            argv += ["--now", core.iso(sim.replace(microsecond=0))]
        say("run " + " ".join(argv[3:]))
        rc = run(argv, cwd=str(core.ROOT)).returncode
        say(f"{name} exit {rc}")
        return rc

    say(f"chain pid {os.getpid()} (fired {fired_at}{', sim start ' + sim_start if sim_start else ''})")
    if (Path(repo) / handoff_root / ds / "prep.json").exists():
        say("prep.json already present; prep skipped")
    elif job("prep") != 0:
        mark(status="failed", failed_step="prep")
        say("FAILED at prep; no pre-open, no engine")
        return 2
    mark(status="prep_done")
    if job("preopen", "--launch-engine") != 0:
        mark(status="failed", failed_step="preopen")
        say("FAILED at pre-open; no engine")
        return 2
    info = _read(engine_runner.runner_file(state, session_date, handoff_root))
    mark(status="engine_launched", runner_pid=info.get("runner_pid"), engine_pid=info.get("engine_pid"))
    # watchdog at the window end + grace, on the chain's clock
    watch_at_sim = datetime.combine(session_date, core.parse_hhmm(core.DEFAULT_END), tzinfo=core.tz()) + WATCH_AFTER_END
    if sim_start:
        watch_real = fired + (watch_at_sim - core.parse_iso(sim_start))
    else:
        watch_real = watch_at_sim
    deadline = watch_real + timedelta(seconds=5)
    wait = (deadline - real_now()).total_seconds()
    mark(watchdog_at=core.iso(watch_real.replace(microsecond=0)))
    say(f"watchdog armed for {core.iso(watch_real.replace(microsecond=0))} (sleeping {max(0, int(wait))}s)")
    # wall-clock sleep in 15 s chunks: a suspended box stops monotonic time
    for _ in range(int(max(0.0, wait) // SLEEP_CHUNK) + 2):
        remaining = (deadline - real_now()).total_seconds()
        if remaining <= 0:
            break
        sleep(min(remaining, SLEEP_CHUNK))
    rc = job("watchdog")
    mark(status="complete" if rc == 0 else "watchdog_alert", watchdog_exit=rc)
    return 0 if rc == 0 else 1


# ------------------------------------------------------------------ stop / status
def _kill(pid: Optional[int], sig: int, group: bool = False) -> str:
    if not pid:
        return "none"
    try:
        if group:
            os.killpg(os.getpgid(int(pid)), sig)
        else:
            os.kill(int(pid), sig)
        return "killed"
    except ProcessLookupError:
        return "not_running"
    except PermissionError:
        return "permission_denied"


def stop(session_date: date, handoff_root: str, state: Path) -> dict:
    """Kill the chain (its whole process group: prep/preopen/sleep), then the
    runner with SIGKILL (so it cannot push ENGINE_EXIT), then the engine."""
    mf = marker_file(state, session_date, handoff_root)
    doc = _read(mf)
    info = _read(engine_runner.runner_file(state, session_date, handoff_root))
    out = {"session_date": session_date.isoformat(), "handoff_root": handoff_root, "marker": str(mf),
           "chain": _kill(doc.get("chain_pid"), signal.SIGTERM, group=True),
           "runner": _kill(info.get("runner_pid"), signal.SIGKILL),
           "engine": _kill(info.get("engine_pid"), signal.SIGTERM)}
    time.sleep(1)
    if engine_runner._alive(info.get("engine_pid")):
        out["engine"] = _kill(info.get("engine_pid"), signal.SIGKILL) + " (SIGKILL)"
    if doc:
        doc.update(status="stopped", stopped_at=core.iso(core.now_ct().replace(microsecond=0)))
        _write(mf, doc)
    out["note"] = ("nothing already pushed is removed (prep.json / READY / ENGINE_STARTED stay in dragonfly-private); "
                   "the marker stays, so this date/root cannot be fired again by accident")
    return out


def status(repo: Path, session_date: date, handoff_root: str, state: Path, remote: bool = True) -> dict:
    doc = _read(marker_file(state, session_date, handoff_root))
    info = _read(engine_runner.runner_file(state, session_date, handoff_root))
    base = Path(repo) / handoff_root / session_date.isoformat()
    return {"session_date": session_date.isoformat(), "handoff_root": handoff_root, "marker": doc or None,
            "chain_alive": engine_runner._alive(doc.get("chain_pid")),
            "runner_pid": info.get("runner_pid"), "runner_alive": engine_runner._alive(info.get("runner_pid")),
            "engine_pid": info.get("engine_pid"), "engine_alive": engine_runner._alive(info.get("engine_pid")),
            "engine_started": engine_started(repo, session_date, handoff_root, remote=remote),
            "ready": (base / "READY").exists(), "done": (base / "cards" / "DONE").exists(),
            "engine_exit": (base / engine_runner.EXIT_NAME).exists()}
