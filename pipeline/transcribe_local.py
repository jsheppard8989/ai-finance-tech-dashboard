#!/usr/bin/env python3
"""
Transcribe audio files using LOCAL OpenAI Whisper (no API costs).
"""
import os
import subprocess
import sys
from pathlib import Path

# Whisper path (installed via pip)
WHISPER_BIN = "/Library/Frameworks/Python.framework/Versions/3.9/bin/whisper"

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/pipeline/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
TRANSCRIPT_DIR.mkdir(exist_ok=True)
AUDIO_DIR.mkdir(exist_ok=True)

def transcribe_with_whisper(audio_path, output_path):
    """Transcribe audio using local Whisper."""
    print(f"  🎙️  Transcribing with local Whisper...")
    
    cmd = [
        WHISPER_BIN,
        str(audio_path),
        "--model", "base",  # Options: tiny, base, small, medium, large
        "--language", "en",
        "--output_format", "txt",
        "--output_dir", str(TRANSCRIPT_DIR),
        "--verbose", "False"
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout for long episodes
        )
        
        if result.returncode == 0:
            # Whisper saves as <audio_name>.txt in output_dir
            whisper_output = TRANSCRIPT_DIR / f"{audio_path.stem}.txt"
            
            if whisper_output.exists():
                # If we want a different output name, rename it
                if output_path != whisper_output:
                    whisper_output.rename(output_path)
                print(f"  ✓ Transcribed: {output_path.name}")
                return True
            else:
                print(f"  ✗ Output file not found: {whisper_output}")
                return False
        else:
            print(f"  ✗ Whisper error: {result.stderr[:200]}")
            return False
            
    except subprocess.TimeoutExpired:
        print(f"  ✗ Transcription timed out (>30 min)")
        return False
    except Exception as e:
        print(f"  ✗ Error: {str(e)[:100]}")
        return False

def transcribe_file(audio_path, output_name=None):
    """Transcribe a single audio file."""
    audio_path = Path(audio_path)
    
    if not audio_path.exists():
        print(f"✗ File not found: {audio_path}")
        return False
    
    # Determine output filename
    if output_name:
        output_file = TRANSCRIPT_DIR / f"{output_name}.txt"
    else:
        output_file = TRANSCRIPT_DIR / f"{audio_path.stem}.txt"
    
    # Skip if already transcribed
    if output_file.exists():
        print(f"⏭ Already transcribed: {output_file.name}")
        return True
    
    print(f"\n📁 Processing: {audio_path.name}")
    print(f"   Size: {audio_path.stat().st_size / 1024 / 1024:.1f} MB")
    
    # Transcribe
    success = transcribe_with_whisper(audio_path, output_file)
    
    if success:
        # Show file size
        transcript_size = output_file.stat().st_size
        print(f"   Output: {transcript_size / 1024:.0f} KB")
    
    return success

def main():
    """Main entry point - can be called with file path as argument."""
    print("=" * 60)
    print("LOCAL WHISPER TRANSCRIPTION (FREE - No API Costs)")
    print("=" * 60)
    
    # Check if whisper is available
    if not Path(WHISPER_BIN).exists():
        print(f"\n✗ Whisper not found at: {WHISPER_BIN}")
        print("  Install with: pip3 install openai-whisper")
        return
    
    print(f"\n✓ Whisper found: {WHISPER_BIN}")
    print(f"✓ Audio directory: {AUDIO_DIR}")
    print(f"✓ Transcript directory: {TRANSCRIPT_DIR}\n")
    
    # If called with arguments, transcribe those files
    if len(sys.argv) > 1:
        audio_file = sys.argv[1]
        output_name = sys.argv[2] if len(sys.argv) > 2 else None
        
        audio_path = Path(audio_file)
        if not audio_path.is_absolute():
            audio_path = AUDIO_DIR / audio_file
        
        success = transcribe_file(audio_path, output_name)
        sys.exit(0 if success else 1)
    
    # Otherwise, transcribe all files in audio directory
    print("Scanning for audio files...")
    audio_files = list(AUDIO_DIR.glob("*.mp3")) + list(AUDIO_DIR.glob("*.m4a")) + list(AUDIO_DIR.glob("*.wav"))
    
    if not audio_files:
        print("  No audio files found.")
        return
    
    print(f"  Found {len(audio_files)} audio file(s)\n")
    
    results = []
    for audio_file in audio_files:
        success = transcribe_file(audio_file)
        results.append((audio_file.name, success))
    
    # Summary
    success_count = sum(1 for _, s in results if s)
    print("\n" + "=" * 60)
    print(f"RESULTS: {success_count}/{len(results)} files transcribed")
    print(f"Cost: $0.00 (local Whisper)")
    print(f"Transcripts: {TRANSCRIPT_DIR}")

if __name__ == "__main__":
    main()
