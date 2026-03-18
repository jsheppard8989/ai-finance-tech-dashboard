#!/usr/bin/env python3
"""
ElevenLabs TTS for The Long and Short of It.

Primary path: run `python3 pipeline/debate_weekly.py` (generates scripts + contract + MP3).

This script alone only re-encodes audio from the last weekly run:
  python3 pipeline/debate_weekly.py --audio-only

Or (legacy dev):
  python3 generate_debate_audio_11labs.py
  → uses pipeline/state/last_debate_scripts.json from the last debate_weekly run.

Env: ELEVENLABS_API_KEY, ELEVENLABS_HOST_VOICE_ID, ELEVENLABS_A_VOICE_ID, ELEVENLABS_B_VOICE_ID
"""

import json
import os
import sys
from pathlib import Path

WORKSPACE = Path.home() / ".openclaw/workspace"
PIPELINE = WORKSPACE / "pipeline"
SITE_AUDIO = WORKSPACE / "site" / "audio"
SCRIPTS_STATE = PIPELINE / "state" / "last_debate_scripts.json"
OUT_PATH = SITE_AUDIO / "emp_ai_the_debate_11labs.mp3"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


def tts(voice_id: str, text: str) -> bytes:
    import requests

    api_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }
    r = requests.post(url, headers=headers, json=payload, timeout=120)
    r.raise_for_status()
    return r.content


def main() -> int:
    load_env_file(WORKSPACE / ".env")
    load_env_file(PIPELINE / ".env")

    if not SCRIPTS_STATE.exists():
        print(
            "No saved debate scripts. Run:\n"
            "  python3 pipeline/debate_weekly.py\n"
            "Or after a weekly run:\n"
            "  python3 pipeline/debate_weekly.py --audio-only"
        )
        return 1

    bundle = json.loads(SCRIPTS_STATE.read_text(encoding="utf-8"))
    host_v = os.getenv("ELEVENLABS_HOST_VOICE_ID", "").strip()
    a_v = os.getenv("ELEVENLABS_A_VOICE_ID", "").strip()
    b_v = os.getenv("ELEVENLABS_B_VOICE_ID", "").strip()
    if not host_v or not a_v or not b_v:
        raise RuntimeError("Missing one or more ELEVENLABS_*_VOICE_ID env vars")

    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    audio = (
        tts(host_v, bundle["host"])
        + tts(a_v, bundle["yes"])
        + tts(b_v, bundle["no"])
        + tts(host_v, bundle["close"])
    )
    OUT_PATH.write_bytes(audio)
    print(f"✓ Wrote {OUT_PATH} ({len(audio)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
