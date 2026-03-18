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
META_PATH = SITE_AUDIO / "debate_contract.json"
PUNDITS_PATH = WORKSPACE / "site" / "data" / "pundits.json"


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


def build_contract() -> dict:
    """
    Build the single contract that the debate is about.
    For now, we use a stable default. Later we’ll generate this from pipeline exports.
    """
    prompt = (
        "Will S&P 500 companies announce at least 50,000 net layoffs explicitly "
        "attributed to automation or AI in public filings, press releases, or verified "
        "corporate social posts within the next 42 days?"
    )
    return {
        "prompt": prompt,
        "generated_at": datetime.now().isoformat(),
        "expires_rule": "42-day Friday-noon CST (to be enforced by scheduler)",
        "resolution_clarity": {
            "source_of_truth": "Capitalist Compass (the line / crowd signal)",
            "resolution_sources": ["TBD"],
            "resolution_criteria": ["TBD"],
        },
        "sides": {
            "a": "Affirmative (YES)",
            "b": "Negative (NO)",
        },
    }


def build_script(contract: dict) -> dict:
    prompt = contract["prompt"]

    # Seed with exported pundit backgrounds (no impersonation; just persona context).
    pundits = []
    try:
        import json
        if PUNDITS_PATH.exists():
            pundits = json.loads(PUNDITS_PATH.read_text(encoding="utf-8"))
    except Exception:
        pundits = []
    if not isinstance(pundits, list):
        pundits = []

    pA = pundits[0] if len(pundits) > 0 else {"name": "Pundit A", "known_for": "", "bio": ""}
    pB = pundits[1] if len(pundits) > 1 else {"name": "Pundit B", "known_for": "", "bio": ""}

    nameA = (pA.get("name") or "Pundit A").strip()
    nameB = (pB.get("name") or "Pundit B").strip()

    seedA = (pA.get("known_for") or pA.get("bio") or "").strip()
    seedB = (pB.get("known_for") or pB.get("bio") or "").strip()
    seed_partA = f"Seed: {seedA}\n\n" if seedA else ""
    seed_partB = f"Seed: {seedB}\n\n" if seedB else ""

    host = (
        "Welcome to Emp(ai)thy is the Edge.\n"
        "Today we debate one contract. The bet is the question itself.\n\n"
        f"Contract:\n{prompt}\n\n"
        f"{nameA} argues the affirmative of the contract.\n"
        f"{nameB} argues the negative of the contract.\n\n"
        "Listen for evidence, and update your beliefs."
    )

    a = (
        f"{nameA} — Affirmative (YES).\n"
        f"{seed_partA}"
        "I argue YES. In the next forty-two days, enough S and P five hundred companies will "
        "publicly announce at least fifty thousand net layoffs that explicitly tie the action to "
        "automation or AI.\n\n"
        "Why.\n"
        "Automation and AI initiatives have moved from pilots into operational cost reductions. "
        "When deployments are measurable, workforce actions become more likely and easier to justify.\n"
        "Second, large firms often communicate staffing changes through filings, press releases, and "
        "verified corporate channels.\n"
        "Third, the threshold can be reached by aggregation: if multiple large events occur, the total stacks fast.\n\n"
        "Concession.\n"
        "The contract requires explicit attribution. Companies could still describe cuts as restructuring "
        "without naming AI. So YES depends on clarity—language that points directly to automation or AI."
    )

    b = (
        f"{nameB} — Negative (NO).\n"
        f"{seed_partB}"
        "I argue NO. In the next forty-two days, the S and P five hundred will not reach "
        "fifty thousand net layoffs with explicit attribution to automation or AI.\n\n"
        "Why.\n"
        "Attribution is the constraint. Workforce changes are frequently framed as efficiency or restructuring "
        "without explicitly linking them to AI.\n"
        "Second, the timeline is tight. Even when capability gains arrive, public communication and "
        "reporting cycles can lag.\n"
        "Third, the contract is strict: it demands both scale and explicit linkage, which reduces the probability.\n\n"
        "Concession.\n"
        "Even if AI contributes, the contract can still resolve NO if the language is not explicit, "
        "or if the net figure falls short within the window."
    )

    close = "Your job is not to choose a tribe. Your job is to choose evidence."

    return {"prompt": prompt, "host": host, "a": a, "b": b, "close": close}


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
    contract = build_contract()
    script = build_script(contract)

    # Write contract metadata so the website prompt matches the audio.
    import json

    META_PATH.write_text(json.dumps(contract, indent=2), encoding="utf-8")

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

