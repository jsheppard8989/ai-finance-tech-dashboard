"""Detached engine launch, ENGINE_EXIT marker, and the DONE watchdog.

  spawn_detached()   double-fork + setsid; the grandchild (re-parented away from
                     the caller's session) runs this module's runner. Used by the
                     pre-open job (--launch-engine) so the engine outlives the
                     job and the agent/tool shell that started it.
  runner (main)      runs `python -m dragonfly.engine run ...` as a child, waits
                     for it, then writes <handoff root>/<date>/ENGINE_EXIT
                     (exit code, times, DONE present or not, last 40 log lines)
                     and commits + pushes it with the engine's PrivateRepo.
  watchdog           `python -m dragonfly.jobs watchdog`: after the window end
                     (+ grace) with no cards/DONE, or with the runner dead and no
                     ENGINE_EXIT, writes <root>/<date>/ENGINE_WATCHDOG, pushes it,
                     exits 1. Otherwise exit 0 (ok / pending).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import deque
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from dragonfly.engine import core

EXIT_NAME = "ENGINE_EXIT"
WATCHDOG_NAME = "ENGINE_WATCHDOG"
WATCHDOG_GRACE = timedelta(minutes=3)


def _suffix(handoff_root: str) -> str:
    return "" if handoff_root == core.DEFAULT_HANDOFF_ROOT else f".{handoff_root}"


def runner_file(state: Path, session_date: date, handoff_root: str) -> Path:
    return Path(state) / "engine" / f"runner-{session_date.isoformat()}{_suffix(handoff_root)}.json"


def default_log(state: Path, session_date: date, handoff_root: str) -> Path:
    return Path(state) / "logs" / f"engine-{session_date.isoformat()}{_suffix(handoff_root)}.log"


def spawn_detached(argv: Sequence[str], log_path: Path, cwd: Path, env: Optional[dict] = None) -> int:
    """Double-fork + setsid; stdin /dev/null, stdout/stderr appended to log_path.
    Returns the grandchild's pid (it execs argv)."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(r)
            os.setsid()
            gpid = os.fork()
            if gpid:
                os.write(w, str(gpid).encode())
                os._exit(0)
            os.close(w)
            devnull = os.open(os.devnull, os.O_RDWR)
            out = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(devnull, 0)
            os.dup2(out, 1)
            os.dup2(out, 2)
            os.chdir(str(cwd))
            os.execve(argv[0], list(argv), env if env is not None else dict(os.environ))
        except BaseException:
            os._exit(127)
    os.close(w)
    data = b""
    while True:
        chunk = os.read(r, 64)
        if not chunk:
            break
        data += chunk
    os.close(r)
    os.waitpid(pid, 0)
    if not data:
        raise core.EngineError("detached engine launch failed (no pid from the double fork)")
    return int(data.decode())


def engine_argv(python: str, repo: Path, session_date: date, handoff_root: str, inbox_root: str,
                book: Optional[Path], watchlist: Optional[Path], now_iso: Optional[str]) -> List[str]:
    argv = [python, "-m", "dragonfly.engine", "run", "--repo", str(repo), "--date", session_date.isoformat()]
    if handoff_root != core.DEFAULT_HANDOFF_ROOT:
        argv += ["--handoff-root", handoff_root, "--inbox-root", inbox_root]
    if book:
        argv += ["--book", str(book)]
    if watchlist:
        argv += ["--watchlist", str(watchlist)]
    if now_iso:
        argv += ["--now", now_iso]
    return argv


def launch_engine(repo: Path, session_date: date, handoff_root: str, inbox_root: str, *, now_iso: Optional[str],
                  state: Path, book: Optional[Path] = None, watchlist: Optional[Path] = None,
                  python: Optional[str] = None, spawn: Callable = spawn_detached) -> dict:
    """Start the runner (which starts the engine) fully detached. Returns pid + log."""
    python = python or sys.executable
    log = default_log(state, session_date, handoff_root)
    eng = engine_argv(python, repo, session_date, handoff_root, inbox_root, book, watchlist, now_iso)
    argv = [python, "-m", "dragonfly.jobs.engine_runner", "--repo", str(repo), "--date", session_date.isoformat(),
            "--handoff-root", handoff_root, "--state-dir", str(state), "--log", str(log), "--"] + eng
    env = dict(os.environ, DRAGONFLY_STATE_DIR=str(state))
    pid = spawn(argv, log, core.ROOT, env)
    return {"runner_pid": pid, "log": str(log), "engine_argv": eng, "launched_at": core.iso(core.now_ct())}


def _tail(path: Path, n: int = 40) -> List[str]:
    try:
        with open(path, errors="replace") as fh:
            return [line.rstrip("\n") for line in deque(fh, maxlen=n)]
    except OSError:
        return []


def _push_marker(repo_path: Path, rel: str, doc: dict, message: str) -> str:
    from dragonfly.engine.gitops import PrivateRepo

    path = Path(repo_path) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(core.dumps(doc), encoding="utf-8")
    try:
        repo = PrivateRepo(Path(repo_path))
        try:
            repo.sync()
        except Exception as exc:  # still try to commit and push
            print(f"{rel}: sync failed: {exc}", flush=True)
        repo.commit_and_push([rel], message, push=True)
        return "pushed"
    except Exception as exc:
        print(f"{rel}: commit/push failed: {exc}", flush=True)
        return f"failed: {exc}"


def run(repo: Path, session_date: date, handoff_root: str, state: Path, log: Path, engine: Sequence[str]) -> int:
    ds = session_date.isoformat()
    started = core.iso(core.now_ct())
    print(f"---- runner {os.getpid()} start {started}: {' '.join(engine)}", flush=True)
    proc = subprocess.Popen(list(engine), cwd=str(core.ROOT), stdin=subprocess.DEVNULL)
    rf = runner_file(state, session_date, handoff_root)
    rf.parent.mkdir(parents=True, exist_ok=True)
    rf.write_text(core.dumps({"runner_pid": os.getpid(), "engine_pid": proc.pid, "started_at": started,
                              "log": str(log), "engine_argv": list(engine)}), encoding="utf-8")
    rc = proc.wait()
    ended = core.iso(core.now_ct())
    print(f"---- engine exited rc={rc} at {ended}", flush=True)
    rel_dir = f"{handoff_root}/{ds}"
    done = (Path(repo) / rel_dir / "cards" / "DONE").exists()
    doc = {"marker": EXIT_NAME, "session_date": ds, "exit_code": rc, "started_at": started, "ended_at": ended,
           "done_present": done, "engine_pid": proc.pid, "runner_pid": os.getpid(), "log": str(log),
           "log_tail": _tail(log, 40)}
    status = _push_marker(Path(repo), f"{rel_dir}/{EXIT_NAME}", doc,
                          f"engine {ds}: {EXIT_NAME} rc={rc}{'' if done else ' (NO DONE)'} ({handoff_root})")
    print(f"---- {EXIT_NAME} {status}", flush=True)
    return rc


def _alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def watchdog(repo: Path, session_date: date, handoff_root: str, state: Path, now: datetime,
             end: str = core.DEFAULT_END, pull: bool = True, push: bool = True) -> dict:
    ds = session_date.isoformat()
    rel_dir = f"{handoff_root}/{ds}"
    if pull:
        from dragonfly.engine.gitops import PrivateRepo

        try:
            PrivateRepo(Path(repo)).sync()
        except Exception as exc:
            print(f"watchdog: sync failed: {exc}", flush=True)
    base = Path(repo) / rel_dir
    done = (base / "cards" / "DONE").exists()
    exited = (base / EXIT_NAME).exists()
    try:
        info = json.loads(runner_file(state, session_date, handoff_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        info = {}
    runner_alive = _alive(info.get("runner_pid"))
    deadline = datetime.combine(session_date, core.parse_hhmm(end), tzinfo=core.tz()) + WATCHDOG_GRACE
    out = {"session_date": ds, "done": done, "engine_exit": exited, "runner_alive": runner_alive,
           "runner_pid": info.get("runner_pid"), "engine_pid": info.get("engine_pid"),
           "deadline": core.iso(deadline), "now": core.iso(now)}
    if done:
        out["status"] = "ok"
        return out
    problem = None
    if now > deadline:
        problem = "no DONE after the window end + grace"
    elif info and not runner_alive and not exited:
        problem = "runner died without ENGINE_EXIT"
    if not problem:
        out["status"] = "pending"
        return out
    out["status"] = "alert"
    out["problem"] = problem
    doc = dict(out, marker=WATCHDOG_NAME, log_tail=_tail(Path(info["log"]), 40) if info.get("log") else [])
    out["pushed"] = _push_marker(Path(repo), f"{rel_dir}/{WATCHDOG_NAME}", doc,
                                 f"engine {ds}: {WATCHDOG_NAME} ({problem}) ({handoff_root})") if push else "no-push"
    return out


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" not in argv:
        print("usage: python -m dragonfly.jobs.engine_runner --repo R --date D --handoff-root H --state-dir S "
              "--log L -- <engine argv>", file=sys.stderr)
        return 2
    i = argv.index("--")
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--handoff-root", required=True)
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--log", type=Path, required=True)
    args = ap.parse_args(argv[:i])
    return run(args.repo, date.fromisoformat(args.date), args.handoff_root, args.state_dir, args.log, argv[i + 1:])


if __name__ == "__main__":
    sys.exit(main())
