"""CLI: python3 -m dragonfly.jobs {prep,preopen} ...

  prep     15:30 CT, prior session: watchlist, bars, measurements ->
           <handoff root>/<next session>/prep.json + measurements.json
  preopen  08:05 CT: prep check, book check, pre-market quotes ->
           quotes.json + book.json, then READY (last)

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
    for name in ("prep", "preopen"):
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
    return ap


def _handoff_root(args) -> str:
    """handoff-dryrun with --dry-run-roots; else the engine's env pair rule
    ($DRAGONFLY_HANDOFF_ROOT / $DRAGONFLY_INBOX_ROOT), else handoff."""
    return core.resolve_roots(None, None, args.dry_run_roots)[0]


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    common.setup_logging(args.verbose)
    log = logging.getLogger("dragonfly.jobs")
    from dragonfly import guards

    try:
        root = _handoff_root(args)
        if root != core.DEFAULT_HANDOFF_ROOT:
            log.info("handoff root: %s/ (not handoff/)", root)
        repo = args.repo or common.default_repo()
        book = args.book or common.default_book_path()
        now_fn = common.now_fn(args.now)
        if args.cmd == "prep":
            from dragonfly.jobs.prep import run_prep

            out = run_prep(repo, now=now_fn(), date_arg=args.date, handoff_root=root, pull=not args.no_pull,
                           push=not args.no_push, state=args.state_dir, book_path=book,
                           mark_book=not args.no_mark_book)
        else:
            from dragonfly.jobs.preopen import run_preopen

            out = run_preopen(repo, now_fn=now_fn, date_arg=args.date, simulated=bool(args.now), handoff_root=root,
                              pull=not args.no_pull, push=not args.no_push, state=args.state_dir, book_path=book)
        print(core.dumps(out), end="")
        return 0
    except guards.GuardBlocked as exc:
        log.error("guard blocked: %s %s", exc.reason, exc.detail)
        return 2
    except core.EngineError as exc:
        log.error("%s", exc)
        return 2


if __name__ == "__main__":
    sys.exit(main())
