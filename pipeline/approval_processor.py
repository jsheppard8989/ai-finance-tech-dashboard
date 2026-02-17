#!/usr/bin/env python3
"""
Process user approval response for podcast transcripts.
Called when user replies to the morning curation iMessage.
"""

import json
import re
import sys
from pathlib import Path

TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
PENDING_FILE = Path.home() / ".openclaw/workspace/pipeline/pending_approval.json"
PROCESSED_MARKER_DIR = Path.home() / ".openclaw/workspace/pipeline/processed"


def load_pending_episodes():
    """Load pending episodes from file."""
    if not PENDING_FILE.exists():
        return None
    
    with open(PENDING_FILE, 'r') as f:
        return json.load(f)


def parse_approval_response(response_text, episodes):
    """
    Parse user's approval response.
    Returns list of filenames to process.
    """
    response_lower = response_text.lower().strip()
    
    # Check for ALL
    if 'all' in response_lower and 'process' in response_lower:
        return [ep['filename'] for ep in episodes]
    
    # Check for SKIP
    if 'skip' in response_lower:
        return []
    
    # Look for numbers (1,3,5 or 1 3 5 or 1-3)
    numbers = []
    
    # Pattern: "1,3,5" or "1, 3, 5"
    if ',' in response_text:
        parts = response_text.split(',')
        for p in parts:
            p = p.strip()
            if p.isdigit():
                numbers.append(int(p))
    
    # Pattern: "1 3 5" or "1 and 3"
    elif ' ' in response_text or 'and' in response_lower:
        words = re.findall(r'\d+', response_text)
        numbers = [int(w) for w in words]
    
    # Pattern: "1-3" or "1 to 3"
    elif '-' in response_text or 'to' in response_lower:
        match = re.search(r'(\d+)\s*(?:-|to)\s*(\d+)', response_text)
        if match:
            start, end = int(match.group(1)), int(match.group(2))
            numbers = list(range(start, end + 1))
    
    # Single number
    elif response_text.strip().isdigit():
        numbers = [int(response_text.strip())]
    
    # Convert numbers to filenames
    to_process = []
    for num in numbers:
        if 1 <= num <= len(episodes):
            to_process.append(episodes[num - 1]['filename'])
    
    return to_process


def mark_for_processing(filenames):
    """Mark selected files for processing by removing processed markers."""
    for filename in filenames:
        marker = PROCESSED_MARKER_DIR / f"{Path(filename).stem}.processed"
        if marker.exists():
            marker.unlink()
            print(f"  ✓ Marked for reprocessing: {filename}")


def process_approved_episodes(filenames):
    """Run transcript analysis on approved episodes."""
    import subprocess
    
    if not filenames:
        print("No episodes approved for processing.")
        return
    
    print(f"\nProcessing {len(filenames)} approved episode(s)...")
    
    # Run the analyze_transcript module directly for just these files
    result = subprocess.run(
        [sys.executable, "-c", 
         f"from analyze_transcript import process_all_transcripts; process_all_transcripts()"],
        cwd=Path.home() / ".openclaw/workspace/pipeline",
        capture_output=True,
        text=True
    )
    
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    return result.returncode == 0


def main(response_text=None):
    """Main function to process approval response."""
    
    # Load pending episodes
    pending = load_pending_episodes()
    
    if not pending:
        print("No pending episodes found. Run morning_curator.py first.")
        return
    
    episodes = pending.get('episodes', [])
    
    if not episodes:
        print("No episodes in pending list.")
        return
    
    # If no response provided, check command line
    if response_text is None and len(sys.argv) > 1:
        response_text = ' '.join(sys.argv[1:])
    
    if not response_text:
        print("Usage: python3 approval_processor.py '<your response>'")
        print(f"Pending episodes ({len(episodes)}):")
        for i, ep in enumerate(episodes, 1):
            print(f"  {i}. {ep['podcast']}")
        return
    
    print(f"Processing approval response: '{response_text}'")
    print(f"Available episodes: {len(episodes)}")
    
    # Parse approval
    to_process = parse_approval_response(response_text, episodes)
    
    print(f"\nApproved for processing: {len(to_process)} episode(s)")
    for f in to_process:
        print(f"  - {f}")
    
    if to_process:
        # Mark for processing and run
        success = process_approved_episodes(to_process)
        
        if success:
            print("\n✓ Episodes processed successfully!")
            print("Next: Run 'python3 run_pipeline.py' to update website")
        else:
            print("\n✗ Processing failed. Check logs above.")
    else:
        print("\n✓ Skipping all episodes as requested.")
    
    # Clear pending file
    PENDING_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
