#!/bin/bash
# Pushover notification script
# Usage: ./pushover.sh "Title" "Message" [priority]

USER_KEY="uo48fj98byqex2bt8jvercic38qze2"
APP_TOKEN="a8p75vg3vep6p4grpncktbrip652jr"

TITLE="${1:-OpenClaw Alert}"
MESSAGE="${2:-Notification from 6AIndolf}"
PRIORITY="${3:-0}"

curl -s \
  --form-string "token=$APP_TOKEN" \
  --form-string "user=$USER_KEY" \
  --form-string "title=$TITLE" \
  --form-string "message=$MESSAGE" \
  --form-string "priority=$PRIORITY" \
  https://api.pushover.net/1/messages.json

echo ""
