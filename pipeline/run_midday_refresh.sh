#!/usr/bin/env bash
#
# Midday site refresh: prices + charts + export (no heavy AI).
# Intended for the 12:00pm job instead of running pieces by hand.
#
# Steps:
#   1) Update intraday prices (cheap API calls)
#   2) Regenerate 2‑week charts and price_data.json
#   3) Rebuild site/data JSON + data.js (no auto git push here)
#
# This script is idempotent and safe to call from launchd/cron.

set -euo pipefail

WORKSPACE="${HOME}/.openclaw/workspace"
PIPELINE_DIR="${WORKSPACE}/pipeline"

cd "${PIPELINE_DIR}"

echo "=== Midday price + chart refresh ($(date)) ==="

echo "[1/3] Fetching latest prices..."
python3 fetch_prices.py

echo "[2/3] Generating charts..."
python3 generate_charts.py

echo "[3/3] Exporting site data..."
python3 export_data.py

echo "=== Midday refresh complete ==="

