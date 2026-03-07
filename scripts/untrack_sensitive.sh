#!/usr/bin/env bash
# Stop tracking Openclaw and sensitive files (files stay on disk).
# Run from workspace root: ./scripts/untrack_sensitive.sh
# Then: git add .gitignore && git commit -m "Stop tracking Openclaw and sensitive files" && git push origin main

set -e
cd "$(dirname "$0")/.."

echo "Untracking Openclaw and sensitive files (required)..."
git rm --cached AGENTS.md SOUL.md USER.md IDENTITY.md MEMORY.md HEARTBEAT.md TOOLS.md bip39.txt pending_contacts.json 2>/dev/null || true
git rm -r --cached memory/ 2>/dev/null || true

# Optional: uncomment to also stop tracking pipeline state and inbox
# echo "Untracking pipeline/state and pipeline/inbox (optional)..."
# git rm -r --cached pipeline/state/ 2>/dev/null || true
# git rm -r --cached pipeline/inbox/ 2>/dev/null || true

echo "Done. Staged: untracked paths. Files remain on disk."
echo "Next: git add .gitignore && git commit -m \"Stop tracking Openclaw and sensitive files; add to .gitignore\" && git push origin main"
