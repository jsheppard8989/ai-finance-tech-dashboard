#!/usr/bin/env bash
# Reload the pipeline interval runner as a standard user LaunchAgent.
# Run from repo root or anywhere; no administrator password is required.
set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="${WORKSPACE_ROOT:-$REPO_ROOT}"
PLIST="com.scarcity.pipeline.daemon.plist"
DEPRECATED="com.scarcity.pipeline.schedule.plist"
DEST="${HOME}/Library/LaunchAgents/${PLIST}"
DEPRECATED_DEST="${HOME}/Library/LaunchAgents/${DEPRECATED}"
echo "Unloading deprecated calendar scheduler (if present)..."
launchctl unload "${DEPRECATED_DEST}" 2>/dev/null || true
rm -f "${DEPRECATED_DEST}"
echo "Copying ${PLIST} to ${HOME}/Library/LaunchAgents/ and reloading..."
cp "${WORKSPACE}/docs/launchd/${PLIST}" "${DEST}"
launchctl unload "${DEST}" 2>/dev/null || true
launchctl load "${DEST}"
echo "Done. Active scheduler: com.scarcity.pipeline.daemon"
echo "Check: launchctl list | grep scarcity.pipeline"
