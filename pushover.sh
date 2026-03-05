#!/bin/bash
# Pushover notification script
# Usage: PUSHOVER_USER_KEY=... PUSHOVER_APP_TOKEN=... ./pushover.sh "Title" "Message" [priority]
#
# IMPORTANT: Do NOT hardcode real keys in this file.
# Set them via environment variables instead:
#   export PUSHOVER_USER_KEY="your-user-key"
#   export PUSHOVER_APP_TOKEN="your-app-token"

if [ -z "$PUSHOVER_USER_KEY" ] || [ -z "$PUSHOVER_APP_TOKEN" ]; then
  echo "Error: PUSHOVER_USER_KEY and PUSHOVER_APP_TOKEN must be set in the environment." >&2
  exit 1
fi

USER_KEY="$PUSHOVER_USER_KEY"
APP_TOKEN="$PUSHOVER_APP_TOKEN"

TITLE="${1:-OpenClaw Alert}"
MESSAGE="${2:-Notification from OpenClaw}"
PRIORITY="${3:-0}"

curl -s \
  --form-string "token=$APP_TOKEN" \
  --form-string "user=$USER_KEY" \
  --form-string "title=$TITLE" \
  --form-string "message=$MESSAGE" \
  --form-string "priority=$PRIORITY" \
  https://api.pushover.net/1/messages.json

echo ""

