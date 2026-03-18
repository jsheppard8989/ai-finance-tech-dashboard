#!/usr/bin/env python3
"""
Weekly debate orchestrator — The Long and Short of It

Runs each Friday (cron): archives last week → LLM new Yes/No contract from DB context
→ LLM debater speeches → rotates pundit pair → ElevenLabs audio → writes public JSON.

No hardcoded weekly topic; contract + arguments come from the model + live Overton/insights.

Usage:
  python3 debate_weekly.py              # full run if new week (America/Chicago Friday)
  python3 debate_weekly.py --force      # regenerate even if same friday_iso
  python3 debate_weekly.py --dry-run    # print plan + LLM output, no audio
  python3 debate_weekly.py --audio-only # TTS only from last saved scripts
  python3 debate_weekly.py --resolve 2026-03-14 yes "Settled per filings"

Env: same as pipeline (Moonshot/OpenAI) + ELEVENLABS_* for audio.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

WORKSPACE = Path.home() / ".openclaw/workspace"
PIPELINE = WORKSPACE / "pipeline"
SITE_AUDIO = WORKSPACE / "site" / "audio"
SITE_DATA = WORKSPACE / "site" / "data"
DB_PATH = PIPELINE / "dashboard.db"
PUNDITS_PATH = SITE_DATA / "pundits.json"
CONTRACT_PATH = SITE_AUDIO / "debate_contract.json"
HISTORY_PATH = WORKSPACE / "site" / "debate_history.json"
SCRIPTS_STATE = PIPELINE / "state" / "last_debate_scripts.json"
ARCHIVE_DIR = SITE_AUDIO / "archive"
OUT_MP3 = SITE_AUDIO / "emp_ai_the_debate_11labs.mp3"

EXCLUDE_PUNDITS = frozenset(
    {"Dylan", "Moonshots", "Alexander Wissner-Gross", "Salim Ismail", "Dave Blundin"}
)

sys.path.insert(0, str(PIPELINE))


def load_env() -> None:
    for p in (WORKSPACE / ".env", PIPELINE / ".env"):
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


def friday_iso_cst(d: Optional[datetime] = None) -> str:
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Chicago")
    except Exception:
        tz = None
    now = d or datetime.now(tz or None)
    if tz and now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    wd = now.weekday()  # Mon=0, Fri=4
    days = (4 - wd) % 7
    target = (now.date() if hasattr(now, "date") else now) + timedelta(days=days)
    if hasattr(target, "isoformat"):
        return target.isoformat()
    return str(target)


def load_pundits() -> List[Dict[str, Any]]:
    if not PUNDITS_PATH.exists():
        return []
    try:
        rows = json.loads(PUNDITS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if (r.get("name") or "").strip() not in EXCLUDE_PUNDITS]
    return out


def pick_debaters(pundits: List[Dict[str, Any]], rotation: int) -> Tuple[Dict, Dict]:
    n = len(pundits)
    if n >= 2:
        i = (rotation * 2) % n
        j = (i + 1 + (rotation // max(1, n // 2))) % n
        if j == i:
            j = (i + 1) % n
        return pundits[i], pundits[j]
    if n == 1:
        return pundits[0], {"name": "Pundit B", "known_for": "", "bio": ""}
    return (
        {"name": "Pundit A", "known_for": "", "bio": ""},
        {"name": "Pundit B", "known_for": "", "bio": ""},
    )


def load_history() -> Dict[str, Any]:
    if not HISTORY_PATH.exists():
        return {"rotation_index": 0, "weeks": []}
    try:
        h = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"rotation_index": 0, "weeks": []}
    h.setdefault("rotation_index", 0)
    h.setdefault("weeks", [])
    return h


def save_history(h: Dict[str, Any]) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(h, indent=2), encoding="utf-8")


def load_context_from_db() -> Tuple[List[str], List[str]]:
    terms, titles = [], []
    if not DB_PATH.exists():
        return terms, titles
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            SELECT term FROM overton_terms
            WHERE status = 'active' OR status IS NULL
            ORDER BY COALESCE(last_mentioned_date, first_detected_date) DESC
            LIMIT 14
            """
        )
        terms = [r["term"] for r in cur.fetchall() if r["term"]]
        cur = conn.execute(
            """
            SELECT title FROM latest_insights
            ORDER BY COALESCE(source_date, added_date) DESC
            LIMIT 10
            """
        )
        titles = [r["title"] for r in cur.fetchall() if r["title"]]
        conn.close()
    except Exception:
        pass
    return terms, titles


def get_ai_client():
    from analyze_transcript import get_ai_client as _gc

    return _gc()


def _strip_json_fence(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def llm_chat_json(client_kind: str, client: Any, system: str, user: str) -> Dict[str, Any]:
    if client_kind == "moonshot" or client_kind == "openai":
        model = os.getenv("DEBATE_LLM_MODEL", "moonshot-v1-8k")
        if client_kind == "openai" and "moonshot" in model:
            model = os.getenv("OPENAI_DEBATE_MODEL", "gpt-4o-mini")
        r = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.75,
            max_tokens=2000,
        )
        text = (r.choices[0].message.content or "").strip()
    elif client_kind == "gemini":
        import google.generativeai as genai

        genai.configure(api_key=client)
        model = os.getenv("GEMINI_DEBATE_MODEL", "gemini-1.5-flash")
        m = genai.GenerativeModel(model)
        r = m.generate_content(
            f"{system}\n\n---\n\n{user}",
            generation_config={"temperature": 0.75},
        )
        text = (getattr(r, "text", None) or "").strip()
    else:
        raise RuntimeError("No LLM client")
    raw = _strip_json_fence(text)
    return json.loads(raw)


def generate_contract(
    client_kind: str, client: Any, overton: List[str], insights: List[str], avoid_prompts: List[str]
) -> Dict[str, Any]:
    system = """You are the editorial brain for a weekly investor debate show.
Return ONLY valid JSON with keys:
  "prompt": string — one clear Yes/No question, falsifiable within ~42 days, no single-stock tickers (no AAPL, NVDA, etc.); themes like AI, rates, labor, policy, indices OK.
  "expires_rule": string — human-readable e.g. "Resolves Friday 12:00 PM CST YYYY-MM-DD" (pick date = contract Friday + 42 days).
  "crux_theme": short label for the substance (e.g. "AI labor", "rates path").
  "resolution_clarity": { "source_of_truth": string, "resolution_sources": [string], "resolution_criteria": [string] } — brief, practical."""

    avoid = "\n".join(f"- {p[:200]}" for p in avoid_prompts[-5:]) or "(none yet)"
    ctx = f"Overton-style terms:\n{', '.join(overton) or '(none)'}\n\nRecent insight titles:\n" + "\n".join(
        f"- {t}" for t in insights
    ) or "- (none)"
    user = f"""{ctx}

Avoid repeating these past prompts:
{avoid}

Produce ONE fresh contract JSON. The question must be specific enough to argue yes/no on substance, not philosophy."""

    data = llm_chat_json(client_kind, client, system, user)
    for k in ("prompt", "expires_rule"):
        if k not in data or not str(data[k]).strip():
            raise ValueError(f"LLM contract missing {k}")
    data.setdefault("crux_theme", "")
    data.setdefault("resolution_clarity", {})
    data["sides"] = {"a": "Affirmative (YES)", "b": "Negative (NO)"}
    return data


def generate_speeches(
    client_kind: str,
    client: Any,
    prompt: str,
    crux: str,
    name_yes: str,
    name_no: str,
) -> Tuple[str, str]:
    system = """Return ONLY valid JSON:
  "yes_speech": string — plain text for text-to-speech. Speaker is arguing YES on the contract.
  "no_speech": string — plain text for TTS, arguing NO.

Rules:
- Start each speech with only the speaker's first line as their name plus period, e.g. "Sam." then blank line, then body. Use the exact names given.
- Three substantive paragraphs (or sections) plus a short "Concession." paragraph.
- Argue the CRUX of the issue (e.g. real economic force vs narrative). Do NOT nitpick the contract wording or hide behind legal parsing.
- Do NOT repeat or quote the full Yes/No question; the listener already heard it from the host.
- No stage directions, no markdown."""

    user = f"""Contract question (for your reasoning only — do not read it back verbatim in the speeches):
{prompt}

Crux theme: {crux or "general"}

YES speaker display name: {name_yes}
NO speaker display name: {name_no}

Write yes_speech and no_speech."""

    data = llm_chat_json(client_kind, client, system, user)
    ys = (data.get("yes_speech") or "").strip()
    ns = (data.get("no_speech") or "").strip()
    if len(ys) < 80 or len(ns) < 80:
        raise ValueError("LLM speeches too short")
    return ys, ns


def build_host_script(prompt: str, name_a: str, name_b: str) -> str:
    return (
        "Welcome to The Long and Short of It.\n"
        "Today’s contract debate topic is:\n"
        f"{prompt}\n\n"
        f"{name_a} will make the case for yes.\n"
        f"{name_b} will make the case for no."
    )


def archive_current_week(history: Dict[str, Any], prev_contract: Optional[Dict]) -> None:
    if not prev_contract or not prev_contract.get("friday_iso"):
        return
    fr = prev_contract["friday_iso"]
    # already in history?
    for w in history["weeks"]:
        if w.get("friday_iso") == fr:
            return
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    arc_mp3 = ARCHIVE_DIR / f"debate_{fr}.mp3"
    if OUT_MP3.exists() and OUT_MP3.stat().st_size > 1000:
        try:
            shutil.copy2(OUT_MP3, arc_mp3)
        except Exception:
            pass
    audio_href = f"./audio/archive/debate_{fr}.mp3" if arc_mp3.exists() else ""
    history["weeks"].insert(
        0,
        {
            "friday_iso": fr,
            "week_label": prev_contract.get("week_label") or f"Week of {fr}",
            "prompt": prev_contract.get("prompt", ""),
            "debater_a": prev_contract.get("debater_a", ""),
            "debater_b": prev_contract.get("debater_b", ""),
            "expires_rule": prev_contract.get("expires_rule", ""),
            "resolution_status": "pending",
            "resolution_notes": "",
            "archived_at": datetime.now().isoformat(),
            "audio_href": audio_href,
        },
    )


def write_scripts_state(host: str, yes_s: str, no_s: str) -> None:
    SCRIPTS_STATE.parent.mkdir(parents=True, exist_ok=True)
    SCRIPTS_STATE.write_text(
        json.dumps(
            {
                "host": host,
                "yes": yes_s,
                "no": no_s,
                "close": "This has been The Long and Short of It. Choose evidence over tribe.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def run_tts() -> None:
    from generate_debate_audio_11labs import tts

    load_env()
    bundle = json.loads(SCRIPTS_STATE.read_text(encoding="utf-8"))
    host_v = os.getenv("ELEVENLABS_HOST_VOICE_ID", "").strip()
    a_v = os.getenv("ELEVENLABS_A_VOICE_ID", "").strip()
    b_v = os.getenv("ELEVENLABS_B_VOICE_ID", "").strip()
    if not all([host_v, a_v, b_v]):
        raise RuntimeError("Missing ELEVENLABS_*_VOICE_ID")
    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    audio = (
        tts(host_v, bundle["host"])
        + tts(a_v, bundle["yes"])
        + tts(b_v, bundle["no"])
        + tts(host_v, bundle["close"])
    )
    OUT_MP3.write_bytes(audio)
    print(f"✓ Wrote {OUT_MP3} ({len(audio)} bytes)")


def public_contract(
    base: Dict[str, Any],
    friday: str,
    name_a: str,
    name_b: str,
) -> Dict[str, Any]:
    out = {k: v for k, v in base.items() if not str(k).startswith("script_")}
    out["friday_iso"] = friday
    out["week_label"] = f"Week of {friday}"
    out["debater_a"] = name_a
    out["debater_b"] = name_b
    out["generated_at"] = datetime.now().isoformat()
    out["bet_status"] = "open"
    out["audio_href"] = "./audio/emp_ai_the_debate_11labs.mp3"
    return out


def cmd_mark_resolved(friday_iso: str, status: str, notes: str) -> int:
    load_env()
    h = load_history()
    status = status.lower()
    if status not in ("yes", "no", "void", "pending"):
        print("status must be yes|no|void|pending")
        return 1
    for w in h["weeks"]:
        if w.get("friday_iso") == friday_iso:
            w["resolution_status"] = status
            w["resolution_notes"] = notes or ""
            w["resolved_at"] = datetime.now().isoformat()
            save_history(h)
            print(f"Updated {friday_iso} -> {status}")
            return 0
    print(f"Week {friday_iso} not found in history")
    return 1


def main() -> int:
    load_env()
    ap = argparse.ArgumentParser(description="Weekly debate orchestrator")
    ap.add_argument("--force", action="store_true", help="Regenerate even if friday_iso matches")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--audio-only", action="store_true", help="TTS from last_debate_scripts.json only")
    ap.add_argument("--mark-resolved", metavar="FRIDAY_ISO", help="With --status, update history")
    ap.add_argument("--status", choices=("yes", "no", "void", "pending"), help="Bet resolution for --mark-resolved")
    ap.add_argument("--notes", default="", help="Resolution notes")
    args = ap.parse_args()

    if args.mark_resolved:
        if not args.status:
            print("Use --status yes|no|void|pending with --mark-resolved")
            return 1
        return cmd_mark_resolved(args.mark_resolved, args.status, args.notes)

    if args.audio_only:
        if not SCRIPTS_STATE.exists():
            print("No last_debate_scripts.json — run full weekly generation first.")
            return 1
        run_tts()
        return 0

    friday = friday_iso_cst()
    history = load_history()
    prev = None
    if CONTRACT_PATH.exists():
        try:
            prev = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        except Exception:
            prev = None

    prev_friday = (prev or {}).get("friday_iso")
    if prev_friday == friday and not args.force:
        print(f"Contract already current for {friday}. Use --force to regenerate.")
        return 0

    ai = get_ai_client()
    if not ai:
        print("No LLM client. Configure Moonshot/OpenAI per pipeline.")
        return 1
    kind, client = ai

    overton, insights = load_context_from_db()
    avoid = [w.get("prompt", "") for w in history.get("weeks", [])]
    if prev and prev.get("prompt"):
        avoid.append(prev["prompt"])

    if args.dry_run:
        print(f"Friday (CST): {friday}")
        print(f"Context terms: {overton[:5]}...")
        c = generate_contract(kind, client, overton, insights, avoid)
        print(json.dumps(c, indent=2))
        return 0

    if prev:
        arch = dict(prev)
        if not arch.get("friday_iso"):
            ga = arch.get("generated_at") or ""
            arch["friday_iso"] = ga[:10] if len(ga) >= 10 else "legacy-pre-weekly"
        arch.setdefault("debater_a", "")
        arch.setdefault("debater_b", "")
        arch.setdefault("prompt", arch.get("prompt", ""))
        same_week_force = bool(args.force and prev_friday == friday)
        new_week = arch.get("friday_iso") != friday
        legacy_migrate = not prev_friday
        if not same_week_force and (new_week or legacy_migrate):
            archive_current_week(history, arch)
            save_history(history)

    contract_core = generate_contract(kind, client, overton, insights, avoid)
    rotation = history["rotation_index"]
    pundits = load_pundits()
    p_a, p_b = pick_debaters(pundits, rotation)
    name_a = (p_a.get("name") or "Debater A").strip()
    name_b = (p_b.get("name") or "Debater B").strip()

    yes_speech, no_speech = generate_speeches(
        kind,
        client,
        contract_core["prompt"],
        contract_core.get("crux_theme") or "",
        name_a,
        name_b,
    )
    host_s = build_host_script(contract_core["prompt"], name_a, name_b)
    write_scripts_state(host_s, yes_speech, no_speech)

    full_public = public_contract(contract_core, friday, name_a, name_b)
    SITE_AUDIO.mkdir(parents=True, exist_ok=True)
    CONTRACT_PATH.write_text(json.dumps(full_public, indent=2), encoding="utf-8")

    history["rotation_index"] = rotation + 1
    save_history(history)

    try:
        run_tts()
    except Exception as e:
        print(f"⚠ Audio failed (contract saved): {e}")
        return 1

    print(f"✓ Week {friday} | {name_a} vs {name_b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
