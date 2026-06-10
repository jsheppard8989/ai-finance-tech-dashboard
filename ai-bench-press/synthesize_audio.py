#!/usr/bin/env python3
"""
Synthesize the debate into real ElevenLabs audio.

One MP3 per segment (host intro + each turn), so the web player keeps per-turn
highlighting, tap-to-jump, and real <audio> lock-screen playback.

Voices (from pipeline/.env): host = ELEVENLABS_HOST_VOICE_ID,
Ada/YES = ELEVENLABS_A_VOICE_ID, Gil/NO = ELEVENLABS_B_VOICE_ID.

Output: audio/seg_*.mp3  and  audio.js (window.AUDIO playlist)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "debate.json"
AUDIO_DIR = HERE / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)


def load_env() -> None:
    for p in (HERE.parent / "pipeline" / ".env", HERE.parent / ".env"):
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


def tts(voice_id: str, text: str) -> bytes:
    key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not key:
        raise RuntimeError("Missing ELEVENLABS_API_KEY")
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = json.dumps({
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "xi-api-key": key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    })
    with urllib.request.urlopen(req, timeout=180) as resp:
        return resp.read()


def main() -> int:
    load_env()
    d = json.loads(DATA.read_text(encoding="utf-8"))
    host_v = os.environ.get("ELEVENLABS_HOST_VOICE_ID", "").strip()
    a_v = os.environ.get("ELEVENLABS_A_VOICE_ID", "").strip()
    b_v = os.environ.get("ELEVENLABS_B_VOICE_ID", "").strip()
    if not (host_v and a_v and b_v):
        raise RuntimeError("Missing one or more ELEVENLABS_*_VOICE_ID env vars")

    a, b = d["debater_a"], d["debater_b"]
    intro = (
        f"Welcome to AI Bench Press. Today's resolution: {d['topic']} "
        f"Arguing yes, {a['name']}. Arguing no, {b['name']}. "
        "No humans on the panel. Let's begin."
    )

    # Segment order MUST match index.html: [host intro] + turns
    segments = [{"role": "host", "speaker": "Host", "phase": "Intro", "text": intro}]
    for t in d["turns"]:
        segments.append(t)

    voice_for = {"host": host_v, "yes": a_v, "no": b_v}
    playlist = []
    for i, seg in enumerate(segments):
        vid = voice_for.get(seg["role"], host_v)
        fname = f"seg_{i:02d}.mp3"
        out = AUDIO_DIR / fname
        print(f"  synth {fname:11s} {seg['speaker']:5s} [{seg['phase']}] {len(seg['text'].split())}w ...", flush=True)
        out.write_bytes(tts(vid, seg["text"]))
        playlist.append({"i": i, "file": f"audio/{fname}", "role": seg["role"],
                         "speaker": seg["speaker"], "phase": seg["phase"]})

    (HERE / "audio.js").write_text("window.AUDIO = " + json.dumps(playlist, indent=2) + ";\n", encoding="utf-8")
    total = sum((AUDIO_DIR / Path(p["file"]).name).stat().st_size for p in playlist)
    print(f"\n✓ {len(playlist)} segments, {total // 1024} KB total")
    print("✓ Wrote audio.js")
    return 0


if __name__ == "__main__":
    sys.exit(main())
