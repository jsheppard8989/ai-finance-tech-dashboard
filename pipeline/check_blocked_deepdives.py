#!/usr/bin/env python3
"""Read-only alert for stuck Deep Dives (Oct 28 2026, Wendy).

Lists:
  1. deep_dive_generation_failures rows in 'blocked' state (the nightly run skips these; only a
     manual `generate_deepdives.py --insight-ids ...` retries them), and
  2. any live (non-archived) insight with no deep_dive_content row that is older than 48h
     (by latest_insights.added_date) and is not already listed as blocked.

Output: id, episode, reason, retries and last-tried time in US Central (CT).
Exit 0 with "OK: 0 blocked" when nothing is listed, 1 otherwise.

Insights in deepdive_permanent_skips.json (approved permanent skips) are listed separately as
"SKIPPED (permanent)" with their reason and do NOT count toward the alert / exit 1.

The DB is opened with SQLite mode=ro; this script never writes. Default DB is
workspace_paths.DB_PATH (honours WORKSPACE_ROOT); override with --db.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from deepdive_skips import load_permanent_skips

CT = ZoneInfo("America/Chicago")
STALE_HOURS = 48


def open_readonly(db_path: Path) -> sqlite3.Connection:
    p = Path(db_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"DB not found: {p}")
    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def fmt_ct(ts: Optional[str]) -> str:
    """Format a stored timestamp in CT. Naive values are pipeline-local (the Mac runs in CT)."""
    if not ts:
        return "never"
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return str(ts)
    dt = dt.replace(tzinfo=CT) if dt.tzinfo is None else dt.astimezone(CT)
    return dt.strftime("%Y-%m-%d %H:%M CT")


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def find_problems(conn: sqlite3.Connection, now: Optional[datetime] = None):
    """Return (blocked_rows, stale_rows) as lists of dicts."""
    now = now or datetime.now(CT)
    blocked: List[dict] = []
    if _has_table(conn, "deep_dive_generation_failures"):
        for r in conn.execute(
            """SELECT insight_id, podcast_episode_id, insight_title, failure_reason, failure_detail,
                      retry_count, last_attempt_at
               FROM deep_dive_generation_failures
               WHERE status = 'blocked'
               ORDER BY insight_id"""
        ):
            blocked.append(dict(r))
    blocked_ids = {b["insight_id"] for b in blocked}

    stale: List[dict] = []
    has_fail = _has_table(conn, "deep_dive_generation_failures")
    cutoff = (now - timedelta(hours=STALE_HOURS)).date()
    fail_cols = ("f.failure_reason, f.retry_count, f.last_attempt_at, f.status"
                 if has_fail else "NULL AS failure_reason, NULL AS retry_count, NULL AS last_attempt_at, NULL AS status")
    fail_join = "LEFT JOIN deep_dive_generation_failures f ON f.insight_id = li.id" if has_fail else ""
    for r in conn.execute(
        f"""SELECT li.id AS insight_id, li.podcast_episode_id, li.title AS insight_title,
                   li.added_date, {fail_cols}
            FROM latest_insights li
            {fail_join}
            WHERE li.archived_date IS NULL
              AND NOT EXISTS (SELECT 1 FROM deep_dive_content d WHERE d.insight_id = li.id)
            ORDER BY li.id"""
    ):
        row = dict(r)
        if row["insight_id"] in blocked_ids:
            continue
        try:
            added = date.fromisoformat(str(row["added_date"])[:10])
        except (TypeError, ValueError):
            continue
        # added_date is a DATE: older than 48h means the whole day is before the cutoff day.
        if added < cutoff:
            stale.append(row)
    return blocked, stale


def split_skipped(blocked: List[dict], stale: List[dict], skips: Optional[Dict[int, dict]]):
    """Move permanently-skipped insights out of blocked/stale. Returns (blocked, stale, skipped).

    Only skips that match a current blocked/stale row are listed (a resolved insight is not noise)."""
    skips = skips or {}
    skipped: List[dict] = []
    keep_b, keep_s = [], []
    for kind, rows, keep in (("blocked", blocked, keep_b), ("no deep dive", stale, keep_s)):
        for r in rows:
            iid = r["insight_id"]
            if iid in skips:
                skipped.append({"insight_id": iid, "state": kind, "row": r, "skip": skips[iid]})
            else:
                keep.append(r)
    skipped.sort(key=lambda x: x["insight_id"])
    return keep_b, keep_s, skipped


def _short(s: Optional[str], n: int = 90) -> str:
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[: n - 1] + "…"


def _render_skipped(skipped: List[dict]) -> List[str]:
    out = []
    for k in skipped:
        sk, row = k["skip"], k["row"]
        ep = row.get("podcast_episode_id", sk.get("podcast_episode_id"))
        state = f"was {k['state']}"
        out.append(
            f"  SKIPPED (permanent) insight {k['insight_id']} | ep {ep} | reason: {sk.get('reason') or 'none recorded'}"
            f" | approved: {sk.get('approved_by') or 'unknown'} | {state}"
            f" | retries: {row.get('retry_count') or 0} | last tried: {fmt_ct(row.get('last_attempt_at'))}"
            f" | {_short(row.get('insight_title') or sk.get('title'), 60)}"
        )
    if out:
        out.append("  (permanent skips are not alerts; undo by removing the entry from pipeline/deepdive_permanent_skips.json)")
    return out


def render(blocked: List[dict], stale: List[dict], skipped: Optional[List[dict]] = None) -> str:
    skipped = skipped or []
    if not blocked and not stale:
        if not skipped:
            return "OK: 0 blocked"
        return "\n".join([f"OK: 0 blocked ({len(skipped)} permanently skipped)"] + _render_skipped(skipped))
    out = [f"ALERT: {len(blocked)} blocked deep dive(s), {len(stale)} insight(s) >{STALE_HOURS}h old with no deep dive"]
    for b in blocked:
        out.append(
            f"  BLOCKED insight {b['insight_id']} | ep {b['podcast_episode_id']} | reason: {b['failure_reason']}"
            f" | retries: {b['retry_count']} | last tried: {fmt_ct(b['last_attempt_at'])}"
            f" | {_short(b.get('insight_title'), 60)}"
        )
        if b.get("failure_detail"):
            out.append(f"      detail: {_short(b['failure_detail'])}")
    for s in stale:
        out.append(
            f"  NO DEEP DIVE insight {s['insight_id']} | ep {s['podcast_episode_id']} | added {s['added_date']}"
            f" | reason: {s.get('failure_reason') or 'none recorded'} | retries: {s.get('retry_count') or 0}"
            f" | last tried: {fmt_ct(s.get('last_attempt_at'))} | {_short(s.get('insight_title'), 60)}"
        )
    out.extend(_render_skipped(skipped))
    out.append("Retry after a fix: python3 generate_deepdives.py --insight-ids <ids> (manual runs include blocked)")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", type=Path, default=None, help="dashboard.db path (default: workspace_paths.DB_PATH)")
    ap.add_argument("--skips", type=Path, default=None,
                    help="permanent-skip config (default: pipeline/deepdive_permanent_skips.json)")
    args = ap.parse_args(argv)
    skips = load_permanent_skips(args.skips)
    if args.db is None:
        from workspace_paths import DB_PATH
        args.db = DB_PATH
    conn = open_readonly(args.db)
    try:
        blocked, stale = find_problems(conn)
    finally:
        conn.close()
    blocked, stale, skipped = split_skipped(blocked, stale, skips)
    print(render(blocked, stale, skipped))
    return 0 if not blocked and not stale else 1


if __name__ == "__main__":
    sys.exit(main())
