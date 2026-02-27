#!/usr/bin/env python3
import os
import subprocess
import json
import time
from pathlib import Path

# Define path and command
WORKSPACE = Path.home() / ".openclaw/workspace"
CONTACT_API_SCRIPT = WORKSPACE / "contact_api.py"

def is_running():
    # Check if contact_api.py is running
    result = subprocess.run(['pgrep', '-f', 'contact_api.py'], stdout=subprocess.PIPE)
    return bool(result.stdout)

def start_server():
    # Start the contact API server
    process = subprocess.Popen(['python3', str(CONTACT_API_SCRIPT)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(2)  # Wait for server to start
    return process

if __name__ == '__main__':
    server_status = ""  
    if is_running():
        server_status = 'running'
    else:
        start_server()
        server_status = 'started'

    # Create morning notification message
    message = f"Good morning! The contact server is {server_status}."

    # (In production, you might replace this with a push notification)
    print(message)