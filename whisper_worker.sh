#!/bin/bash
# whisper_worker.sh — runs outside OpenClaw sandbox as a LaunchAgent
# Watches ~/.openclaw/workspace/whisper_queue/ for .mp3 files
# Transcribes each one, writes .txt to whisper_done/, writes .done marker

QUEUE_DIR="$HOME/.openclaw/workspace/whisper_queue"
DONE_DIR="$HOME/.openclaw/workspace/whisper_done"
WHISPER="$HOME/anaconda3/bin/whisper"
LOG="$HOME/.openclaw/workspace/whisper_worker.log"

mkdir -p "$QUEUE_DIR" "$DONE_DIR"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG"
}

log "=== Whisper worker started ==="

while true; do
    # Look for any .mp3 files in queue (skip ones with a .processing marker)
    for mp3 in "$QUEUE_DIR"/*.mp3; do
        [ -f "$mp3" ] || continue
        base="${mp3%.mp3}"
        name="$(basename "$base")"

        # Skip if already being processed
        [ -f "${base}.processing" ] && continue

        # Skip if already done
        [ -f "$DONE_DIR/${name}.txt" ] && { rm -f "$mp3"; continue; }

        touch "${base}.processing"
        log "Transcribing: $name"

        # Run whisper — CPU only, no Metal GPU, avoids OOM
        "$WHISPER" "$mp3" \
            --model tiny \
            --language en \
            --output_format txt \
            --output_dir "$DONE_DIR" \
            --fp16 False \
            >> "$LOG" 2>&1

        EXIT=$?
        rm -f "${base}.processing"

        if [ $EXIT -eq 0 ] && [ -f "$DONE_DIR/${name}.txt" ]; then
            log "✓ Done: $DONE_DIR/${name}.txt"
            # Copy any sidecar .meta.json alongside
            [ -f "${base}.meta.json" ] && cp "${base}.meta.json" "$DONE_DIR/${name}.meta.json"
            rm -f "$mp3" "${base}.meta.json"
        else
            log "✗ Failed (exit $EXIT): $name"
            rm -f "${base}.processing"
        fi
    done

    sleep 10
done
