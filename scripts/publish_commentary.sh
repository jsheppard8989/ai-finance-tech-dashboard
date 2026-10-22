#!/usr/bin/env bash
# Publish Ric's Market Commentary: scripts/publish_commentary.sh /workspace/ric-commentary/YYYY-MM-DD.md
# Validates the post, opens a PR adding it under commentary/, squash-merges; the merge redeploys the site.
set -euo pipefail
SRC="${1:?usage: publish_commentary.sh /workspace/ric-commentary/YYYY-MM-DD.md}"
REPO="${REPO_DIR:-/workspace/ai-finance-tech-dashboard}"
NAME="$(basename "$SRC")"; DAY="${NAME%.md}"
cd "$REPO"
git fetch -q origin main
python3 pipeline/export_commentary.py --check "$SRC"
WT="$(mktemp -d /tmp/commentary-XXXX)"; BR="commentary/$DAY-$(date +%H%M%S)"
git worktree add -q -b "$BR" "$WT" origin/main
cp "$SRC" "$WT/commentary/$NAME"
( cd "$WT" && git add "commentary/$NAME" && git commit -qm "Market Commentary: $DAY" && git push -q -u origin "$BR" \
  && gh pr create --base main --head "$BR" --title "Market Commentary: $DAY" --body "Adds commentary/$NAME" )
gh pr merge "$BR" --squash --delete-branch
git worktree remove --force "$WT"
echo "Merged. Deploy runs automatically; live in ~2 min at https://jsheppard8989.github.io/ai-finance-tech-dashboard/"
