#!/usr/bin/env bash
# Reload the pipeline LaunchDaemon so it picks up the plist from the repo.
# Run from workspace root. You'll be prompted for your Mac password.
set -e
WORKSPACE="${HOME}/.openclaw/workspace"
PLIST="com.openclaw.pipeline.daemon.plist"
echo "Copying ${PLIST} to /Library/LaunchDaemons/ and reloading..."
sudo cp "${WORKSPACE}/docs/launchd/${PLIST}" /Library/LaunchDaemons/
sudo chown root:wheel "/Library/LaunchDaemons/${PLIST}"
sudo chmod 644 "/Library/LaunchDaemons/${PLIST}"
sudo launchctl unload "/Library/LaunchDaemons/${PLIST}" 2>/dev/null || true
sudo launchctl load "/Library/LaunchDaemons/${PLIST}"
echo "Done. Daemon is loaded. Check: sudo launchctl list | grep openclaw.pipeline.daemon"
