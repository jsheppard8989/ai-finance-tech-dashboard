"""CLI: python3 -m dragonfly.jobs {prep,preopen} ...

  prep     15:30 CT, prior session: watchlist, bars, measurements ->
           <handoff root>/<next session>/prep.json + measurements.json
  preopen  08:05 CT: prep check, book check, pre-market quotes ->
           quotes.json + book.json, then READY (last); --launch-engine then
           starts the engine loop detached (ENGINE_EXIT pushed when it ends)
  session  box, ONE command ~07:10-07:45 CT: returns in seconds; a detached
           chain runs prep, preopen --launch-engine, then the watchdog at
           08:27 (dragonfly/jobs/session.py). Refused if this date/root was
           already fired, has a live runner, or has ENGINE_STARTED.
  session-stop / session-status: kill / inspect a box session
  watchdog after 08:27 CT: alert (ENGINE_WATCHDOG pushed, exit 1) if cards/DONE
           is missing, or the runner died without ENGINE_EXIT

Common: --repo (else $DRAGONFLY_PRIVATE_DIR, else ~/projects/dragonfly-private),
--book (else $DRAGONFLY_BOOK, else <state dir>/book.json), --date, --now
(simulated clock, dry runs), --dry-run-roots (handoff-dryrun/ only),
--no-pull, --no-push. Exit: 0 ok (also a non-session day), 2 failure.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Optional, Sequence

from dragonfly.engine import core
from dragonfly.jobs import common


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m dragonfly.jobs", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("prep", "preopen", "watchdog"):
        p = sub.add_parser(name)
        p.add_argument("--repo", type=Path, default=None)
        p.add_argument("--date", default=None,
                       help="session date YYYY-MM-DD (prep: the target session, default the next one; "
                            "preopen: default today)")
        p.add_argument("--now", default=None, help="simulated clock ISO with offset (dry runs)")
        p.add_argument("--book", type=Path, default=None)
        p.add_argument("--state-dir", type=Path, default=None, help="job state (locks, quote cache); default state/live")
        p.add_argument("--no-pull", action="store_true")
        p.add_argument("--no-push", action="store_true", help="commit locally, do not push")
        p.add_argument("--dry-run-roots", action="store_true", help="write handoff-dryrun/ (never handoff/)")
        p.add_argument("-v", "--verbose", action="store_true")
        if name == "prep":
            p.add_argument("--no-mark-book", action="store_true", help="do not re-stamp a flat book")
        if name == "preopen":
            p.add_argument("--launch-engine", action="store_true",
                           help="after READY, start the engine loop fully detached (double fork + setsid); "
                                "ENGINE_EXIT is pushed when it ends")
    for name in ("session", "session-chain", "session-stop", "session-status"):
        p = sub.add_parser(name)
        p.add_argument("--repo", type=Path, default=None)
        p.add_argument("--date", default=None, help="session date YYYY-MM-DD (default today, CT)")
        p.add_argument("--state-dir", type=Path, default=None)
        p.add_argument("-v", "--verbose", action="store_true")
        if name in ("session", "session-chain"):
            p.add_argument("--sim-start", default=None,
                           help="shifted clock: the simulated time at the fire, ISO with offset (smoke tests)")
        if name == "session-chain":
            p.add_argument("--fired-at", required=True)
    return ap


def _roots(args):
    """handoff-dryrun/inbox-dryrun with --dry-run-roots; else the engine's env pair
    rule ($DRAGONFLY_HANDOFF_ROOT / $DRAGONFLY_INBOX_ROOT), else handoff/inbox."""
    return core.resolve_roots(None, None, getattr(args, "dry_run_roots", False))


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    common.setup_logging(args.verbose)
    log = logging.getLogger("dragonfly.jobs")
    from dragonfly import guards

    try:
        root, inbox_root = _roots(args)
        if root != core.DEFAULT_HANDOFF_ROOT:
            log.info("handoff root: %s/ (not handoff/)", root)
        repo = args.repo or common.default_repo()
        if args.cmd.startswith("session"):
            return _session(args, repo, root, inbox_root)
        book = args.book or common.default_book_path()
        now_fn = common.now_fn(args.now)
        if args.cmd == "prep":
            from dragonfly.jobs.prep import run_prep

            out = run_prep(repo, now=now_fn(), date_arg=args.date, handoff_root=root, pull=not args.no_pull,
                           push=not args.no_push, state=args.state_dir, book_path=book,
                           mark_book=not args.no_mark_book)
        elif args.cmd == "preopen":
            from dragonfly.jobs.preopen import run_preopen

            out = run_preopen(repo, now_fn=now_fn, date_arg=args.date, simulated=bool(args.now), handoff_root=root,
                              pull=not args.no_pull, push=not args.no_push, state=args.state_dir, book_path=book,
                              inbox_root=inbox_root, launch_engine=args.launch_engine)
        else:
            from datetime import date as _date

            from dragonfly.jobs.engine_runner import watchdog

            now = now_fn()
            out = watchdog(repo, _date.fromisoformat(args.date) if args.date else now.date(), root,
                           args.state_dir or core.state_dir(), now, pull=not args.no_pull, push=not args.no_push)
            print(core.dumps(out), end="")
            return 1 if out["status"] == "alert" else 0
        print(core.dumps(out), end="")
        return 0
    except guards.GuardBlocked as exc:
        log.error("guard blocked: %s %s", exc.reason, exc.detail)
        return 2
    except core.EngineError as exc:
        log.error("%s", exc)
        return 2


def _session(args, repo, root, inbox_root) -> int:
    from datetime import date as _date

    from dragonfly.jobs import session

    state = args.state_dir or core.state_dir()
    day = _date.fromisoformat(args.date) if args.date else core.now_ct().date()
    if args.cmd == "session":
        try:
            out = session.fire(repo, day, root, inbox_root, state, sim_start=args.sim_start)
        except session.SessionRefused as exc:
            print(core.dumps({"session_date": day.isoformat(), "handoff_root": root, "refused": str(exc)}), end="")
            return 3
    elif args.cmd == "session-chain":
        return session.run_chain(repo, day, state, args.fired_at, sim_start=args.sim_start)
    elif args.cmd == "session-stop":
        out = session.stop(day, root, state)
    else:
        out = session.status(repo, day, root, state)
    print(core.dumps(out), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
