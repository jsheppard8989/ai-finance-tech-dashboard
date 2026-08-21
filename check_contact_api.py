#!/usr/bin/env python3
import os
import subprocess
import json
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(_REPO / "pipeline"))
from workspace_paths import WORKSPACE_ROOT as WORKSPACE

# Define path and command
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