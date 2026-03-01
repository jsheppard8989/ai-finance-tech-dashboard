#!/usr/bin/env python3
"""
Sweep completed transcripts from whisper_done into the pipeline, then run
analyze → promote → export so the site gets new episodes (e.g. All-In Feb 28).

Usage:
  cd ~/.openclaw/workspace/pipeline
  python3 sweep_whisper_done_and_publish.py

Does not fetch or transcribe; use fetch_latest.py for that.
"""

import shutil
import subprocess
import sys
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw/workspace"
WHISPER_DONE = WORKSPACE / "whisper_done"
TRANSCRIPT_DIR = WORKSPACE / "pipeline" / "transcripts"
PIPELINE_DIR = WORKSPACE / "pipeline"


def sweep_whisper_done():
    """Copy .txt and .meta.json from whisper_done to pipeline/transcripts (keep originals)."""
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    moved = 0
    for txt in WHISPER_DONE.glob("*.txt"):
        dest = TRANSCRIPT_DIR / txt.name
        if not dest.exists() or dest.stat().st_size != txt.stat().st_size:
            shutil.copy2(txt, dest)
            print(f"  ✓ Copied {txt.name} → pipeline/transcripts/")
            moved += 1
    for meta in WHISPER_DONE.glob("*.meta.json"):
        dest = TRANSCRIPT_DIR / meta.name
        if not dest.exists():
            shutil.copy2(meta, dest)
            print(f"  ✓ Copied {meta.name} → pipeline/transcripts/")
            moved += 1
    return moved


def main():
    print("=" * 60)
    print("Sweep whisper_done → pipeline/transcripts, then analyze & export")
    print("=" * 60)

    if not WHISPER_DONE.exists():
        print("No whisper_done dir; nothing to sweep.")
        sys.exit(0)

    n = sweep_whisper_done()
    if n == 0:
        print("No new files to sweep (already in pipeline/transcripts).")

    print("\nRunning analyze + export (auto_pipeline --analyze-only)...")
    r = subprocess.run(
        [sys.executable, "auto_pipeline.py", "--analyze-only"],
        cwd=str(PIPELINE_DIR),
    )
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
