#!/usr/bin/env python3
"""
contact_api.py — lightweight local API to capture contact-form submissions
and trigger a pushover notification.
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json, time, subprocess
from datetime import datetime
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw/workspace"
PENDING_FILE = WORKSPACE / "pending_contacts.json"
PUSHOVER_SCRIPT = WORKSPACE / "pushover.sh"

class ContactHandler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200):
        self.send_response(status)
        self.send_header('Content-type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path != '/contact':
            self._set_headers(404)
            self.wfile.write(json.dumps({'error': 'Invalid endpoint'}).encode())
            return

        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            name = data.get('name') or 'Anonymous'
            contact = data.get('contact')
            message = data.get('message', '')
            wants_weekly = data.get('wantsWeekly', False)

            if not contact:
                self._set_headers(400)
                self.wfile.write(json.dumps({'error': 'Missing contact'}).encode())
                return

            pending_entry = {
                'id': int(time.time()),
                'name': name,
                'contact': contact,
                'message': message,
                'wantsWeekly': wants_weekly,
                'submittedAt': datetime.now().isoformat()
            }

            # Load existing pending data
            if PENDING_FILE.exists():
                with open(PENDING_FILE, 'r') as f:
                    pending_data = json.load(f)
            else:
                pending_data = {'pending': []}

            pending_data['pending'].append(pending_entry)

            with open(PENDING_FILE, 'w') as f:
                json.dump(pending_data, f, indent=2)

            # Trigger pushover notification
            if PUSHOVER_SCRIPT.exists():
                try:
                    subprocess.run([
                        str(PUSHOVER_SCRIPT),
                        "New Contact",
                        f"{name} ({contact}) just signed up.",
                        "0"
                    ])
                except Exception as e:
                    print('Pushover error:', e)

            self._set_headers(200)
            self.wfile.write(json.dumps({'status': 'ok'}).encode())
        except Exception as e:
            self._set_headers(500)
            self.wfile.write(json.dumps({'error': str(e)}).encode())


def run(server_class=HTTPServer, handler_class=ContactHandler, port=8765):
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    print(f"✅ Contact API running on http://localhost:{port}/contact")
    httpd.serve_forever()


if __name__ == '__main__':
    run()
