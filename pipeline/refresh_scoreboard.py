#!/usr/bin/env python3
"""Box-side scoreboard refresh: record a read-only quote pull, rebuild, tie out, open a data PR.

The paper book lives only on the box (/workspace/cos/paper_book), so the scoreboard is
built here, not in the Mac nightly. The flow mirrors .github/workflows/market-data.yml:
a fresh worktree from origin/<base>, rebuild site/data/scoreboard.json, verify it against
the book, then commit on a data branch and open a PR.

Robinhood stays read-only: this script never calls Robinhood. The routine calls
get_equity_quotes and get_option_quotes itself and hands the saved results here.

Modes
  --mode dry-run  build + verify in a temp worktree, print the result, push nothing
  --mode preview  commit onto an existing branch (--base) and push it (pre-launch: updates
                  the draft PR / preview only; nothing reaches main)
  --mode pr       new branch data/scoreboard-<ts> from origin/<base>, push, open a PR, no merge
  --mode merge    as pr, then merge and dispatch deploy.yml (only after Jared's go-live yes
                  AND his yes to auto-merging scoreboard data PRs)

A row that does not tie to the book is held by build_scoreboard.py; with any held row the
refresh stops before committing and exits 2.

Example (routine, pre-launch):
  python3 pipeline/refresh_scoreboard.py \\
     --equity-json /workspace/cos/quotes/raw/2026-11-27_0835_equity.json \\
     --option-json /workspace/cos/quotes/raw/2026-11-27_0835_options.json \\
     --mode preview --base feat/home-live-scoreboard
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import pull_scoreboard_quotes as pq  # noqa: E402

CT = ZoneInfo("America/Chicago")
DEFAULT_REPO = Path("/workspace/ai-finance-tech-dashboard")
WORK_ROOT = Path("/workspace/scoreboard-refresh")
SB_PATH = "site/data/scoreboard.json"
VOLATILE_KEYS = {"generated_at_ct", "generated_at_label"}


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=cwd, check=check, text=True, capture_output=True)


def _stable(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k not in VOLATILE_KEYS}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--equity-json", type=Path, default=None)
    ap.add_argument("--option-json", type=Path, default=None)
    ap.add_argument("--read-time", default=None, help="ISO time the Robinhood tools were called")
    ap.add_argument("--no-record", action="store_true", help="do not append the pull to /workspace/cos/quotes")
    ap.add_argument("--quotes-dir", type=Path, default=pq.COS_QUOTES_DIR)
    ap.add_argument("--book", type=Path, default=None)
    ap.add_argument("--repo", type=Path, default=DEFAULT_REPO)
    ap.add_argument("--base", default="main")
    ap.add_argument("--mode", choices=["dry-run", "preview", "pr", "merge"], default="dry-run")
    args = ap.parse_args(argv)

    now = pq.parse_ct_timestamp(args.read_time) if args.read_time else datetime.now(CT)
    ts = now.strftime("%Y-%m-%d-%H%M")
    book_path = pq.resolve_book_path(args.book)
    book = json.loads(book_path.read_text(encoding="utf-8"))

    # 1. Record the live read (CSV + audit + SPY close) and normalize quotes.
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    norm_path = WORK_ROOT / f"quotes_{ts}.json"
    pull_args = ["--book", str(book_path), "--quotes-dir", str(args.quotes_dir), "--out", str(norm_path)]
    if args.equity_json:
        pull_args += ["--equity-json", str(args.equity_json)]
    if args.option_json:
        pull_args += ["--option-json", str(args.option_json)]
    if args.read_time:
        pull_args += ["--read-time", args.read_time]
    if not args.no_record and (args.equity_json or args.option_json):
        pull_args.append("--record")
    if pq.main(pull_args) != 0:
        return 1

    # 2. Fresh worktree from origin/<base>; the checkout at --repo is never switched.
    # explicit refspec: the box clone only tracks main by default
    run(["git", "-C", str(args.repo), "fetch", "-q", "origin",
         f"+refs/heads/{args.base}:refs/remotes/origin/{args.base}"])
    wt = WORK_ROOT / f"wt-{ts}"
    if wt.exists():
        run(["git", "-C", str(args.repo), "worktree", "remove", "--force", str(wt)], check=False)
        shutil.rmtree(wt, ignore_errors=True)
    run(["git", "-C", str(args.repo), "worktree", "add", "-q", "--detach", str(wt), f"origin/{args.base}"])
    try:
        sb_file = wt / SB_PATH
        before = json.loads(sb_file.read_text(encoding="utf-8")) if sb_file.is_file() else {}
        build = run([sys.executable, "pipeline/build_scoreboard.py", "--book", str(book_path),
                     "--quotes-dir", str(args.quotes_dir), "--live-quotes", str(norm_path),
                     "--held-log", str(WORK_ROOT / "held.log"), "--now", now.isoformat(), "--strict"],
                    cwd=wt, check=False)
        print(build.stdout + build.stderr)
        if build.returncode != 0:
            print("HOLD: a row did not tie to the book; nothing committed. See held.log.", file=sys.stderr)
            return 2
        verify = run([sys.executable, "pipeline/build_scoreboard.py", "--book", str(book_path), "--verify-only"],
                     cwd=wt, check=False)
        print(verify.stdout + verify.stderr)
        if verify.returncode != 0:
            return 2
        after = json.loads(sb_file.read_text(encoding="utf-8"))
        if before and _stable(before) == _stable(after):
            print("No scoreboard change; nothing to commit.")
            return 0
        rec, bk = after["record"], after["book"]
        msg = (f"Scoreboard refresh {ts} CT (box, read-only Robinhood quotes): "
               f"open {rec['open_pnl']:+,.2f}, book ${bk['book_value']:,.2f}, mark as of {rec['open_mark_label']}")
        if args.mode == "dry-run":
            print("DRY RUN: " + msg)
            return 0
        if args.mode == "preview":
            branch = args.base
        else:
            branch = f"data/scoreboard-{ts}"
        run(["git", "checkout", "-q", "-B", branch], cwd=wt)
        run(["git", "add", SB_PATH], cwd=wt)
        run(["git", "commit", "-q", "-m", msg], cwd=wt)
        run(["git", "push", "-q", "origin", f"HEAD:{branch}"], cwd=wt)
        if args.mode == "preview":
            print(f"Pushed {msg} to {branch}")
            return 0
        pr = run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Scoreboard refresh {ts} CT",
                  "--body", "Automated by pipeline/refresh_scoreboard.py on the box: read-only Robinhood quotes, "
                            "rebuilt and tied out against the paper book."], cwd=wt)
        url = pr.stdout.strip()
        print(f"Opened {url}")
        if args.mode == "merge":
            run(["gh", "pr", "merge", url, "--merge", "--delete-branch"], cwd=wt)
            run(["gh", "workflow", "run", "deploy.yml", "--ref", "main"], cwd=wt)
            print(f"Merged {url} and dispatched deploy.yml")
        return 0
    finally:
        run(["git", "-C", str(args.repo), "worktree", "remove", "--force", str(wt)], check=False)


if __name__ == "__main__":
    raise SystemExit(main())
