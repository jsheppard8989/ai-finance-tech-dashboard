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
# Physical path: /tmp is a symlink on macOS, and git worktree list reports the resolved path.
WT="$(cd "$(mktemp -d /tmp/commentary-XXXX)" && pwd -P)"; BR="commentary/$DAY-$(date +%H%M%S)"
# Idempotent teardown, also run on failure. gh pr merge --delete-branch (gh >= 2.103) may already
# have removed the worktree and local branch, so every step tolerates "already gone".
cleanup() {
  if git -C "$REPO" worktree list --porcelain | grep -qxF "worktree $WT"; then
    git -C "$REPO" worktree remove --force "$WT" 2>/dev/null || true
  fi
  git -C "$REPO" worktree prune 2>/dev/null || true
  rm -rf "$WT"
  git -C "$REPO" worktree prune 2>/dev/null || true
  git -C "$REPO" branch -D "$BR" >/dev/null 2>&1 || true
}
trap cleanup EXIT
git worktree add -q -b "$BR" "$WT" origin/main
cp "$SRC" "$WT/commentary/$NAME"
( cd "$WT" && git add "commentary/$NAME" && git commit -qm "Market Commentary: $DAY" && git push -q -u origin "$BR" \
  && gh pr create --base main --head "$BR" --title "Market Commentary: $DAY" --body "Adds commentary/$NAME" )
gh pr merge "$BR" --squash --delete-branch
echo "Merged. Deploy runs automatically; live in ~2 min at https://jsheppard8989.github.io/ai-finance-tech-dashboard/"
