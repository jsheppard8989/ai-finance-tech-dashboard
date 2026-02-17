#!/usr/bin/env python3
"""
Evening pipeline - ONLY curates podcasts, doesn't download/transcribe.
Transcription happens AFTER 6am approval.
"""

import subprocess
import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

def run_step(name: str, script: str) -> bool:
    """Run a pipeline step."""
    print(f"\n{'='*60}")
    print(f"STEP: {name}")
    print(f"{'='*60}")
    
    try:
        result = subprocess.run(
            [sys.executable, script],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent
        )
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        return result.returncode == 0
    except Exception as e:
        print(f"✗ Error: {e}")
        return False

def main():
    """Evening pipeline - curate only."""
    print("="*60)
    print("EVENING PIPELINE - CURATION ONLY")
    print(f"Started: {datetime.now()}")
    print("="*60)
    print("\nThis pipeline ONLY discovers new podcast episodes.")
    print("Downloads and transcription happen AFTER 6am approval.\n")
    
    # Step 1: Curate podcasts (discover new episodes)
    print("Step 1: Discovering new podcast episodes...")
    success = run_step("Podcast Curation", "curate.py")
    
    if success:
        print("\n✓ Curation complete!")
        print("  New episodes discovered and logged.")
        print("  They will appear in tomorrow's 6am iMessage for approval.")
        print("  Transcription will ONLY happen after you approve specific episodes.")
    else:
        print("\n⚠ Curation had issues, check logs above.")
    
    print(f"\nFinished: {datetime.now()}")

if __name__ == "__main__":
    main()
