#!/usr/bin/env python3
"""
When a suggested term is auto-promoted into Definitions + Overton, notify the user by iMessage
and record a short token. They can reply "NO <token>" or a plain "NO" / "No" to remove it
(see process_term_promotion_replies.py; plain NO targets the last notified promotion).

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

from workspace_paths import STATE_DIR, WORKSPACE_ROOT as WORKSPACE

PENDING_FILE = STATE_DIR / "pending_term_promotions.json"
IMESSAGE_SCRIPT = WORKSPACE / "send_imessage.sh"
PUSHOVER_SCRIPT = WORKSPACE / "pushover.sh"
NOTIFY_LOG_FILE = STATE_DIR / "term_promotion_notify_log.jsonl"


def _reply_token(term_id: int, term: str) -> str:
    secret = (os.environ.get("TERM_PROMOTION_REPLY_SECRET") or "term-promo-default-secret").encode()
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


def _append_notify_log(entry: Dict[str, Any]) -> None:
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with NOTIFY_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except Exception:
        pass


def _send_fallback_notification(title: str, message: str) -> None:
    if not PUSHOVER_SCRIPT.is_file():
        return
    try:
        subprocess.run(
            [str(PUSHOVER_SCRIPT), title, message, "0"],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except Exception:
        pass


def notify_promoted_term(term_data: Dict[str, Any]) -> None:
    """
    Send iMessage asking if they want to keep the term; record token for NO <token> replies.
    """
    term = (term_data.get("term") or "").strip()
    tid = term_data.get("id")
    if not term or tid is None:
        return
    if not IMESSAGE_SCRIPT.is_file():
        _append_notify_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "term": term,
                "term_id": tid,
                "status": "skipped",
                "reason": "send_imessage.sh missing",
            }
        )
        _send_fallback_notification(
            "Term promotion notification skipped",
            f'Promoted "{term}" but send_imessage.sh was not found; no iMessage sent.',
        )
        return

    phone = (os.environ.get("IMESSAGE_NOTIFY_PHONE") or "+16306437437").strip()
    token = _reply_token(int(tid), term)

    pending = _load_pending()
    by_token = pending.setdefault("by_token", {})
    tl = token.lower()
    by_token[tl] = {
        "term_id": int(tid),
        "term": term,
        "notified_at": datetime.now(timezone.utc).isoformat(),
    }
    # Plain "NO" / "No" replies target the most recently notified promotion (see process_term_promotion_replies.py).
    pending["last_notified_token"] = tl
    pending["last_notified_term"] = term
    pending["last_notified_at"] = datetime.now(timezone.utc).isoformat()
    save_pending(pending)

    # Keep message short for SMS; token must be copy-pastable
    body = (
        f'Scarcity: promoted to Overton — "{term}". '
        f"Keep it? Do nothing. Remove? Reply exactly: NO {token}"
    )
    escaped = _escape_applescript_string(body)
    script = f'tell application "Messages" to send "{escaped}" to buddy "{phone}"'
    try:
        run = subprocess.run(
            ["osascript", "-e", script],
            cwd=str(WORKSPACE),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        if run.returncode == 0:
            _append_notify_log(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "term": term,
                    "term_id": int(tid),
                    "token": tl,
                    "status": "sent",
                }
            )
            return
        stderr = (run.stderr or "").strip()
        stdout = (run.stdout or "").strip()
        _append_notify_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "term": term,
                "term_id": int(tid),
                "token": tl,
                "status": "failed",
                "returncode": run.returncode,
                "stderr": stderr[:500],
                "stdout": stdout[:500],
            }
        )
        _send_fallback_notification(
            "Term promotion iMessage failed",
            f'Promoted "{term}" but osascript could not send iMessage (rc={run.returncode}). '
            f"See term_promotion_notify_log.jsonl for details.",
        )
    except Exception as e:
        _append_notify_log(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "term": term,
                "term_id": int(tid),
                "token": tl,
                "status": "error",
                "error": str(e)[:500],
            }
        )
        _send_fallback_notification(
            "Term promotion iMessage error",
            f'Promoted "{term}" but iMessage send raised an exception. Check term_promotion_notify_log.jsonl.',
        )


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
