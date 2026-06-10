#!/bin/bash
# Re-copy conda’s interpreter into TermPromotionRepliesRunner.app after e.g. `conda upgrade python`.
# The binary must live at Contents/MacOS/TermPromotionRepliesRunner (CFBundleExecutable).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
SRC="${CONDA_PYTHON:-/Users/jaredsheppard/anaconda3/bin/python3.10}"
DST="$ROOT/TermPromotionRepliesRunner.app/Contents/MacOS/TermPromotionRepliesRunner"
test -x "$SRC" || { echo "missing: $SRC" >&2; exit 1; }
cp "$SRC" "$DST"
chmod +x "$DST"
codesign --force --deep -s - "$ROOT/TermPromotionRepliesRunner.app"
