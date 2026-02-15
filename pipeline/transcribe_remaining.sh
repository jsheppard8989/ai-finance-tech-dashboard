#!/bin/bash
# Transcribe remaining audio files

set -e

AUDIO_DIR="/Users/jaredsheppard/.openclaw/workspace/audio"
SPLIT_DIR="$AUDIO_DIR/split"
TRANSCRIPT_DIR="/Users/jaredsheppard/.openclaw/workspace/pipeline/transcripts"

mkdir -p "$SPLIT_DIR" "$TRANSCRIPT_DIR"

# Function to transcribe a single chunk
transcribe_chunk() {
    local chunk_file="$1"
    local result=$(curl -s https://api.openai.com/v1/audio/transcriptions \
        -H "Authorization: Bearer $OPENAI_API_KEY" \
        -H "Content-Type: multipart/form-data" \
        -F file="@$chunk_file" \
        -F model="whisper-1" \
        -F language="en")
    
    # Extract text using grep/sed to avoid jq dependency issues
    local text=$(echo "$result" | grep -o '"text": "[^"]*"' | sed 's/"text": "//;s/"$//')
    
    if [ -z "$text" ] || [ "$text" = "null" ]; then
        echo "ERROR: Failed to transcribe chunk" >&2
        return 1
    fi
    echo "$text"
}

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
    
    # Split file into 10-minute chunks
    rm -f "$SPLIT_DIR/${base_name}"_*.mp3
    ffmpeg -y -i "$AUDIO_DIR/$filename" -f segment -segment_time 600 -c copy "$SPLIT_DIR/${base_name}_%03d.mp3" 2>/dev/null
    
    # Transcribe each chunk
    local transcript=""
    local chunk_count=0
    for chunk in "$SPLIT_DIR/${base_name}"_*.mp3; do
        if [ -f "$chunk" ]; then
            chunk_count=$((chunk_count + 1))
            echo "  Processing chunk $chunk_count: $(basename "$chunk")"
            local chunk_text=$(transcribe_chunk "$chunk" || echo "")
            if [ -n "$chunk_text" ] && [ "$chunk_text" != "null" ]; then
                transcript="${transcript}${chunk_text} "
            fi
            rm -f "$chunk"
        fi
    done
    
    # Save transcript
    if [ -n "$transcript" ]; then
        echo "$transcript" > "$output_file"
        echo "  ✓ Saved to ${base_name}.txt"
        return 0
    else
        echo "  ✗ Failed to transcribe"
        return 1
    fi
}

# Remaining files to transcribe
echo "============================================================"
echo "Transcribing Remaining Files"
echo "============================================================"

transcribe_file "IMP3972824673.mp3"
transcribe_file "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-0-13%2F4f1c691a-555d-6be3-1ab4-1aebf83a0b84.mp3"
transcribe_file "https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-3%2F417366235-44100-2-96fb158c7055a.mp3"

echo ""
echo "============================================================"
echo "Transcription complete!"
echo "Transcripts saved to: $TRANSCRIPT_DIR"
echo "============================================================"
