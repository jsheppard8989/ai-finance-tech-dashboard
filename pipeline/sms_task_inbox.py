#!/usr/bin/env python3
"""
Phone → agent task inbox.

Accepts HTTP POST /task with JSON {"text": "fix the homepage debate player"} or form field `text`.
Appends to pipeline/state/agent_tasks.jsonl and optionally notifies via Pushover.

Run on your Mac (LAN or via ngrok/Cloudflare tunnel for Twilio SMS webhooks):

  python3 sms_task_inbox.py serve --port 8787

Twilio SMS webhook URL (example):
  https://YOUR-TUNNEL.example.com/task  (POST, Body=text)

Apple Shortcuts: "Get Contents of URL" POST JSON {"text": "..."} to the same endpoint.

Usage:
  python3 sms_task_inbox.py serve
  python3 sms_task_inbox.py list
  python3 sms_task_inbox.py drain   # print pending tasks
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from workspace_paths import STATE_DIR, WORKSPACE_ROOT as WORKSPACE

INBOX = STATE_DIR / "agent_tasks.jsonl"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_task(text: str, source: str = "http") -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    entry = {"at": _now(), "source": source, "text": text.strip(), "status": "pending"}
    with INBOX.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    return entry


def notify_task(text: str) -> None:
    script = WORKSPACE / "pushover.sh"
    if not script.is_file():
        return
    subprocess.run(
        [str(script), "Agent task queued", text[:900]],
        check=False,
        cwd=str(WORKSPACE),
    )


class TaskHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # noqa: ARG002
        return

    def _ok(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?")[0] not in ("/task", "/sms", "/"):
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        text = ""
        source = "http"
        ctype = (self.headers.get("Content-Type") or "").lower()
        if "application/json" in ctype:
            try:
                data = json.loads(raw or "{}")
                text = str(data.get("text") or data.get("Body") or data.get("message") or "")
            except json.JSONDecodeError:
                text = raw
        else:
            qs = parse_qs(raw)
            text = (qs.get("text") or qs.get("Body") or qs.get("body") or [raw])[0]
            if "twilio" in ctype or qs.get("From"):
                source = "twilio"
        text = text.strip()
        if not text:
            self._ok({"ok": False, "error": "empty text"})
            return
        entry = append_task(text, source=source)
        notify_task(text)
        self._ok({"ok": True, "queued": entry})


def serve(port: int) -> None:
    server = HTTPServer(("127.0.0.1", port), TaskHandler)
    print(f"Agent task inbox listening on http://127.0.0.1:{port}/task")
    print("Expose via ngrok/cloudflared for Twilio SMS. See docs/TEXT-TO-AGENT.md")
    server.serve_forever()


def list_tasks(limit: int = 20) -> None:
    if not INBOX.is_file():
        print("No tasks yet.")
        return
    lines = INBOX.read_text(encoding="utf-8").splitlines()
    for line in lines[-limit:]:
        print(line)


def main() -> int:
    ap = argparse.ArgumentParser(description="Queue agent tasks from phone/SMS/Shortcuts.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_serve = sub.add_parser("serve", help="Run HTTP inbox")
    p_serve.add_argument("--port", type=int, default=8787)
    sub.add_parser("list", help="Show recent tasks")
    args = ap.parse_args()
    if args.cmd == "serve":
        serve(args.port)
    elif args.cmd == "list":
        list_tasks()
    return 0


if __name__ == "__main__":
    sys.exit(main())
