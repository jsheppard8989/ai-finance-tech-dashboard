#!/usr/bin/env python3
"""
Transcribe audio using LOCAL OpenAI Whisper (PyTorch). No API, stable on macOS.

Use this if faster-whisper crashes (SIGABRT) on your machine.
Install: pip install openai-whisper
"""
import subprocess
import sys
from pathlib import Path

# Config
AUDIO_DIR = Path.home() / ".openclaw/workspace/pipeline/audio"
WORKSPACE_AUDIO_DIR = Path.home() / ".openclaw/workspace/audio"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)

AUDIO_EXTENSIONS = (".mp3", ".m4a", ".wav")


def _latest_audio_file():
    """Return the most recently modified audio file in pipeline or workspace audio dirs."""
    candidates = []
    for d in (AUDIO_DIR, WORKSPACE_AUDIO_DIR):
        if not d.is_dir():
            continue
        for ext in AUDIO_EXTENSIONS:
            for f in d.glob("*" + ext):
                if f.is_file():
                    candidates.append(f)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _find_whisper():
    """Use current Python with -m whisper (no hardcoded path)."""
    try:
        r = subprocess.run(
            [sys.executable, "-m", "whisper", "--help"],
            capture_output=True,
            timeout=10,
        )
        if r.returncode == 0:
            return [sys.executable, "-m", "whisper"]
    except Exception:
        pass
    return None


def transcribe_with_whisper(audio_path, output_path, model="base"):
    """Transcribe audio using local openai-whisper (PyTorch)."""
    whisper_cmd = _find_whisper()
    if not whisper_cmd:
        print("  ✗ openai-whisper not found. Install with: pip install openai-whisper", file=sys.stderr)
        return False

    print(f"  🎙️  Transcribing with openai-whisper (model={model})...")
    audio_path = Path(audio_path)
    output_path = Path(output_path)
    out_dir = output_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)

    cmd = whisper_cmd + [
        str(audio_path),
        "--model", model,
        "--language", "en",
        "--output_format", "txt",
        "--output_dir", str(out_dir),
        "--verbose", "False",
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=14400)  # 4 hours for long episodes
        if result.returncode != 0:
            print(f"  ✗ Whisper error: {(result.stderr or result.stdout or '')[:300]}", file=sys.stderr)
            return False
        whisper_txt = out_dir / f"{audio_path.stem}.txt"
        if whisper_txt.exists():
            if whisper_txt.resolve() != output_path.resolve():
                whisper_txt.rename(output_path)
            print(f"  ✓ Saved: {output_path.name}")
            return True
        print("  ✗ Output file not found", file=sys.stderr)
        return False
    except subprocess.TimeoutExpired:
        print("  ✗ Transcription timed out (4 h). For very long episodes, run whisper manually.", file=sys.stderr)
        return False
    except Exception as e:
        print(f"  ✗ Error: {e}", file=sys.stderr)
        return False


def transcribe_file(audio_path, output_name=None, output_path=None, model="base"):
    """Transcribe one file. Returns True on success."""
    audio_path = Path(audio_path)
    if not audio_path.exists():
        print(f"  ✗ File not found: {audio_path}", file=sys.stderr)
        return False

    if output_path is None:
        output_path = TRANSCRIPT_DIR / (f"{output_name}.txt" if output_name else f"{audio_path.stem}.txt")
    output_path = Path(output_path)

    if output_path.exists():
        print(f"  ⏭ Already transcribed: {output_path.name}")
        return True

    print(f"\n📁 {audio_path.name} ({audio_path.stat().st_size / 1024 / 1024:.1f} MB)")
    return transcribe_with_whisper(audio_path, output_path, model=model)

def main():
    print("=" * 60)
    print("LOCAL WHISPER (openai-whisper) — stable on macOS")
    print("=" * 60)

    if _find_whisper() is None:
        print("\n✗ openai-whisper not found. Run: pip install openai-whisper")
        sys.exit(1)

    print(f"\n✓ Audio:      {AUDIO_DIR}")
    print(f"✓ Transcripts: {TRANSCRIPT_DIR}\n")

    if len(sys.argv) > 1:
        if sys.argv[1] == "--latest":
            latest = _latest_audio_file()
            if latest is None:
                print("No audio files found in pipeline/audio or workspace/audio.")
                sys.exit(1)
            print("Latest audio: " + str(latest) + "\n")
            ok = transcribe_file(latest)
            sys.exit(0 if ok else 1)
        audio_file = Path(sys.argv[1])
        output_name = sys.argv[2] if len(sys.argv) > 2 else None
        if not audio_file.is_absolute():
            audio_file = AUDIO_DIR / audio_file
        ok = transcribe_file(audio_file, output_name=output_name)
        sys.exit(0 if ok else 1)

    audio_files = []
    for d in (AUDIO_DIR, WORKSPACE_AUDIO_DIR):
        if d.is_dir():
            for ext in AUDIO_EXTENSIONS:
                audio_files.extend(d.glob("*" + ext))
    audio_files = [f for f in audio_files if f.is_file()]
    if not audio_files:
        print("No audio files found in pipeline/audio or workspace/audio.")
        sys.exit(0)
    audio_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    print(f"Found {len(audio_files)} file(s)\n")
    ok = sum(1 for af in sorted(audio_files) if transcribe_file(af))
    print("\n" + "=" * 60)
    print(f"Done: {ok}/{len(audio_files)} transcribed")
    sys.exit(0 if ok == len(audio_files) else 1)
