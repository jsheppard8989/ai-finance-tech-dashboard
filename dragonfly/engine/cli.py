"""CLI: python3 -m dragonfly.engine {run,ready} ...

  run    Poll inbox/<date>/ from 08:08 to 08:24 CT (60 s). Size each draft once
         its <trade_id>.redteam.json lands (cutoff 08:20), card every draft,
         write DONE after the cutoff. --once for one pass.
  ready  Write handoff/<date>/READY (LAST step of the 08:05 pre-open job).

The private repo checkout: --repo, else $DRAGONFLY_PRIVATE_DIR, else
~/projects/dragonfly-private. Book: --book, else $DRAGONFLY_STATE_DIR/book.json,
else dragonfly/state/live/book.json.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional, Sequence

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dragonfly.engine import core  # noqa: E402
from dragonfly.engine.core import EngineError, SessionClock  # noqa: E402

ENV_REPO = "DRAGONFLY_PRIVATE_DIR"


class _CTFormatter(logging.Formatter):
    def formatTime(self, record, datefmt=None):  # noqa: N802
        from datetime import datetime

        return datetime.fromtimestamp(record.created, core.tz()).isoformat(timespec="seconds")


def setup_logging(verbose: bool = False) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_CTFormatter("%(asctime)s %(levelname)s %(message)s"))
    root = logging.getLogger("dragonfly.engine")
    root.handlers[:] = [handler]
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.propagate = False


def default_repo() -> Path:
    return Path(os.environ.get(ENV_REPO) or Path.home() / "projects" / "dragonfly-private")


def _parse_date(value: Optional[str], now) -> date:
    return date.fromisoformat(value) if value else now.date()


def _now_fn(start_at: Optional[str]):
    """--now shifts the clock: it reads start_at at launch and then advances in real time."""
    if not start_at:
        return core.now_ct
    offset = core.parse_iso(start_at) - core.now_ct()
    return lambda: (core.now_ct() + offset).replace(microsecond=0)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="python3 -m dragonfly.engine", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="engine poll loop (or --once)")
    run.add_argument("--repo", type=Path, default=None)
    run.add_argument("--date", default=None, help="session date YYYY-MM-DD (default: today in CT)")
    run.add_argument("--once", action="store_true", help="single pass, then exit")
    run.add_argument("--finalize", action="store_true", help="write DONE even before the cutoff")
    run.add_argument("--start", default=core.DEFAULT_START)
    run.add_argument("--cutoff", default=core.DEFAULT_CUTOFF)
    run.add_argument("--end", default=core.DEFAULT_END)
    run.add_argument("--poll-seconds", type=int, default=core.DEFAULT_POLL_SECONDS)
    run.add_argument("--book", type=Path, default=None, help="book state JSON (default: state/live/book.json)")
    run.add_argument("--state-dir", type=Path, default=None, help="engine local state dir (default: state/live)")
    run.add_argument("--bars-dir", type=Path, default=None, help="bars cache dir (default: state/live/cache/bars; read-only)")
    run.add_argument("--watchlist", type=Path, default=None, help="watchlist.json for sector/spread fallback (read-only)")
    run.add_argument("--no-pull", action="store_true", help="do not ls-remote/pull")
    run.add_argument("--no-push", action="store_true", help="write files only; no commit, no push")
    run.add_argument("--now", default=None, help="pretend the clock reads this (ISO with offset) at launch; dry runs")
    run.add_argument("-v", "--verbose", action="store_true")

    ready = sub.add_parser("ready", help="write handoff/<date>/READY (last step of the pre-open job)")
    ready.add_argument("--repo", type=Path, default=None)
    ready.add_argument("--date", default=None)
    ready.add_argument("--no-pull", action="store_true")
    ready.add_argument("--no-push", action="store_true", help="commit READY locally but do not push")
    ready.add_argument("--now", default=None)
    ready.add_argument("-v", "--verbose", action="store_true")
    return ap


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging(args.verbose)
    log = logging.getLogger("dragonfly.engine")
    now_fn = _now_fn(args.now)
    session_date = _parse_date(args.date, now_fn())
    repo = args.repo or default_repo()
    try:
        if args.cmd == "ready":
            from dragonfly.engine.markers import write_ready

            doc = write_ready(repo, session_date, now=now_fn(), pull=not args.no_pull, push=not args.no_push)
            print(core.dumps({"ready": f"handoff/{session_date}/READY", "files": len(doc["files"])}), end="")
            return 0

        from dragonfly.engine.engine import Engine

        clock = SessionClock(session_date, args.start, args.cutoff, args.end)
        engine = Engine(
            repo, session_date, clock=clock, book_path=args.book, state_dir=args.state_dir,
            pull=not args.no_pull, push=not args.no_push, finalize=args.finalize,
            poll_seconds=args.poll_seconds, now_fn=now_fn, bars_dir=args.bars_dir, watchlist_path=args.watchlist,
        )
        if args.once:
            result = engine.run_pass()
            summary = {"tick": result["tick"], "written": result["written"], "pending": result["pending"],
                       "frozen_changed": result["frozen_changed"], "done": bool(result["done"])}
            print(core.dumps(summary), end="")
            return 0
        return engine.run_loop()
    except EngineError as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
