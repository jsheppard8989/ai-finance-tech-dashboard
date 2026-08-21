#!/bin/bash
# Local term review UI (127.0.0.1 only); opens the browser automatically.
cd "$(dirname "$0")"
exec python3 term_admin_server.py
