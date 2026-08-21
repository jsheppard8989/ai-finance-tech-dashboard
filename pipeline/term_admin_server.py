#!/usr/bin/env python3
"""
Local term admin UI — localhost only.

  cd pipeline && python3 term_admin_server.py
  open http://127.0.0.1:8765

Env: TERM_ADMIN_PORT (default 8765)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))

import term_admin_service as svc  # noqa: E402

STATIC_DIR = Path(__file__).parent / "term_admin"
DEFAULT_PORT = 8765


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_json(handler: BaseHTTPRequestHandler) -> dict:
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    return json.loads(raw.decode("utf-8"))


class TermAdminHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        print(f"[term-admin] {self.address_string()} {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path == "/api/review-queue":
            return _json_response(self, 200, svc.list_review_queue())
        if path == "/api/terms":
            return _json_response(self, 200, svc.list_all_terms())
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            return self._serve_static(rel, self._guess_type(rel))
        _json_response(self, 404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            data = _read_json(self)
            if path == "/api/suggest":
                result = svc.suggest_term(
                    data.get("term", ""),
                    data.get("definition"),
                    data.get("investment_implications"),
                )
                return _json_response(self, 201, {"ok": True, "result": result})

            if path.startswith("/api/pending/") and path.endswith("/approve"):
                tid = int(path.split("/")[3])
                show = data.get("show_on_main", True)
                result = svc.promote_suggested(tid, show_on_main=bool(show))
                return _json_response(self, 200, {"ok": True, "result": result})

            if path.startswith("/api/pending/") and path.endswith("/reject"):
                tid = int(path.split("/")[3])
                result = svc.reject_suggested(tid, data.get("reason") or "Rejected via term admin UI")
                return _json_response(self, 200, {"ok": True, "result": result})

            if path.startswith("/api/overton/") and path.endswith("/show"):
                term = data.get("term") or ""
                result = svc.show_overton_on_site(term)
                return _json_response(self, 200, {"ok": True, "result": result})

            if path.startswith("/api/overton/") and path.endswith("/hide"):
                term = data.get("term") or ""
                result = svc.hide_overton_from_site(term)
                return _json_response(self, 200, {"ok": True, "result": result})

            if path.startswith("/api/overton/") and path.endswith("/reject"):
                term = data.get("term") or ""
                result = svc.reject_overton(term, data.get("reason") or "Rejected via term admin UI")
                return _json_response(self, 200, {"ok": True, "result": result})

            _json_response(self, 404, {"error": "Not found"})
        except ValueError as e:
            _json_response(self, 400, {"ok": False, "error": str(e)})
        except Exception as e:
            _json_response(self, 500, {"ok": False, "error": str(e)})

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        try:
            data = _read_json(self)
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3 and parts[0] == "api":
                kind, sid = parts[1], int(parts[2])
                if kind == "pending":
                    result = svc.update_suggested(
                        sid,
                        definition=data.get("definition"),
                        investment_implications=data.get("investment_implications"),
                    )
                elif kind == "overton":
                    result = svc.update_overton(
                        sid,
                        description=data.get("description") or data.get("definition"),
                        investment_implications=data.get("investment_implications"),
                    )
                elif kind == "definitions":
                    result = svc.update_definition(
                        sid,
                        definition=data.get("definition"),
                        investment_implications=data.get("investment_implications"),
                    )
                else:
                    return _json_response(self, 404, {"error": "Not found"})
                return _json_response(self, 200, {"ok": True, "result": result})
            _json_response(self, 404, {"error": "Not found"})
        except ValueError as e:
            _json_response(self, 400, {"ok": False, "error": str(e)})
        except Exception as e:
            _json_response(self, 500, {"ok": False, "error": str(e)})

    def _guess_type(self, name: str) -> str:
        if name.endswith(".css"):
            return "text/css; charset=utf-8"
        if name.endswith(".js"):
            return "application/javascript; charset=utf-8"
        return "application/octet-stream"

    def _serve_static(self, name: str, content_type: str) -> None:
        file_path = (STATIC_DIR / name).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            _json_response(self, 403, {"error": "Forbidden"})
            return
        if not file_path.is_file():
            _json_response(self, 404, {"error": "Not found"})
            return
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local-only term review UI.")
    parser.add_argument("--no-open", action="store_true", help="Do not open the browser automatically.")
    args = parser.parse_args()
    port = int(os.environ.get("TERM_ADMIN_PORT", DEFAULT_PORT))
    host = "127.0.0.1"
    server = ThreadingHTTPServer((host, port), TermAdminHandler)
    url = f"http://{host}:{port}"
    print("=" * 60)
    print("Term Admin (local only)")
    print(f"  {url}")
    print("  Ctrl+C to stop")
    print("=" * 60)
    if not args.no_open:
        threading.Timer(0.3, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
        server.server_close()


if __name__ == "__main__":
    main()
