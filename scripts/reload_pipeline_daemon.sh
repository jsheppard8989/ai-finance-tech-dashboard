#!/usr/bin/env bash
# Reload the pipeline interval runner as a standard user LaunchAgent.
# Run from repo root or anywhere; no administrator password is required.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${WORKSPACE_ROOT:-$REPO_ROOT}"
PLIST="com.scarcity.pipeline.daemon.plist"
DEST="${HOME}/Library/LaunchAgents/${PLIST}"
echo "Copying ${PLIST} to ${HOME}/Library/LaunchAgents/ and reloading..."
cp "${WORKSPACE}/docs/launchd/${PLIST}" "${DEST}"
launchctl unload "${DEST}" 2>/dev/null || true
launchctl load "${DEST}"
echo "Done. LaunchAgent is loaded. Check: launchctl list | grep scarcity.pipeline.daemon"
