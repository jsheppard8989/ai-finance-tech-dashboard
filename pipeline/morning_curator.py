#!/usr/bin/env python3
"""
Morning Podcast Curation Script
Checks for new podcasts and sends iMessage for approval
"""

import json
import subprocess
from pathlib import Path
from datetime import datetime

TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
STATE_DIR = Path.home() / ".openclaw/workspace/pipeline/state"
CURATION_LOG = STATE_DIR / "curation_log.json"


def get_episode_info(filename):
    """Get episode info from transcript file."""
    filepath = TRANSCRIPT_DIR / filename
    if not filepath.exists():
        return None
    
    size = filepath.stat().st_size
    if size < 1000:  # Skip stub files
        return None
    
    # Read first few lines for preview
    with open(filepath, 'r') as f:
        lines = f.readlines()[:5]
    
    preview = ' '.join([l.strip() for l in lines if l.strip()])[:200]
    
    # Map filename patterns to podcast names
    if 'EWWMN' in filename:
        podcast = "Monetary Matters with Jack Farley"
    elif 'IMP' in filename:
        podcast = "The Moonshot Podcast"
    elif 'jack_mallers' in filename.lower() or '417811310' in filename:
        podcast = "The Jack Mallers Show"
    elif 'dario' in filename.lower():
        podcast = "a16z Live (Dario Amodei)"
    elif 'elon' in filename.lower():
        podcast = "Moonshots with Peter Diamandis"
    elif 'peter_diamandis' in filename.lower():
        podcast = "Moonshots with Peter Diamandis"
    elif 'default' in filename:
        podcast = "a16z Live"
    else:
        podcast = "Unknown Podcast"
    
    return {
        'filename': filename,
        'podcast': podcast,
        'size_kb': round(size / 1024, 1),
        'preview': preview
    }


def get_unprocessed_episodes():
    """Get list of unprocessed transcript files."""
    unprocessed = []
    
    for txt_file in TRANSCRIPT_DIR.glob("*.txt"):
        info = get_episode_info(txt_file.name)
        if info:
            unprocessed.append(info)
    
    return unprocessed


def send_imessage(phone_number, message):
    """Send iMessage using the send_imessage.sh script."""
    script = Path.home() / ".openclaw/workspace/send_imessage.sh"
    
    if not script.exists():
        print(f"iMessage script not found at {script}")
        return False
    
    try:
        result = subprocess.run(
            [str(script), phone_number, message],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception as e:
        print(f"Failed to send iMessage: {e}")
        return False


def main():
    """Main function to check podcasts and request approval."""
    
    # Get unprocessed episodes
    episodes = get_unprocessed_episodes()
    
    if not episodes:
        print("No new podcasts to process.")
        return
    
    # Build message
    message_lines = [
        f"🎙️ Good morning! {len(episodes)} new podcast(s) ready for processing:",
        ""
    ]
    
    for i, ep in enumerate(episodes, 1):
        message_lines.append(f"{i}. {ep['podcast']}")
        message_lines.append(f"   Preview: {ep['preview'][:100]}...")
        message_lines.append("")
    
    message_lines.append("Reply with:")
    message_lines.append("• 'PROCESS ALL' - analyze all episodes")
    message_lines.append("• 'SKIP ALL' - skip today's batch")
    message_lines.append("• Numbers like '1,3,5' - process only those")
    message_lines.append("")
    message_lines.append("⏰ You have 30 minutes to reply before I skip today's batch.")
    
    message = "\n".join(message_lines)
    
    # Send to Jared
    phone = "+16306437437"
    
    print(f"Sending podcast list to {phone}...")
    print(f"Message:\n{message}")
    
    success = send_imessage(phone, message)
    
    if success:
        print("✓ iMessage sent successfully")
        
        # Save pending state
        pending_file = STATE_DIR / "pending_approval.json"
        with open(pending_file, 'w') as f:
            json.dump({
                'sent_at': datetime.now().isoformat(),
                'episodes': episodes,
                'expires_at': None  # Will be set by approval processor
            }, f, indent=2)
    else:
        print("✗ Failed to send iMessage")


if __name__ == "__main__":
    main()
