#!/bin/bash
# Podcast dashboard site QA.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/pipeline"
python3 site_qa.py --notify "$@"
