#!/usr/bin/env python3
"""
Poll macOS Messages database for replies that reject a promoted Overton term:

  • "NO <8-char-token>" — precise match (multiple pending promotions).
  • "NO" or "No" (plain, optional trailing punctuation) — rejects the last notified
    promotion (last_notified_token in pending_term_promotions.json), or if exactly
    one promotion is pending, that one.

Requires Full Disk Access for TermPromotionRepliesRunner.app. The conda Python copy is the
bundle’s CFBundleExecutable (Contents/MacOS/TermPromotionRepliesRunner) so FDA matches launchd.
Reads: ~/Library/Messages/chat.db

Run on a schedule (launchd) every few minutes alongside the pipeline.

Env:
  TERM_PROMOTION_MESSAGES_DB — override path to chat.db (default ~/Library/Messages/chat.db)
"""

from __future__ import annotations

import fcntl
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db  # type: ignore
from workspace_paths import STATE_DIR  # type: ignore
from reject_promoted_term import reject_promoted_term  # type: ignore
from term_promotion_notify import _load_pending, pop_pending_token, save_pending  # type: ignore

NO_TOKEN_RE = re.compile(r"\bNO\s+([0-9a-f]{8})\b", re.IGNORECASE)


def _open_chat_db_ro(path: Path) -> tuple[sqlite3.Connection | None, str | None]:
    """
    Open Messages DB read-only. Use Path.as_uri() (proper encoding); raw file:{path}?mode=ro
    breaks on some paths and hides errors behind a swallowed exception.
    """
    resolved = path.expanduser().resolve()
    try:
        fd = os.open(os.fspath(resolved), os.O_RDONLY)
        os.close(fd)
    except OSError as e:
        return None, f"os.open O_RDONLY failed (errno {e.errno}): {e}"
    attempts: list[tuple[str, str]] = []
    uri_ro = resolved.as_uri() + "?mode=ro"
    uri_immutable = resolved.as_uri() + "?mode=ro&immutable=1"
    for label, uri in (("mode=ro", uri_ro), ("mode=ro+immutable", uri_immutable)):
        try:
            return sqlite3.connect(uri, uri=True, timeout=5.0), None
        except sqlite3.Error as e:
            attempts.append((label, f"{type(e).__name__}: {e}"))
        except OSError as e:
            attempts.append((label, f"{type(e).__name__}: {e}"))
    detail = "; ".join(f"{a}: {msg}" for a, msg in attempts)
    return None, detail


def _is_plain_no(text: str) -> bool:
    """True for messages that are only 'no' / 'NO' / 'No' (optional whitespace and !.)."""
    if not text or not text.strip():
        return False
    t = text.strip().strip("!.…").strip()
    return t.lower() == "no"


def _token_for_plain_no(pending: dict) -> str | None:
    """
    Resolve which promotion token a plain 'NO' refers to.
    Priority: last_notified_token if still pending; else sole remaining token.
    """
    by_token = pending.get("by_token") or {}
    if not isinstance(by_token, dict) or not by_token:
        return None
    last = str(pending.get("last_notified_token") or "").strip().lower()
    if last and last in by_token:
        return last
    keys = [str(k).strip().lower() for k in by_token.keys()]
    if len(keys) == 1:
        return keys[0]
    return None


def process_replies() -> int | None:
    """Scan new messages for NO / NO <token>. Returns rejection count, or None if setup/DB unavailable."""
    db_path = Path(os.environ.get("TERM_PROMOTION_MESSAGES_DB") or (Path.home() / "Library/Messages/chat.db"))
    if not db_path.is_file():
        print(f"ℹ️  Messages DB not found at {db_path} (grant Full Disk Access or skip).")
        return None

    pending = _load_pending()
    by_token = pending.setdefault("by_token", {})
    if not by_token:
        return 0

    mconn, open_err = _open_chat_db_ro(db_path)
    if not mconn:
        tip = (
            "System Settings → Privacy & Security → Full Disk Access "
            "(remove/re-add TermPromotionRepliesRunner.app after updates)."
        )
        print(
            f"ℹ️  Could not open {db_path} read-only: {open_err or 'unknown'}. "
            f"(interpreter={sys.executable}) {tip}",
            flush=True,
        )
        return None

    last_rid = int(pending.get("last_message_rowid") or 0)
    max_rid = last_rid
    n_done = 0
    rows: list = []

    try:
        cur = mconn.execute(
            """
            SELECT ROWID, text FROM message
            WHERE text IS NOT NULL AND LENGTH(text) >= 2
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

        token_to_pop: str | None = None
        m = NO_TOKEN_RE.search(text)
        from_plain_no = False
        if m:
            token_to_pop = m.group(1).lower()
        elif _is_plain_no(text):
            from_plain_no = True
            pending = _load_pending()
            token_to_pop = _token_for_plain_no(pending)
            if not token_to_pop:
                print(
                    "ℹ️  Plain 'NO' ignored: multiple promotions pending — reply NO <token> from the message."
                )
                continue
        else:
            continue

        entry = pop_pending_token(token_to_pop)
        if not entry:
            continue
        term = (entry.get("term") or "").strip()
        if not term:
            continue

        with dash._get_connection() as conn:
            note = (
                "Rejected: plain NO reply to promoted Overton term"
                if from_plain_no
                else "Rejected: SMS reply (NO token) to promoted Overton term"
            )
            if reject_promoted_term(conn, term, notes=note):
                conn.commit()
                n_done += 1
                print(f"✓ Rejected promoted term from reply: {term}")
            else:
                conn.commit()

        # Clear last_notified if we removed that token
        pending = _load_pending()
        lt = str(pending.get("last_notified_token") or "").lower()
        if lt == token_to_pop:
            pending["last_notified_token"] = ""
            pending["last_notified_term"] = ""
            save_pending(pending)

    pending = _load_pending()
    pending["last_message_rowid"] = max_rid
    save_pending(pending)
    return n_done


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    lock_path = STATE_DIR / "term_promotion_replies.lock"
    lock_fp = open(lock_path, "a+", encoding="utf-8")  # noqa: SIM115 — held until unlock
    try:
        try:
            fcntl.flock(lock_fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"SKIP {datetime.now(timezone.utc).isoformat()} (another instance is running)", flush=True)
            return
        started = datetime.now(timezone.utc).isoformat()
        print(f"BEGIN {started} pid={os.getpid()}", flush=True)
        n = process_replies()
        if n is None:
            print(f"END {datetime.now(timezone.utc).isoformat()} result=(aborted, see above)", flush=True)
            return
        if n > 0:
            print(f"Processed {n} rejection(s). Re-run site export to refresh Overton.")
        else:
            print("No matching NO / NO <token> replies to process.")
        print(f"END {datetime.now(timezone.utc).isoformat()} result={n}", flush=True)
    finally:
        fcntl.flock(lock_fp.fileno(), fcntl.LOCK_UN)
        lock_fp.close()


if __name__ == "__main__":
    main()
