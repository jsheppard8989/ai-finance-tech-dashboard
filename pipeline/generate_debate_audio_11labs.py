#!/usr/bin/env python3
"""
Generate a multi-voice debate audio track using ElevenLabs.

Debate generation note (substance over semantics):
- Focus on the crux of the issue (e.g. whether AI/automation is materially driving
  layoffs at scale), not on parsing the contract’s legal wording.
- Debaters should not re-read the full prompt; the host states it once.

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
        "Welcome to The Long and Short of It.\n"
        "Here is this week’s contract—the full question, stated once:\n"
        f"{prompt}\n\n"
        f"{nameA} argues yes.\n"
        f"{nameB} argues no.\n"
        "You’ve both heard the contract—do not read it back. "
        "Argue the substance: is real, material job displacement from AI and automation already here at scale, "
        "or is that mostly narrative? Skip lawyer-style technicalities about wording."
    )

    a = (
        f"{nameA}. You argue yes.\n"
        f"{seed_partA}"
        "On the merits—the wave is real. Copilots, workflow automation, and customer-facing bots are past the pilot stage; "
        "they show up in operating plans. When the same work needs fewer people, headcount pressure follows.\n\n"
        "Second, this pattern compounds across big employers. Finance, operations, support—similar playbooks roll out firm by firm.\n\n"
        "Third, leadership is already framing efficiency programs around tools that replace tasks, not just trim perks.\n\n"
        "Concession. Not every displacement happens as a neat headline; some shows up as slower hiring or role churn. "
        "Still, the directional force is toward fewer bodies for the same output where AI lands hardest."
    )

    b = (
        f"{nameB}. You argue no.\n"
        f"{seed_partB}"
        "On the merits—the AI-layoff story is still overstated. A lot of announced cuts are ordinary restructuring, "
        "mergers, or margin pressure that would exist without a single new model.\n\n"
        "Second, in most shops the tools augment before they eliminate; the loudest anecdotes are not the whole labor market.\n\n"
        "Third, calling something AI in a memo is cheap; it does not prove that automation caused the cut.\n\n"
        "Concession. Capabilities are improving fast—the long run may look different. "
        "The honest debate is whether broad, material displacement is already the baseline, not whether it might arrive someday."
    )

    close = "This has been The Long and Short of It. Choose evidence over tribe."

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

