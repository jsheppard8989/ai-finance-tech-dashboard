#!/usr/bin/env python3
"""
Transcribe audio using faster-whisper (local, fast, no API).

faster-whisper is a CTranslate2 port of Whisper: ~4x faster than openai-whisper,
lower memory, and runs entirely locally. Use this for reliable podcast transcription
without API costs or rate limits.

Install: pip install faster-whisper
If you see SIGABRT/crash on macOS, run with --model tiny and/or:
  OMP_NUM_THREADS=4 python3 transcribe_faster_whisper.py ...
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Reduce risk of CTranslate2/OpenMP SIGABRT on macOS by limiting threads
if "OMP_NUM_THREADS" not in os.environ:
    os.environ["OMP_NUM_THREADS"] = "4"

# Paths
AUDIO_DIR = Path.home() / ".openclaw/workspace/pipeline/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)

# Default model: base is fast and good for English; use medium/large-v3 for best quality
DEFAULT_MODEL = "tiny"
SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v2", "large-v3")


def transcribe_file(
    audio_path: Path,
    output_path: Path | None = None,
    *,
    model_size: str = DEFAULT_MODEL,
    device: str = "auto",
    compute_type: str = "default",
    language: str | None = "en",
    beam_size: int = 1,
) -> bool:
    """
    Transcribe a single audio file with faster-whisper.
    Returns True on success, False on failure.
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print("faster-whisper not installed. Run: pip install faster-whisper", file=sys.stderr)
        return False

    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"  ✗ File not found: {audio_path}", file=sys.stderr)
        return False

    out_txt = output_path or (TRANSCRIPT_DIR / f"{audio_path.stem}.txt")
    out_txt = Path(out_txt)
    if out_txt.exists():
        print(f"  ⏭ Already transcribed: {out_txt.name}")
        return True

    # On macOS force CPU + int8 to reduce native (CTranslate2) crash risk; no torch
    if sys.platform == "darwin":
        device = "cpu"
        compute_type = "int8"
    elif device == "cpu" and compute_type == "default":
        compute_type = "int8"
    elif device == "auto":
        try:
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cpu":
                compute_type = "int8"
        except Exception:
            device = "cpu"
            compute_type = "int8"

    print(f"  🎙️  Transcribing with faster-whisper (model={model_size}, device={device})...")
    try:
        model = WhisperModel(model_size, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            str(audio_path),
            language=language,
            beam_size=beam_size,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=400),
        )
        lines = []
        for seg in segments:
            text = (seg.text or "").strip()
            if text:
                lines.append(text)
        transcript = "\n".join(lines)
        out_txt.write_text(transcript, encoding="utf-8")
        print(f"  ✓ Saved: {out_txt.name} ({len(transcript):,} chars)")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}", file=sys.stderr)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transcribe podcasts with faster-whisper (local, fast, no API)."
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Audio file path(s); if omitted, transcribe all in pipeline audio dir",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=SUPPORTED_MODELS,
        help=f"Model size (default: {DEFAULT_MODEL}). Larger = better quality, slower.",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=("auto", "cpu", "cuda"),
        help="Device to run on (default: auto).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRANSCRIPT_DIR,
        help="Directory for .txt transcripts",
    )
    parser.add_argument(
        "--audio-dir",
        type=Path,
        default=AUDIO_DIR,
        help="Audio directory when no files given",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=None,
        help="Limit OpenMP threads (e.g. 2 or 4). Can prevent SIGABRT on macOS.",
    )
    args = parser.parse_args()

    if args.threads is not None:
        os.environ["OMP_NUM_THREADS"] = str(args.threads)

    if args.files:
        paths = [Path(p) for p in args.files]
        for p in paths:
            if not p.is_absolute():
                p = args.audio_dir / p
            success = transcribe_file(
                p,
                output_path=args.output_dir / f"{p.stem}.txt",
                model_size=args.model,
                device=args.device,
            )
            if not success:
                return 1
        return 0

    # Batch: all audio in pipeline audio dir
    print("=" * 60)
    print("FASTER-WHISPER LOCAL TRANSCRIPTION")
    print("=" * 60)
    print(f"  Audio dir:      {args.audio_dir}")
    print(f"  Transcript dir: {args.output_dir}")
    print(f"  Model:          {args.model}\n")

    audio_files = (
        list(args.audio_dir.glob("*.mp3"))
        + list(args.audio_dir.glob("*.m4a"))
        + list(args.audio_dir.glob("*.wav"))
        + list(args.audio_dir.glob("*.mp4"))
    )
    if not audio_files:
        print("  No audio files found.")
        return 0

    ok = 0
    for af in sorted(audio_files):
        out = args.output_dir / f"{af.stem}.txt"
        if transcribe_file(af, output_path=out, model_size=args.model, device=args.device):
            ok += 1

    print("\n" + "=" * 60)
    print(f"  Done: {ok}/{len(audio_files)} transcribed (local, no API cost)")
    return 0 if ok == len(audio_files) else 1


if __name__ == "__main__":
    sys.exit(main())
