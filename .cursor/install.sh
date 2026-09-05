#!/usr/bin/env bash
# Idempotent dependency bootstrap for the AI Finance Tech Dashboard.
# Safe to run repeatedly: pip resolves already-satisfied requirements as no-ops.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

echo "[install] Python: $(python3 --version)"
python3 -m pip install --upgrade pip
python3 -m pip install -r pipeline/requirements.txt

echo "[install] Done. Site data present: $([ -f site/data/data.js ] && echo yes || echo no)"
