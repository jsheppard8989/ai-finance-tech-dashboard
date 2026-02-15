#!/bin/bash
# Send iMessage via AppleScript
# Usage: ./send_imessage.sh "phone_number" "message"

PHONE="$1"
MESSAGE="$2"

if [ -z "$PHONE" ] || [ -z "$MESSAGE" ]; then
    echo "Usage: $0 <phone_number> <message>"
    exit 1
fi

osascript -e "tell application \"Messages\" to send \"$MESSAGE\" to buddy \"$PHONE\""
