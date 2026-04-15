#!/usr/bin/env python3
"""
Poll macOS Messages database for replies like "NO a1b2c3d4" and reject matching promoted terms.

Requires Full Disk Access for Terminal/Python (or whatever runs this) to read:
  ~/Library/Messages/chat.db

Run on a schedule (cron/launchd) every few minutes alongside the pipeline.

Env:
  TERM_PROMOTION_MESSAGES_DB — override path to chat.db (default ~/Library/Messages/chat.db)
"""

from __future__ import annotations

import os
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db  # type: ignore
from reject_promoted_term import reject_promoted_term  # type: ignore
from term_promotion_notify import _load_pending, pop_pending_token, save_pending  # type: ignore

NO_TOKEN_RE = re.compile(r"\bNO\s+([0-9a-f]{8})\b", re.IGNORECASE)


def _open_chat_db_ro(path: Path) -> sqlite3.Connection | None:
    try:
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except Exception:
        return None


def process_replies() -> int:
    """Scan new messages for NO <token>; reject terms. Returns number of rejections."""
    db_path = Path(os.environ.get("TERM_PROMOTION_MESSAGES_DB") or (Path.home() / "Library/Messages/chat.db"))
    if not db_path.is_file():
        print(f"ℹ️  Messages DB not found at {db_path} (grant Full Disk Access or skip).")
        return 0

    pending = _load_pending()
    by_token = pending.setdefault("by_token", {})
    if not by_token:
        return 0

    mconn = _open_chat_db_ro(db_path)
    if not mconn:
        print(f"ℹ️  Could not open {db_path} read-only.")
        return 0

    last_rid = int(pending.get("last_message_rowid") or 0)
    max_rid = last_rid
    n_done = 0
    rows: list = []

    try:
        cur = mconn.execute(
            """
            SELECT ROWID, text FROM message
            WHERE text IS NOT NULL AND LENGTH(text) > 3
              AND ROWID > ?
            ORDER BY ROWID ASC
            """,
            (last_rid,),
        )
        rows = cur.fetchall()
    except Exception as e:
        print(f"⚠ Messages query failed: {e}")
        return 0
    finally:
        mconn.close()

    dash = get_db()

    for rowid, text in rows:
        max_rid = max(max_rid, int(rowid))
        if not text:
            continue
        m = NO_TOKEN_RE.search(text)
        if not m:
            continue
        token = m.group(1).lower()
        entry = pop_pending_token(token)
        if not entry:
            continue
        term = (entry.get("term") or "").strip()
        if not term:
            continue

        with dash._get_connection() as conn:
            if reject_promoted_term(
                conn,
                term,
                notes="Rejected: SMS reply (NO token) to promoted Overton term",
            ):
                conn.commit()
                n_done += 1
                print(f"✓ Rejected promoted term from reply: {term}")
            else:
                conn.commit()

    pending = _load_pending()
    pending["last_message_rowid"] = max_rid
    save_pending(pending)
    return n_done


def main() -> None:
    n = process_replies()
    if n:
        print(f"Processed {n} rejection(s). Re-run site export to refresh Overton.")
    else:
        print("No matching NO <token> replies to process.")


if __name__ == "__main__":
    main()
