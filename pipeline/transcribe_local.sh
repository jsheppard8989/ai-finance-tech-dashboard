#!/bin/bash
# Transcribe remaining audio files using local Whisper

AUDIO_DIR="/Users/jaredsheppard/.openclaw/workspace/audio"
TRANSCRIPT_DIR="/Users/jaredsheppard/.openclaw/workspace/pipeline/transcripts"
WHISPER="/Library/Frameworks/Python.framework/Versions/3.9/bin/whisper"

mkdir -p "$TRANSCRIPT_DIR"

# Function to transcribe a file
transcribe_file() {
    local filename="$1"
    local base_name=$(basename "$filename" .mp3)
    local output_file="$TRANSCRIPT_DIR/${base_name}.txt"
    
    # Skip if already transcribed (and not empty/error)
    if [ -f "$output_file" ] && [ -s "$output_file" ]; then
        local first_word=$(head -c 20 "$output_file")
        if [[ "$first_word" != *"null"* ]]; then
            echo "✓ Already transcribed: $filename"
            return 0
        fi
    fi
    
    echo ""
    echo "🎙️  Transcribing: $filename"
    
    # Clean up any existing bad transcript
    rm -f "$output_file"
    
    # Run whisper
    local output_base="$TRANSCRIPT_DIR/$base_name"
    "$WHISPER" "$AUDIO_DIR/$filename" \
        --model base \
        --language en \
        --output_format txt \
        --output_dir "$TRANSCRIPT_DIR" 2>&1 | tail -10
    
    # Check if output was created
    if [ -f "${output_base}.txt" ]; then
        echo "  ✓ Saved to ${base_name}.txt"
        return 0
    else
        echo "  ✗ Failed to transcribe"
        return 1
    fi
}

# Remaining files to transcribe
echo "============================================================"
echo "Transcribing Remaining Files (Local Whisper)"
echo "============================================================"

transcribe_file "IMP3972824673.mp3"
transcribe_file "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-0-13%2F4f1c691a-555d-6be3-1ab4-1aebf83a0b84.mp3"
transcribe_file "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-3%2F417366235-44100-2-96fb158c7055a.mp3"

echo ""
echo "============================================================"
echo "Transcription complete!"
echo "Transcripts saved to: $TRANSCRIPT_DIR"
echo "============================================================"
