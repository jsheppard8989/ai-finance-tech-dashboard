#!/usr/bin/env python3
"""
Batch podcast transcription using OpenAI Whisper API.
Transcribes all audio files in the audio/ folder.
"""

import os
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
TRANSCRIPT_DIR.mkdir(exist_ok=True)

def get_audio_files():
    """Get all audio files in the audio directory."""
    extensions = ['.mp3', '.m4a', '.ogg', '.wav']
    files = []
    for ext in extensions:
        files.extend(AUDIO_DIR.glob(f"*{ext}"))
    return sorted(files)

def get_duration(file_path):
    """Get audio duration using ffprobe."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration', 
             '-of', 'default=noprint_wrappers=1:nokey=1', str(file_path)],
            capture_output=True, text=True, timeout=30
        )
        return float(result.stdout.strip())
    except:
        return None

def transcribe_file(audio_file):
    """Transcribe a single audio file using Whisper API."""
    output_file = TRANSCRIPT_DIR / f"{audio_file.stem}.txt"
    
    # Skip if already transcribed
    if output_file.exists():
        print(f"  ✓ Already transcribed: {audio_file.name}")
        return {"file": audio_file.name, "status": "skipped", "output": str(output_file)}
    
    print(f"  🎙️  Transcribing: {audio_file.name}")
    
    # Check for API key
    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        return {"file": audio_file.name, "status": "error", "error": "OPENAI_API_KEY not set"}
    
    try:
        # Build curl command
        cmd = [
            'curl', '-s', 'https://api.openai.com/v1/audio/transcriptions',
            '-H', f'Authorization: Bearer {api_key}',
            '-H', 'Content-Type: multipart/form-data',
            '-F', f'file=@{audio_file}',
            '-F', 'model=whisper-1',
            '-F', 'language=en'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            # Parse JSON response
            import json
            response = json.loads(result.stdout)
            transcript = response.get('text', '')
            
            # Save transcript
            with open(output_file, 'w') as f:
                f.write(transcript)
            
            # Also save as JSON for structured access
            json_output = TRANSCRIPT_DIR / f"{audio_file.stem}.json"
            with open(json_output, 'w') as f:
                json.dump({
                    "source_file": audio_file.name,
                    "transcribed_at": str(datetime.now()),
                    "text": transcript
                }, f, indent=2)
            
            print(f"     ✓ Saved to {output_file.name}")
            return {"file": audio_file.name, "status": "success", "output": str(output_file)}
        else:
            error = result.stderr or result.stdout
            print(f"     ✗ Error: {error[:100]}")
            return {"file": audio_file.name, "status": "error", "error": error}
            
    except Exception as e:
        print(f"     ✗ Exception: {e}")
        return {"file": audio_file.name, "status": "error", "error": str(e)}

def main():
    from datetime import datetime
    
    print("=" * 60)
    print("Podcast Transcription Pipeline")
    print("=" * 60)
    
    # Get audio files
    audio_files = get_audio_files()
    print(f"\nFound {len(audio_files)} audio files")
    
    if not audio_files:
        print("No audio files found in audio/ folder")
        return
    
    # Calculate estimated cost
    print("\nEstimating durations...")
    total_seconds = 0
    for f in audio_files:
        duration = get_duration(f)
        if duration:
            minutes = duration / 60
            total_seconds += duration
            print(f"  - {f.name}: {minutes:.1f} min")
    
    total_minutes = total_seconds / 60
    estimated_cost = total_minutes * 0.006
    
    print(f"\nEstimated cost: ${estimated_cost:.2f} ({total_minutes:.0f} minutes)")
    
    # Confirm
    confirm = input("\nProceed with transcription? (y/n): ")
    if confirm.lower() != 'y':
        print("Aborted")
        return
    
    # Transcribe
    print("\nTranscribing...")
    results = []
    
    # Sequential to avoid rate limits
    for audio_file in audio_files:
        result = transcribe_file(audio_file)
        results.append(result)
    
    # Summary
    success = sum(1 for r in results if r['status'] == 'success')
    skipped = sum(1 for r in results if r['status'] == 'skipped')
    errors = sum(1 for r in results if r['status'] == 'error')
    
    print("\n" + "=" * 60)
    print(f"Results: {success} transcribed, {skipped} skipped, {errors} errors")
    print(f"Transcripts saved to: {TRANSCRIPT_DIR}")
    print("\nNext step: Run analyze.py to extract tickers from transcripts")

if __name__ == "__main__":
    main()
