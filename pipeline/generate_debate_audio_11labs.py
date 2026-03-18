#!/usr/bin/env python3
"""
Generate a multi-voice debate audio track using ElevenLabs.

We deliberately avoid impersonating real people. Provide 3 distinct synthetic voices:
- Host
- Debater A
- Debater B

Env vars:
- ELEVENLABS_API_KEY (required)
- ELEVENLABS_HOST_VOICE_ID (required)
- ELEVENLABS_A_VOICE_ID (required)
- ELEVENLABS_B_VOICE_ID (required)

Output:
- site/audio/emp_ai_the_debate_11labs.mp3
"""

import os
import sys
from pathlib import Path
from datetime import datetime

import requests


WORKSPACE = Path.home() / ".openclaw/workspace"
SITE_AUDIO = WORKSPACE / "site" / "audio"
OUT_PATH = SITE_AUDIO / "emp_ai_the_debate_11labs.mp3"


def load_env_file(path: Path) -> None:
    """
    Minimal .env loader:
    - Lines like KEY=VALUE
    - Ignores comments/blank lines
    - Keeps everything after the first '=' as the value (so spaces are allowed)
    - Does not overwrite existing environment variables
    """
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
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.content


def build_script() -> dict:
    # For now, a stable default. Later we’ll generate this from exported debate topic + contracts.
    prompt = "Is AI-driven abundance real, or is it the same old cycle wearing a new mask?"
    return {
        "prompt": prompt,
        "host": (
            "Host.\n"
            "Rules: one prompt, two steel-manned sides, one concession each, one forty-two day wager each.\n"
            f"Prompt: {prompt}"
        ),
        "a": (
            "Debater A.\n"
            "Steel-man: the abundance case.\n"
            "The best version says intelligence is becoming cheap, and when intelligence is cheap, bottlenecks move. "
            "Coordination, design, diagnosis, and research become radically more productive. "
            "Abundance is not the absence of scarcity; it is an expanding frontier.\n\n"
            "Concession: Even if abundance is real, power can concentrate during the transition.\n\n"
            "42-day wager: By expiry, we will see a mainstream AI system replace a full workflow, not just assist a task."
        ),
        "b": (
            "Debater B.\n"
            "Steel-man: the cycle case.\n"
            "The best version says every era sells a new story, but the old mechanics remain. "
            "Capital clusters. Insiders win. Productivity gains are uneven. "
            "AI may increase output, but it can also increase surveillance, fragility, and monopoly rents.\n\n"
            "Concession: Even if this is a cycle, capabilities are improving, and some productivity gains are unavoidable.\n\n"
            "42-day wager: By expiry, we will see a public tightening signal—regulation, litigation, or a high-profile failure—that slows adoption."
        ),
        "close": "Your job is not to choose a tribe. Your job is to choose evidence.",
    }


def main() -> int:
    # Load workspace-level .env (supports spaces; avoids shell `source` pitfalls)
    load_env_file(WORKSPACE / ".env")
    # Also load pipeline/.env if present (optional)
    load_env_file(WORKSPACE / "pipeline" / ".env")

    host_voice = os.getenv("ELEVENLABS_HOST_VOICE_ID", "").strip()
    a_voice = os.getenv("ELEVENLABS_A_VOICE_ID", "").strip()
    b_voice = os.getenv("ELEVENLABS_B_VOICE_ID", "").strip()
    if not host_voice or not a_voice or not b_voice:
        raise RuntimeError("Missing one or more ELEVENLABS_*_VOICE_ID env vars")

    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    script = build_script()

    # Generate each segment
    host_audio = tts(host_voice, script["host"])
    a_audio = tts(a_voice, script["a"])
    b_audio = tts(b_voice, script["b"])
    close_audio = tts(host_voice, script["close"])

    # Naive concatenation of MP3 frames typically plays fine in browsers.
    # If we need sample-accurate joins later, we can add ffmpeg.
    OUT_PATH.write_bytes(host_audio + a_audio + b_audio + close_audio)
    print(f"✓ Wrote {OUT_PATH} ({OUT_PATH.stat().st_size} bytes) at {datetime.now().isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

