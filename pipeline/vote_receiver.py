#!/usr/bin/env python3
"""
Vote receiver - lightweight HTTP server to capture votes from website.
Stores votes in JSON file for processing by pipeline.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

VOTE_FILE = Path.home() / ".openclaw/workspace/pipeline/state/votes.json"

class VoteHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()
    
    def do_POST(self):
        if self.path == '/vote':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                vote = json.loads(post_data)
                vote['timestamp'] = datetime.now().isoformat()
                
                # Load existing votes
                votes = []
                if VOTE_FILE.exists():
                    with open(VOTE_FILE, 'r') as f:
                        votes = json.load(f)
                
                # Add new vote
                votes.append(vote)
                
                # Save
                with open(VOTE_FILE, 'w') as f:
                    json.dump(votes, f, indent=2)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({'status': 'ok'}).encode())
                
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'error': str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        # Suppress default logging
        pass

def ensure_vote_file():
    """Ensure vote file exists."""
    if not VOTE_FILE.exists():
        VOTE_FILE.write_text('[]')

def start_server(port=8765):
    """Start the vote receiver server."""
    ensure_vote_file()
    server = HTTPServer(('localhost', port), VoteHandler)
    print(f"Vote receiver listening on port {port}")
    server.serve_forever()

if __name__ == '__main__':
    start_server()
