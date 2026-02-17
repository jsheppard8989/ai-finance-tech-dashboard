#!/usr/bin/env python3
"""
Process user approval response for podcast transcripts.
Downloads, transcribes, and analyzes ONLY approved episodes.
"""

import json
import re
import sys
import subprocess
from pathlib import Path
from datetime import datetime

TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
PENDING_FILE = Path.home() / ".openclaw/workspace/pipeline/pending_approval.json"
CURATED_FILE = Path.home() / ".openclaw/workspace/pipeline/curated_episodes.json"

def load_pending_episodes():
    """Load pending episodes from file."""
    if not PENDING_FILE.exists():
        return None
    
    with open(PENDING_FILE, 'r') as f:
        return json.load(f)

def load_curated_episodes():
    """Load curated episodes with audio URLs."""
    if not CURATED_FILE.exists():
        return {}
    
    with open(CURATED_FILE, 'r') as f:
        return json.load(f)

def parse_approval_response(response_text, episodes):
    """Parse user's approval response."""
    response_lower = response_text.lower().strip()
    
    # Check for ALL
    if 'all' in response_lower and 'process' in response_lower:
        return [ep for ep in episodes]
    
    # Check for SKIP
    if 'skip' in response_lower:
        return []
    
    # Look for numbers
    numbers = []
    
    # Pattern: "1,3,5"
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
    
    # Convert numbers to episode dicts
    to_process = []
    for num in numbers:
        if 1 <= num <= len(episodes):
            to_process.append(episodes[num - 1])
    
    return to_process

def download_and_transcribe(episode, curated_data):
    """Download and transcribe a single approved episode."""
    import urllib.request
    import os
    
    audio_url = episode.get('audio_url')
    if not audio_url:
        print(f"  ✗ No audio URL for {episode.get('title', 'Unknown')}")
        return None
    
    # Create safe filename
    podcast_name = episode.get('podcast', 'unknown').replace(' ', '_')
    episode_title = episode.get('title', 'episode')[:50].replace(' ', '_')
    safe_name = f"{podcast_name}_{episode_title}_{datetime.now().strftime('%Y%m%d')}"
    safe_name = re.sub(r'[^\w\-]', '_', safe_name)
    
    audio_path = TRANSCRIPT_DIR.parent / "audio" / f"{safe_name}.mp3"
    transcript_path = TRANSCRIPT_DIR / f"{safe_name}.txt"
    
    audio_path.parent.mkdir(exist_ok=True)
    
    try:
        # Download audio
        print(f"  ↓ Downloading audio...")
        req = urllib.request.Request(audio_url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'
        })
        
        with urllib.request.urlopen(req, timeout=300) as response:
            with open(audio_path, 'wb') as f:
                f.write(response.read())
        
        print(f"  ✓ Downloaded: {audio_path}")
        
        # Transcribe using LOCAL Whisper (free, no API costs)
        print(f"  🎤 Transcribing with local Whisper (FREE)...")
        result = subprocess.run(
            [sys.executable, "transcribe_local.py", str(audio_path), safe_name],
            cwd=Path(__file__).parent,
            capture_output=True,
            text=True,
            timeout=1800  # 30 min timeout for long episodes
        )
        
        if result.returncode == 0:
            print(f"  ✓ Transcribed: {transcript_path}")
            return str(transcript_path)
        else:
            print(f"  ✗ Transcription failed: {result.stderr[:200]}")
            return None
            
    except Exception as e:
        print(f"  ✗ Error: {str(e)[:100]}")
        return None

def analyze_transcript(transcript_path):
    """Run AI analysis on transcript."""
    print(f"  🤖 Running AI analysis...")
    
    # Import and run analysis
    try:
        from analyze_transcript import process_all_transcripts
        result = process_all_transcripts()
        print(f"  ✓ Analysis complete")
        return True
    except Exception as e:
        print(f"  ✗ Analysis failed: {e}")
        return False

def run_full_pipeline_export():
    """Run pipeline export and push to GitHub."""
    print(f"\n🚀 Running full pipeline export...")
    
    result = subprocess.run(
        [sys.executable, "run_pipeline.py"],
        cwd=Path(__file__).parent,
        capture_output=True,
        text=True,
        timeout=300
    )
    
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    
    if result.returncode == 0:
        print("\n✓ Pipeline complete! Website updating...")
        return True
    else:
        print("\n✗ Pipeline failed")
        return False

def main(response_text=None):
    """Main function to process approval response."""
    
    # Load pending episodes
    pending = load_pending_episodes()
    curated = load_curated_episodes()
    
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
        print(f"\nPending episodes ({len(episodes)}):")
        for i, ep in enumerate(episodes, 1):
            podcast = ep.get('podcast', 'Unknown')
            title = ep.get('title', 'No title')[:60]
            print(f"  {i}. {podcast}")
            print(f"     {title}")
        return
    
    print(f"="*60)
    print(f"APPROVAL PROCESSING")
    print(f"="*60)
    print(f"Response: '{response_text}'")
    print(f"Available: {len(episodes)} episodes")
    
    # Parse approval
    approved_episodes = parse_approval_response(response_text, episodes)
    
    print(f"\nApproved: {len(approved_episodes)} episode(s)")
    for ep in approved_episodes:
        print(f"  - {ep.get('podcast', 'Unknown')}: {ep.get('title', 'No title')[:50]}")
    
    if not approved_episodes:
        print("\n✓ Skipping all episodes as requested.")
        PENDING_FILE.unlink(missing_ok=True)
        return
    
    # Process each approved episode
    print(f"\n{'='*60}")
    print(f"DOWNLOADING & TRANSCRIBING")
    print(f"{'='*60}")
    
    success_count = 0
    for i, episode in enumerate(approved_episodes, 1):
        print(f"\n[{i}/{len(approved_episodes)}] {episode.get('title', 'Unknown')[:50]}")
        
        transcript_path = download_and_transcribe(episode, curated)
        
        if transcript_path:
            success_count += 1
            analyze_transcript(transcript_path)
    
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Successfully processed: {success_count}/{len(approved_episodes)}")
    
    # Clear pending file
    PENDING_FILE.unlink(missing_ok=True)
    
    if success_count > 0:
        # Run full pipeline to update website
        run_full_pipeline_export()
    else:
        print("\nNo episodes successfully processed.")

if __name__ == "__main__":
    main()
