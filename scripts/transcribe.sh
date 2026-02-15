#!/usr/bin/env bash
# Transcribe audio using the local Whisper CLI (openai-whisper pip package)
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <audio-file> [--model MODEL] [--language LANG] [other whisper args]"
  exit 1
fi

# Default model and language; user-supplied flags passed through
file="$1"
shift

# Invoke the whisper CLI; it will write <file>.txt by default
whisper "$file" --model whisper-1 --language en "$@"

echo "Transcription complete: ${file%.*}.txt"