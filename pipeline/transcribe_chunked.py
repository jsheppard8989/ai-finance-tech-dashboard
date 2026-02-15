#!/usr/bin/env python3
"""
Transcribe large audio files by splitting them into chunks.
"""
import os
import subprocess
import json
from pathlib import Path

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
SPLIT_DIR = AUDIO_DIR / "split"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
TRANSCRIPT_DIR.mkdir(exist_ok=True)
SPLIT_DIR.mkdir(exist_ok=True)

API_KEY = os.environ.get('OPENAI_API_KEY')

# Files to transcribe (approved from curation_log.json)
FILES_TO_TRANSCRIBE = [
    "EWWMN2965097612.mp3",
    "EWWMN6429295583.mp3", 
    "IMP3972824673.mp3",
    "default.mp3",
    "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-0-13%2F4f1c691a-555d-6be3-1ab4-1aebf83a0b84.mp3",
    "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-3%2F417366235-44100-2-96fb158c7055a.mp3"
]

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

def split_audio(file_path, chunk_duration_sec=600):  # 10 minute chunks
    """Split audio file into chunks."""
    base_name = file_path.stem
    print(f"  Splitting {file_path.name} into {chunk_duration_sec}s chunks...")
    
    cmd = [
        'ffmpeg', '-y', '-i', str(file_path),
        '-f', 'segment', '-segment_time', str(chunk_duration_sec),
        '-c', 'copy',
        str(SPLIT_DIR / f"{base_name}_%03d.mp3")
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  Error splitting: {result.stderr}")
        return []
    
    # Get list of created chunks
    chunks = sorted(SPLIT_DIR.glob(f"{base_name}_*.mp3"))
    print(f"  Created {len(chunks)} chunks")
    return chunks

def transcribe_chunk(chunk_path):
    """Transcribe a single chunk using Whisper API."""
    print(f"    Transcribing chunk: {chunk_path.name}")
    
    cmd = [
        'curl', '-s', 'https://api.openai.com/v1/audio/transcriptions',
        '-H', f'Authorization: Bearer {API_KEY}',
        '-H', 'Content-Type: multipart/form-data',
        '-F', f'file=@{chunk_path}',
        '-F', 'model=whisper-1',
        '-F', 'language=en'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode == 0:
        try:
            response = json.loads(result.stdout)
            return response.get('text', '')
        except:
            print(f"    Error parsing response: {result.stdout[:200]}")
            return ""
    else:
        print(f"    Error: {result.stderr[:200]}")
        return ""

def transcribe_file(filename):
    """Transcribe a single audio file."""
    file_path = AUDIO_DIR / filename
    output_file = TRANSCRIPT_DIR / f"{file_path.stem}.txt"
    
    # Skip if already transcribed
    if output_file.exists():
        print(f"✓ Already transcribed: {filename}")
        return True
    
    print(f"\n🎙️  Transcribing: {filename}")
    
    # Check file size
    file_size = file_path.stat().st_size
    if file_size < 25 * 1024 * 1024:  # Under 25MB
        print(f"  File is small enough, transcribing directly...")
        transcript = transcribe_chunk(file_path)
        if transcript:
            with open(output_file, 'w') as f:
                f.write(transcript)
            print(f"  ✓ Saved to {output_file.name}")
            return True
    else:
        # Split and transcribe chunks
        chunks = split_audio(file_path)
        if not chunks:
            print(f"  ✗ Failed to split audio")
            return False
        
        full_transcript = []
        for chunk in chunks:
            text = transcribe_chunk(chunk)
            if text:
                full_transcript.append(text)
            # Clean up chunk after transcription
            chunk.unlink()
        
        if full_transcript:
            transcript_text = "\n\n".join(full_transcript)
            with open(output_file, 'w') as f:
                f.write(transcript_text)
            print(f"  ✓ Saved to {output_file.name} ({len(full_transcript)} chunks)")
            return True
    
    return False

def main():
    print("=" * 60)
    print("Podcast Transcription Pipeline (Chunked)")
    print("=" * 60)
    
    if not API_KEY:
        print("ERROR: OPENAI_API_KEY not set")
        return
    
    results = []
    for filename in FILES_TO_TRANSCRIBE:
        success = transcribe_file(filename)
        results.append((filename, success))
    
    # Summary
    success_count = sum(1 for _, s in results if s)
    print("\n" + "=" * 60)
    print(f"Results: {success_count}/{len(results)} files transcribed")
    print(f"Transcripts saved to: {TRANSCRIPT_DIR}")

if __name__ == "__main__":
    main()
