#!/usr/bin/env python3
"""
When a suggested term is auto-promoted into Definitions + Overton, notify the user by iMessage
and record a short token so they can reply "NO <token>" to remove it (see process_term_promotion_replies.py).

Env:
  IMESSAGE_NOTIFY_PHONE — E.164, default +16306437437 (same as morning_curator)
  TERM_PROMOTION_REPLY_SECRET — optional; included in token hash (set in production)
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

WORKSPACE = Path.home() / ".openclaw/workspace"
PIPELINE = WORKSPACE / "pipeline"
STATE_DIR = PIPELINE / "state"
PENDING_FILE = STATE_DIR / "pending_term_promotions.json"
IMESSAGE_SCRIPT = WORKSPACE / "send_imessage.sh"


def _reply_token(term_id: int, term: str) -> str:
    secret = (os.environ.get("TERM_PROMOTION_REPLY_SECRET") or "openclaw-term-promo").encode()
    raw = f"{term_id}:{term}".encode("utf-8")
    h = hashlib.sha256(secret + raw).hexdigest()
    return h[:8]


def _escape_applescript_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _load_pending() -> Dict[str, Any]:
    if not PENDING_FILE.exists():
        return {"by_token": {}, "last_message_rowid": 0}
    try:
        data = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except Exception:
        data = {"by_token": {}, "last_message_rowid": 0}
    # Normalize token keys to lowercase for reliable matching
    bt = data.get("by_token")
    if isinstance(bt, dict):
        data["by_token"] = {str(k).lower(): v for k, v in bt.items()}
    else:
        data["by_token"] = {}
    return data


def save_pending(data: Dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def notify_promoted_term(term_data: Dict[str, Any]) -> None:
    """
    Send iMessage asking if they want to keep the term; record token for NO <token> replies.
    """
    term = (term_data.get("term") or "").strip()
    tid = term_data.get("id")
    if not term or tid is None:
        return
    if not IMESSAGE_SCRIPT.is_file():
        return

    phone = (os.environ.get("IMESSAGE_NOTIFY_PHONE") or "+16306437437").strip()
    token = _reply_token(int(tid), term)

    pending = _load_pending()
    by_token = pending.setdefault("by_token", {})
    by_token[token.lower()] = {
        "term_id": int(tid),
        "term": term,
        "notified_at": datetime.now(timezone.utc).isoformat(),
    }
    save_pending(pending)

    # Keep message short for SMS; token must be copy-pastable
    body = (
        f'Scarcity: promoted to Overton — "{term}". '
        f"Keep it? Do nothing. Remove? Reply exactly: NO {token}"
    )
    escaped = _escape_applescript_string(body)
    script = f'tell application "Messages" to send "{escaped}" to buddy "{phone}"'
    try:
        subprocess.run(
            ["osascript", "-e", script],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except Exception:
        pass


def pop_pending_token(token: str) -> Dict[str, Any] | None:
    """Remove and return pending entry for token, or None."""
    pending = _load_pending()
    by_token = pending.setdefault("by_token", {})
    key = (token or "").strip().lower()
    v = by_token.pop(key, None)
    if v is not None:
        save_pending(pending)
        return v if isinstance(v, dict) else None
    return None
