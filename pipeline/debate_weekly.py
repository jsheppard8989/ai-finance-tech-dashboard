#!/usr/bin/env python3
"""
Weekly debate orchestrator — The Long and Short of It

Runs each Friday (cron): archives last week → uses the approved editorial contract for that
Friday when present, otherwise generates an LLM Yes/No contract from DB context → LLM debater
speeches → rotates pundit pair → ElevenLabs audio → writes public JSON.

Editorial contracts live in `debate_editorial_contract.json`. Generated fallbacks use
Overton/insights + live Polymarket Gamma themes (filtered, volume-weighted) + anti-repeat rules;
speeches use full pundit profiles from `pundits.json`.

Usage:
  python3 debate_weekly.py              # full run if new week (America/Chicago Friday)
  python3 debate_weekly.py --force      # regenerate even if same friday_iso
  python3 debate_weekly.py --dry-run    # print plan + LLM output, no audio
  python3 debate_weekly.py --scripts-only # generate review scripts; no archive, audio, or publish
  python3 debate_weekly.py --audio-only # TTS only from last saved scripts
  python3 debate_weekly.py --resolve 2026-03-14 yes "Settled per filings"

Env: same as pipeline (Moonshot/OpenAI) + ELEVENLABS_* for audio.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from workspace_paths import DB_PATH, PIPELINE_DIR as PIPELINE, SITE_DATA_DIR as SITE_DATA, SITE_DIR

WORKSPACE = SITE_DIR.parent
SITE_AUDIO = SITE_DIR / "audio"
PUNDITS_PATH = SITE_DATA / "pundits.json"
CONTRACT_PATH = SITE_AUDIO / "debate_contract.json"
EDITORIAL_CONTRACT_PATH = PIPELINE / "debate_editorial_contract.json"
HISTORY_PATH = SITE_DIR / "debate_history.json"
SCRIPTS_STATE = PIPELINE / "state" / "last_debate_scripts.json"
ARCHIVE_DIR = SITE_AUDIO / "archive"
ARCHIVE_MANIFEST_PATH = SITE_AUDIO / "archive_manifest.json"
OUT_MP3 = SITE_AUDIO / "emp_ai_the_debate_11labs.mp3"
AUDIO_META_PATH = SITE_AUDIO / "debate_audio_meta.json"

sys.path.insert(0, str(PIPELINE))

from pundit_exclusions import is_excluded_debater_name, is_excluded_pundit_name

try:
    from polymarket_debate_context import fetch_polymarket_debate_context
except ImportError:
    fetch_polymarket_debate_context = None  # type: ignore

try:
    from debate_quality import (
        stamp_contract_publishable,
        validate_contract_publishable,
        validate_debaters,
        validate_editorial_note,
        validate_prompt_not_repetitive,
        validate_resolution_clarity,
        validate_spx_strike_plausible,
    )
except ImportError:
    stamp_contract_publishable = None  # type: ignore
    validate_contract_publishable = None  # type: ignore
    validate_debaters = None  # type: ignore
    validate_editorial_note = None  # type: ignore
    validate_prompt_not_repetitive = None  # type: ignore
    validate_resolution_clarity = None  # type: ignore
    validate_spx_strike_plausible = None  # type: ignore


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


def now_cst_context() -> str:
    """Human-readable clock + contract window for LLM prompts."""
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/Chicago")
        now = datetime.now(tz)
    except Exception:
        now = datetime.now()
        tz = None
    friday = friday_iso_cst(now)
    resolves = resolves_iso_from_friday(friday)
    if tz:
        stamp = now.strftime("%A, %B %d, %Y %I:%M %p %Z")
    else:
        stamp = now.strftime("%A, %B %d, %Y %I:%M %p")
    return (
        f"TODAY (America/Chicago): {stamp}\n"
        f"Current contract Friday: {friday}\n"
        f"Resolution date (+42 days): {resolves}"
    )


def load_pundits() -> List[Dict[str, Any]]:
    if not PUNDITS_PATH.exists():
        return []
    try:
        rows = json.loads(PUNDITS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(rows, list):
        return []
    out = [r for r in rows if not is_excluded_pundit_name((r.get("name") or ""))]
    return out


def pick_debaters(pundits: List[Dict[str, Any]], rotation: int) -> Tuple[Dict, Dict]:
    eligible = [
        p for p in pundits if not is_excluded_debater_name((p.get("name") or ""))
    ]
    n = len(eligible)
    if n >= 2:
        i = (rotation * 2) % n
        j = (i + 1 + (rotation // max(1, n // 2))) % n
        if j == i:
            j = (i + 1) % n
        return eligible[i], eligible[j]
    if n == 1:
        return eligible[0], {"name": "Pundit B", "known_for": "", "bio": ""}
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


def load_editorial_contract(friday_iso: str, path: Optional[Path] = None) -> Optional[Dict[str, Any]]:
    """Load a human-approved contract only for its explicitly scheduled Friday."""
    source = path or EDITORIAL_CONTRACT_PATH
    if not source.exists():
        return None
    try:
        contract = json.loads(source.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(contract, dict):
        return None
    if (contract.get("friday_iso") or "").strip() != friday_iso:
        return None
    return contract


def archive_audio_href(friday_iso: str) -> str:
    fr = (friday_iso or "").strip()
    if not fr:
        return ""
    arc_mp3 = ARCHIVE_DIR / f"debate_{fr}.mp3"
    return f"./audio/archive/debate_{fr}.mp3" if arc_mp3.exists() and arc_mp3.stat().st_size > 1000 else ""


def resolves_iso_from_friday(friday_iso: str) -> str:
    fr = (friday_iso or "").strip()[:10]
    if not fr:
        return ""
    try:
        friday_date = datetime.strptime(fr, "%Y-%m-%d").date()
        return (friday_date + timedelta(days=42)).isoformat()
    except Exception:
        return ""


def parse_resolves_iso_from_expires_rule(expires_rule: str) -> str:
    m = re.search(r"\d{4}-\d{2}-\d{2}", expires_rule or "")
    return m.group(0) if m else ""


def sync_history_resolves_dates(history: Dict[str, Any]) -> None:
    """Ensure each history week has resolves_iso (contract Friday + 42 days)."""
    for w in history.get("weeks", []):
        iso = (w.get("resolves_iso") or "").strip()
        if not iso:
            iso = parse_resolves_iso_from_expires_rule(w.get("expires_rule") or "")
        if not iso:
            iso = resolves_iso_from_friday(w.get("friday_iso") or "")
        if not iso:
            continue
        w["resolves_iso"] = iso
        rule = (w.get("expires_rule") or "").strip()
        if not rule or not parse_resolves_iso_from_expires_rule(rule):
            try:
                res_date = datetime.strptime(iso, "%Y-%m-%d").date()
                day_name = res_date.strftime("%A")
                w["expires_rule"] = f"Resolves {day_name} 12:00 PM CST {iso}"
            except Exception:
                w["expires_rule"] = f"Resolves Friday 12:00 PM CST {iso}"


def sync_history_audio_refs(history: Dict[str, Any]) -> None:
    """Drop stale audio_href entries when the archive MP3 is missing."""
    for w in history.get("weeks", []):
        fr = (w.get("friday_iso") or "").strip()
        href = archive_audio_href(fr) if fr else ""
        if href:
            w["audio_href"] = href
        else:
            w.pop("audio_href", None)


def write_archive_manifest() -> None:
    """List archive MP3s present on disk (site + deploy use this for Listen links)."""
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    entries: List[Dict[str, str]] = []
    for path in sorted(ARCHIVE_DIR.glob("debate_*.mp3"), reverse=True):
        if path.stat().st_size <= 1000:
            continue
        fr = path.stem.replace("debate_", "", 1)
        if not fr:
            continue
        entries.append({"friday_iso": fr, "audio_href": f"./audio/archive/{path.name}"})
    ARCHIVE_MANIFEST_PATH.write_text(
        json.dumps({"generated_at": datetime.now().isoformat(), "archives": entries}, indent=2),
        encoding="utf-8",
    )


def save_history(h: Dict[str, Any]) -> None:
    sync_history_resolves_dates(h)
    sync_history_audio_refs(h)
    write_archive_manifest()
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
        common = dict(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.75,
            max_tokens=2000,
        )
        # Best-effort: force strict JSON output (prevents parse crashes).
        try:
            r = client.chat.completions.create(
                **common, response_format={"type": "json_object"}
            )
        except Exception:
            r = client.chat.completions.create(**common)
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
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback: try to extract the first JSON object substring.
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end != -1 and end > start:
            raw2 = raw[start : end + 1]
            return json.loads(raw2)
        raise


def _banned_numeric_anchors(avoid_prompts: List[str]) -> str:
    """Surface numbers from prior contracts so the model avoids repeating the same thresholds (e.g. 50k twice)."""
    found: set = set()
    for p in avoid_prompts:
        if not p:
            continue
        for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,}\b|\b\d+\.\d+\b", p):
            found.add(m.group(0).strip())
    if not found:
        return ""
    sample = sorted(found, key=len, reverse=True)[:24]
    return (
        "Banned numeric anchors from prior contracts (do NOT reuse these exact figures or the same "
        "round-number pattern on a different topic — e.g. if last week used 50,000 layoffs, do not use "
        "$50,000 BTC or any other 50,000 this week):\n"
        + ", ".join(sample)
    )


def fetch_yahoo_last_price(symbol: str) -> Optional[float]:
    """Last regular-market price for a Yahoo symbol (e.g. ^GSPC, BTC-USD)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol, safe='')}?interval=1d&range=5d"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 (debate_weekly; scarcity-abundance-dashboard)"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    try:
        result = data.get("chart", {}).get("result")
        if not result:
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice") or meta.get("previousClose")
        if price is None:
            return None
        return float(price)
    except (TypeError, ValueError, IndexError, KeyError):
        return None


def build_macro_reference_block() -> Tuple[str, Optional[float], Optional[float]]:
    """
    Live levels for sanity-checking index/crypto questions (^GSPC = S&P 500 index, not SPY).
    Returns (markdown block for LLM, spx_ref, btc_ref).
    """
    spx = fetch_yahoo_last_price("^GSPC")
    btc = fetch_yahoo_last_price("BTC-USD")
    lines = [
        "=== LIVE MARKET REFERENCE (Yahoo Finance; use for sanity checks — NOT optional) ===",
        (
            f"As of this generation run, approximate levels: S&P 500 index (^GSPC) ≈ {spx:,.2f}"
            if spx
            else "S&P 500 index (^GSPC): (unavailable — avoid inventing index strikes; prefer Polymarket-only themes without numeric index levels.)"
        ),
    ]
    if btc:
        lines.append(f"Bitcoin (BTC-USD) ≈ ${btc:,.2f}")
    if spx and spx > 1000:
        lines.extend(
            [
                "Rules for ANY question involving S&P / SPX / 'S&P 500':",
                f"  - A threshold for RALLY / EXCEED / CLOSE ABOVE / BREAK ABOVE must be ≥ ~{spx * 0.82:,.0f} with spot ~{spx:,.0f} (do not use years-old index levels).",
                f"  - A threshold for CRASH / FALL BELOW / CLOSE BELOW must be clearly below spot (e.g. under ~{spx * 0.88:,.0f}) and phrased as downside risk, not 'exceed'.",
                "  - If you cannot state a defensible level, do NOT use an S&P index strike — pick a different resolution from the Polymarket list (policy, rates, ETF, election, etc.).",
            ]
        )
    if btc and btc > 100:
        lines.append(
            "Rules for Bitcoin USD levels: any strike must be within ~0.45×–2.1× the BTC reference above unless the Polymarket market explicitly discusses a different strike."
        )
    lines.append("=== END LIVE REFERENCE ===")
    return "\n".join(lines), spx, btc


def _prompt_numbers_in_range(text: str, lo: float, hi: float) -> List[float]:
    out: List[float] = []
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,6}(?:\.\d+)?\b", text):
        s = m.group(0).replace(",", "")
        try:
            v = float(s)
        except ValueError:
            continue
        if lo <= v <= hi:
            out.append(v)
    return out


def validate_prompt_macro_sanity(
    prompt: str,
    spx_ref: Optional[float],
    btc_ref: Optional[float],
) -> Tuple[bool, str]:
    """
    Reject obviously stale training-data index levels (e.g. S&P 'exceed 4,500' when spot ~6,600).
    """
    if not (prompt or "").strip():
        return False, "empty prompt"
    pl = prompt.lower()

    spx_m = re.search(r"s&p|s\s*&\s*p\s*500|\bspx\b|\bsp\s*500\b|s\s*p\s*500", pl)
    if spx_m and spx_ref and spx_ref > 1000:
        nums = _prompt_numbers_in_range(prompt, 2000.0, 12000.0)
        bullish = bool(
            re.search(
                r"\b(exceed|above|higher\s+than|surpass|rally|break\s+above|close\s+above|finish\s+above)\b",
                pl,
            )
        )
        bearish = bool(
            re.search(
                r"\b(below|under|fall|crash|drop|close\s+below|finish\s+below|bear\s+market)\b",
                pl,
            )
        )
        for n in nums:
            if bullish and n < spx_ref * 0.82:
                return (
                    False,
                    f"S&P bullish threshold {n:,.0f} is inconsistent with current index ~{spx_ref:,.0f} (likely stale).",
                )
            if bearish and n > spx_ref * 1.12:
                return (
                    False,
                    f"S&P bearish threshold {n:,.0f} is far above spot ~{spx_ref:,.0f}; rephrase or pick a Polymarket theme.",
                )
            if not bullish and not bearish and (n < spx_ref * 0.68 or n > spx_ref * 1.32):
                return (
                    False,
                    f"S&P numeric {n:,.0f} is implausible vs spot ~{spx_ref:,.0f} without clear bull/bear wording.",
                )

    if btc_ref and btc_ref > 100 and re.search(r"\bbitcoin\b|\bbtc\b", pl):
        nums = _prompt_numbers_in_range(prompt, 5000.0, 500_000.0)
        for n in nums:
            if n < btc_ref * 0.42 or n > btc_ref * 2.2:
                return False, f"BTC level {n:,.0f} is far from spot ~{btc_ref:,.0f}."

    return True, ""


def _extract_prompt_calendar_dates(prompt: str) -> List[Tuple[str, datetime.date]]:
    dates: List[Tuple[str, datetime.date]] = []
    seen: set = set()
    text = prompt or ""

    for m in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", text):
        raw = m.group(0)
        try:
            d = datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            continue
        key = (raw, d.isoformat())
        if key in seen:
            continue
        seen.add(key)
        dates.append((raw, d))

    month_re = re.compile(
        r"\b("
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
        r")\s+(\d{1,2})(?:,)?\s+(\d{4})\b",
        flags=re.IGNORECASE,
    )
    for m in month_re.finditer(text):
        raw = m.group(0)
        mon = m.group(1)
        day = m.group(2)
        yr = m.group(3)
        d = None
        for fmt in ("%b %d %Y", "%B %d %Y"):
            try:
                d = datetime.strptime(f"{mon} {day} {yr}", fmt).date()
                break
            except Exception:
                continue
        if not d:
            continue
        key = (raw, d.isoformat())
        if key in seen:
            continue
        seen.add(key)
        dates.append((raw, d))

    return dates


def validate_prompt_temporal_window(prompt: str, friday_iso: str, resolves_iso: str) -> Tuple[bool, str]:
    """
    Hard fail when explicit calendar dates in the prompt fall outside the contract window.
    """
    try:
        window_start = datetime.strptime((friday_iso or "")[:10], "%Y-%m-%d").date()
        window_end = datetime.strptime((resolves_iso or "")[:10], "%Y-%m-%d").date()
    except Exception:
        return False, "invalid contract date window (friday_iso/resolves_iso)"

    for raw, d in _extract_prompt_calendar_dates(prompt or ""):
        if d < window_start:
            return (
                False,
                f"Prompt date '{raw}' is before friday_iso {window_start.isoformat()} (outside 42-day contract window).",
            )
        if d > window_end:
            return (
                False,
                f"Prompt date '{raw}' is after resolves_iso {window_end.isoformat()} (outside 42-day contract window).",
            )
    return True, ""


def validate_prompt_event_plausibility(prompt: str, friday_iso: str, resolves_iso: str) -> Tuple[bool, str]:
    """
    Reject contracts that imply elections or chamber flips unlikely inside a 42-day window.
    """
    pl = (prompt or "").lower()
    if re.search(r"\b(senate|house of representatives|u\.s\. house)\b", pl) and re.search(
        r"\b(control(?:led by)?|majority|flip|takeover)\b", pl
    ):
        if not re.search(r"\b(special election|runoff|recall|by-election)\b", pl):
            return (
                False,
                "Chamber-control questions usually require an election outside a 42-day window; "
                "pick a policy, market, or local-government event instead.",
            )
    if re.search(r"\b(presidential|parliamentary|general) election\b", pl):
        for raw, d in _extract_prompt_calendar_dates(prompt):
            try:
                window_start = datetime.strptime((friday_iso or "")[:10], "%Y-%m-%d").date()
                window_end = datetime.strptime((resolves_iso or "")[:10], "%Y-%m-%d").date()
            except Exception:
                return False, "invalid date window for election check"
            if d < window_start or d > window_end:
                return (
                    False,
                    f"Election date '{raw}' is outside friday_iso–resolves_iso ({window_start} to {window_end}).",
                )
    return True, ""


def generate_contract(
    client_kind: str,
    client: Any,
    overton: List[str],
    insights: List[str],
    avoid_prompts: List[str],
    friday_iso: str = "",
    resolves_iso: str = "",
    polymarket_context: str = "",
    macro_reference_block: str = "",
    retry_hint: str = "",
) -> Dict[str, Any]:
    system = """You are the editorial brain for a weekly investor debate show.
Return ONLY valid JSON with keys:
  "prompt": string — one clear Yes/No question, falsifiable within ~42 days, no single-stock tickers (no AAPL, NVDA, etc.); themes like AI, rates, labor, policy, macro, crypto OK. Phrase the time window as **within the next 42 days** — do not use "by the end of the next 42 days".
  "editorial_note": string — 2–4 sentences explaining why WE picked this topic this week (feed friction, podcast themes, market relevance). Write in first-person plural ("we").
  "expires_rule": string — human-readable e.g. "Resolves Friday 12:00 PM CST YYYY-MM-DD" (pick date = contract Friday + 42 days). Use the CURRENT calendar year from context.
  "crux_theme": short label for the substance (e.g. "AI labor", "rates path").
  "resolution_clarity": { "source_of_truth": string, "resolution_sources": [string], "resolution_criteria": [string] } — concrete enough to settle the bet (feeds, agencies, official data), not vague.

PRIMARY SOURCE OF TRUTH FOR TOPICS:
- The user message includes LIVE Polymarket markets AND a LIVE macro reference block. Prefer adapting ONE Polymarket market into a paraphrased Yes/No (policy, macro, election, rates, crypto regulation, etc.).
- Do NOT invent synthetic index price strikes from memory (e.g. outdated S&P levels). If the question involves S&P / SPX / S&P 500, you MUST follow the numeric rules in the LIVE REFERENCE block.
- If you cannot meet those rules, choose a non-index Polymarket theme instead of a bad index question.
- STRICT TEMPORAL WINDOW: the contract Friday and resolution date are provided below. Any explicit calendar date mentioned in the prompt/criteria must fall inside that window. Do not use past-year windows.
- TODAY's date/time is in the user message. Never write contracts about U.S. Senate/House control or national elections unless a verifiable election falls between friday_iso and resolves_iso.

Anti-stale rules:
- Each week must feel NEW: different theme AND different numeric thresholds than recent weeks unless unavoidable.
- Prefer specific resolution metrics (what data source, what counts as Yes) inspired by prediction-market clarity; write an ORIGINAL question — do not copy Polymarket wording verbatim.
- Avoid lazy round-number reuse (e.g. repeating "50,000" across unrelated topics)."""

    avoid_tail = avoid_prompts[-15:] if avoid_prompts else []
    avoid = "\n".join(f"- {p[:400]}" for p in avoid_tail) or "(none yet)"
    banned_nums = _banned_numeric_anchors(avoid_tail)
    ctx = f"Overton-style terms:\n{', '.join(overton) or '(none)'}\n\nRecent insight titles:\n" + "\n".join(
        f"- {t}" for t in insights
    ) or "- (none)"
    poly = (polymarket_context or "").strip() or "(Polymarket context not loaded.)"
    macro = (macro_reference_block or "").strip() or "(No live macro reference — prefer non-numeric Polymarket themes.)"
    banned_block = f"\n\n{banned_nums}\n" if banned_nums else "\n"
    retry_block = f"\n\nVALIDATION RETRY — fix this issue and regenerate JSON only:\n{retry_hint}\n" if retry_hint.strip() else ""
    user = f"""{now_cst_context()}

Contract date window (HARD CONSTRAINT):
- friday_iso: {friday_iso or "(missing)"}
- resolves_iso: {resolves_iso or "(missing)"}
- Prompt/criteria must stay inside this window OR use only "within the next 42 days".

{macro}

{ctx}

{poly}
{banned_block}
Avoid repeating or lightly paraphrasing these past prompts (full text matters — stay distinct):
{avoid}
{retry_block}

Produce ONE fresh contract JSON. The question must be specific enough to argue yes/no on substance, not philosophy."""

    data = llm_chat_json(client_kind, client, system, user)
    for k in ("prompt", "expires_rule"):
        if k not in data or not str(data[k]).strip():
            raise ValueError(f"LLM contract missing {k}")
    data.setdefault("crux_theme", "")
    data.setdefault("editorial_note", "")
    data.setdefault("resolution_clarity", {})
    data["sides"] = {"a": "Affirmative (YES)", "b": "Negative (NO)"}
    return data


def build_speech_evidence_context(contract: Dict[str, Any]) -> str:
    """Format only contract-attached, editor-reviewed material as speech evidence."""
    packet: Dict[str, Any] = {}
    if contract.get("evidence_brief"):
        packet["evidence_brief"] = contract["evidence_brief"]
    if contract.get("editorial_note"):
        packet["editorial_note"] = contract["editorial_note"]
    clarity = contract.get("resolution_clarity")
    if isinstance(clarity, dict) and clarity:
        packet["resolution_clarity"] = clarity
    return json.dumps(packet, indent=2, ensure_ascii=False) if packet else ""


def generate_speeches(
    client_kind: str,
    client: Any,
    prompt: str,
    crux: str,
    name_yes: str,
    name_no: str,
    context_yes: str = "",
    context_no: str = "",
    evidence_context: str = "",
) -> Tuple[str, str]:
    system = """Return ONLY valid JSON:
  "yes_speech": string — plain text for text-to-speech. Speaker is arguing YES on the contract.
  "no_speech": string — plain text for TTS, arguing NO.

Objective:
- Maximize truth and understanding, not rhetorical victory. A strong argument may openly weaken its own case.
- Build from first principles: clearly defensible constraints, incentives, causal mechanisms, base rates, and tradeoffs. Do not use slogans, popularity, authority, or ideology as foundations.

Rules:
- Start each speech with only the speaker's first line as their name plus period, e.g. "Sam." then blank line, then body. Use the exact names given.
- Write entirely in English, including every paragraph.
- The first sentence of YES body must begin with "The long of it".
- The first sentence of NO body must begin with "The short of it".
- Use three substantive paragraphs plus a short paragraph beginning exactly "Concession."
- First explain in plain English what the proposal or event would change, who is affected, and how the mechanism works. Assume no prior knowledge.
- Separate verified fact from inference, forecast, and value judgment in natural language. Never present an assumption or prediction as an established fact.
- Use specific figures, dates, studies, or quotations only when they appear in the supplied evidence packet. Name the source near the claim. Never invent evidence or vaguely invoke "studies," "data," "history," "experts," or "indicators."
- Show the causal chain behind the conclusion step by step and identify its weakest link.
- Steelman the strongest opposing case and address its strongest evidence. Do not create a weak or caricatured opponent.
- In "Concession.", state the most important uncertainty and one concrete observation that would change the speaker's conclusion.
- Argue the CRUX of the issue (e.g. real economic force vs narrative). Do NOT nitpick the contract wording or hide behind legal parsing.
- Do NOT repeat or quote the full Yes/No question; the listener already heard it from the host.
- Each speaker's argument should reflect their real background and rhetorical style as described in their profile — without caricature.
- End the substantive case with a realistic path for AI to increase U.S. productivity, wages, business formation, or competitiveness while addressing the risks raised. Keep optimism conditional and evidence-based, never promotional.
- No stage directions, no markdown."""

    user = f"""Contract question (for your reasoning only — do not read it back verbatim in the speeches):
{prompt}

Crux theme: {crux or "general"}

--- VERIFIED EVIDENCE PACKET ---
{evidence_context or "(No verified evidence packet was supplied. Do not introduce empirical specifics; reason from clearly labeled assumptions and first principles only.)"}

--- YES speaker ({name_yes}) — use background and voice to shape the argument ---
{context_yes or "(minimal profile)"}

--- NO speaker ({name_no}) — use background and voice to shape the argument ---
{context_no or "(minimal profile)"}

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


def _debater_llm_context(p: Dict[str, Any]) -> str:
    """
    Everything we have on a pundit for speech generation: identity, bio, voice notes,
    recent thesis, optional structured profile (from Grokipedia or LLM enrichment).
    """
    lines: List[str] = []
    name = (p.get("name") or "").strip() or "Debater"
    lines.append(f"Speaker display name: {name}")
    if (p.get("known_for") or "").strip():
        lines.append(f"Known for: {(p.get('known_for') or '').strip()}")
    if (p.get("bio") or "").strip():
        lines.append(f"Bio: {(p.get('bio') or '').strip()[:1400]}")
    vp: List[str] = []
    if (p.get("voice_tone") or "").strip():
        vp.append(f"Tone: {(p.get('voice_tone') or '').strip()}")
    if (p.get("voice_style") or "").strip():
        vp.append(f"Speaking style: {(p.get('voice_style') or '').strip()}")
    if (p.get("voice_delivery_notes") or "").strip():
        vp.append(f"TTS / delivery: {(p.get('voice_delivery_notes') or '').strip()}")
    if vp:
        lines.append("Voice and debate delivery (honor these in word choice and rhythm):\n" + "\n".join(vp))
    if (p.get("last_main_idea") or "").strip():
        lines.append(
            f"Recent thesis on our dashboard (their last appearance): {(p.get('last_main_idea') or '').strip()[:700]}"
        )
    if (p.get("last_episode_title") or "").strip():
        ep = (p.get("last_podcast_name") or "").strip()
        dt = (p.get("last_episode_date") or "").strip()
        lines.append(
            f"Last episode context: {(p.get('last_episode_title') or '').strip()}"
            + (f" — {ep}" if ep else "")
            + (f" ({dt})" if dt else "")
        )
    prof = p.get("pundit_profile")
    if isinstance(prof, dict):
        der = prof.get("derived") if isinstance(prof.get("derived"), dict) else {}
        bits: List[str] = []
        for key in (
            "current_role",
            "former_positions",
            "boards",
            "education",
            "political_affiliation",
            "political_summary",
            "books_or_works",
            "teaching_summary",
        ):
            v = der.get(key) if isinstance(der, dict) else None
            if v and str(v).strip():
                bits.append(f"{key}: {str(v).strip()[:450]}")
        if bits:
            lines.append("Structured background:\n" + "\n".join(bits))
        cliff = (prof.get("cliff_notes") or "").strip()
        if cliff:
            lines.append(f"Expanded background (excerpt): {cliff[:1100]}")
    return "\n\n".join(lines) if lines else f"Speaker: {name} (no extended profile yet)."


def archive_current_week(history: Dict[str, Any], prev_contract: Optional[Dict]) -> None:
    if not prev_contract or not prev_contract.get("friday_iso"):
        return
    if prev_contract.get("publishable") is False:
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
    audio_href = archive_audio_href(fr)
    history["weeks"].insert(
        0,
        {
            "friday_iso": fr,
            "week_label": prev_contract.get("week_label") or f"Week of {fr}",
            "prompt": prev_contract.get("prompt", ""),
            "debater_a": prev_contract.get("debater_a", ""),
            "debater_b": prev_contract.get("debater_b", ""),
            "expires_rule": prev_contract.get("expires_rule", ""),
            "resolves_iso": (prev_contract.get("resolves_iso") or resolves_iso_from_friday(fr)),
            "resolution_status": "pending",
            "resolution_notes": "",
            "archived_at": datetime.now().isoformat(),
            "audio_href": audio_href,
        },
    )


def write_scripts_state(
    host: str,
    yes_s: str,
    no_s: str,
    review_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    SCRIPTS_STATE.parent.mkdir(parents=True, exist_ok=True)
    bundle: Dict[str, Any] = {
        "host": host,
        "yes": yes_s,
        "no": no_s,
        "close": "This has been The Long and Short of It. Choose evidence over tribe.",
    }
    if review_metadata:
        bundle["review"] = review_metadata
    SCRIPTS_STATE.write_text(
        json.dumps(bundle, indent=2),
        encoding="utf-8",
    )


def _first_line_name(speech: str) -> str:
    line = (speech or "").strip().splitlines()[0].strip() if (speech or "").strip() else ""
    if line.endswith("."):
        line = line[:-1]
    return line.strip()


def _has_non_english_script(text: str) -> bool:
    """Reject substantial CJK, Cyrillic, Arabic, or Hebrew output before TTS."""
    chars = re.findall(
        r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
        r"\uac00-\ud7af\u0400-\u052f\u0590-\u05ff\u0600-\u06ff]",
        text or "",
    )
    return len(chars) >= 8


def validate_speeches(yes_s: str, no_s: str, expected_yes: str, expected_no: str) -> None:
    got_yes = _first_line_name(yes_s)
    got_no = _first_line_name(no_s)
    if got_yes.lower() != (expected_yes or "").strip().lower():
        raise ValueError(f"YES speech speaker mismatch: expected '{expected_yes}', got '{got_yes}'")
    if got_no.lower() != (expected_no or "").strip().lower():
        raise ValueError(f"NO speech speaker mismatch: expected '{expected_no}', got '{got_no}'")
    yes_body = "\n".join((yes_s or "").strip().splitlines()[1:]).strip()
    no_body = "\n".join((no_s or "").strip().splitlines()[1:]).strip()
    if not yes_body.lower().startswith("the long of it"):
        raise ValueError("YES speech must begin with 'The long of it'.")
    if not no_body.lower().startswith("the short of it"):
        raise ValueError("NO speech must begin with 'The short of it'.")
    for side, speech, body in (("YES", yes_s, yes_body), ("NO", no_s, no_body)):
        if _has_non_english_script(body):
            raise ValueError(f"{side} speech must be entirely in English.")
        if not re.search(r"(?m)^Concession\.", speech or ""):
            raise ValueError(f"{side} speech must include a 'Concession.' paragraph.")


def run_tts(
    friday_iso: str = "",
    expected_yes: str = "",
    expected_no: str = "",
    prompt: str = "",
) -> Dict[str, Any]:
    from generate_debate_audio_11labs import tts

    load_env()
    bundle = json.loads(SCRIPTS_STATE.read_text(encoding="utf-8"))
    yes_name = _first_line_name(bundle.get("yes", ""))
    no_name = _first_line_name(bundle.get("no", ""))
    if expected_yes and yes_name.lower() != expected_yes.strip().lower():
        raise RuntimeError(f"Audio safety check failed: YES speaker in script is '{yes_name}', expected '{expected_yes}'")
    if expected_no and no_name.lower() != expected_no.strip().lower():
        raise RuntimeError(f"Audio safety check failed: NO speaker in script is '{no_name}', expected '{expected_no}'")

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
    prompt_hash = hashlib.sha256((prompt or "").encode("utf-8")).hexdigest()[:16] if prompt else ""
    meta = {
        "generated_at": datetime.now().isoformat(),
        "friday_iso": friday_iso or "",
        "debater_a": yes_name,
        "debater_b": no_name,
        "prompt_hash": prompt_hash,
        "audio_file": OUT_MP3.name,
        "bytes": len(audio),
    }
    AUDIO_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"✓ Wrote {AUDIO_META_PATH}")
    return meta


def _pundit_snapshot_for_contract(p: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Embed public pundit fields at generation time so debait.html still renders bios if names later fall out of top-N export."""
    if not p or not isinstance(p, dict):
        return {}
    out: Dict[str, Any] = {}
    for key in (
        "name",
        "known_for",
        "bio",
        "last_main_idea",
        "last_podcast_name",
        "last_episode_date",
    ):
        v = p.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    nw = p.get("net_worth")
    if isinstance(nw, str) and nw.strip():
        out["net_worth"] = nw.strip()
    else:
        nwu = p.get("net_worth_usd")
        if isinstance(nwu, (int, float)) and nwu > 0:
            if nwu >= 1_000_000_000:
                out["net_worth"] = f"${nwu / 1_000_000_000:.2f}B"
            elif nwu >= 1_000_000:
                out["net_worth"] = f"${nwu / 1_000_000:.1f}M"
            else:
                out["net_worth"] = f"${nwu:,.0f}"
    prof = p.get("pundit_profile")
    if isinstance(prof, dict) and prof:
        out["pundit_profile"] = prof
    return out


def public_contract(
    base: Dict[str, Any],
    friday: str,
    name_a: str,
    name_b: str,
    p_a: Optional[Dict[str, Any]] = None,
    p_b: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out = {k: v for k, v in base.items() if not str(k).startswith("script_")}
    out["friday_iso"] = friday
    out["week_label"] = f"Week of {friday}"
    out["debater_a"] = name_a
    out["debater_b"] = name_b
    out["generated_at"] = datetime.now().isoformat()
    out["bet_status"] = "open"
    out["audio_href"] = "./audio/emp_ai_the_debate_11labs.mp3"
    sa = _pundit_snapshot_for_contract(p_a)
    sb = _pundit_snapshot_for_contract(p_b)
    if sa:
        out["debater_a_snapshot"] = sa
    if sb:
        out["debater_b_snapshot"] = sb
    return out


def validate_contract_audio_match(contract: Dict[str, Any], audio_meta: Dict[str, Any]) -> None:
    if not audio_meta:
        raise RuntimeError("Audio metadata missing; refusing to publish contract.")
    for k in ("friday_iso", "debater_a", "debater_b"):
        cv = (contract.get(k) or "").strip().lower()
        av = (audio_meta.get(k) or "").strip().lower()
        if cv != av:
            raise RuntimeError(f"Publish safety check failed: contract {k}='{contract.get(k)}' != audio {k}='{audio_meta.get(k)}'")
    ch = (contract.get("prompt_hash") or "").strip().lower()
    ah = (audio_meta.get("prompt_hash") or "").strip().lower()
    if ch and ah and ch != ah:
        raise RuntimeError("Publish safety check failed: contract/audio prompt hashes differ.")


def _enforce_contract_resolution_dates(contract: Dict[str, Any], friday_iso: str) -> Dict[str, Any]:
    """
    Deterministically enforce the resolution/expiration date based on friday_iso + 42 days.

    The LLM may pick an incorrect YEAR when generating the prompt/criteria. We overwrite the relevant
    fields so they are consistent for the given contract friday.
    """
    if not contract or not friday_iso:
        return contract

    try:
        friday_date = datetime.strptime(friday_iso[:10], "%Y-%m-%d").date()
    except Exception:
        return contract

    resolution_date = friday_date + timedelta(days=42)
    date_iso = resolution_date.isoformat()  # YYYY-MM-DD
    date_long = resolution_date.strftime("%b %d, %Y")  # May 31, 2025
    day_name = resolution_date.strftime("%A")  # Should be Friday

    # expires_rule + machine-readable resolves date for the site history table
    contract["expires_rule"] = f"Resolves {day_name} 12:00 PM CST {date_iso}"
    contract["resolves_iso"] = date_iso

    # resolution_clarity.resolution_criteria
    rc = contract.get("resolution_clarity") or {}
    if isinstance(rc, dict):
        criteria = rc.get("resolution_criteria")
        if isinstance(criteria, list):
            month_name_re = re.compile(
                r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
                r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
                r"\s+\d{1,2},\s+\d{4}\b",
                flags=re.IGNORECASE,
            )
            iso_re = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")

            new_criteria: List[str] = []
            for s in criteria:
                if not isinstance(s, str):
                    new_criteria.append(s)
                    continue
                s2 = month_name_re.sub(date_long, s)
                s2 = iso_re.sub(date_iso, s2)
                new_criteria.append(s2)
            rc["resolution_criteria"] = new_criteria
        contract["resolution_clarity"] = rc

    # contract prompt: keep "within the next 42 days" wording; normalize calendar anchors to resolution date.
    prompt = contract.get("prompt")
    if isinstance(prompt, str):
        prompt = re.sub(
            r"\bby\s+the\s+end\s+of\s+the\s+next\s+(\d+)\s+days\b",
            r"within the next \1 days",
            prompt,
            flags=re.IGNORECASE,
        )
        prompt = re.sub(
            r"\bby\s+the\s+end\s+of\s+"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
            r"\d{4}\b",
            f"by {date_long}",
            prompt,
            flags=re.IGNORECASE,
        )
        prompt = re.sub(
            r"\bbefore\s+the\s+end\s+of\s+"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+"
            r"\d{4}\b",
            f"by {date_long}",
            prompt,
            flags=re.IGNORECASE,
        )
        # Handle quarter anchors like "by the end of Q2 2023".
        prompt = re.sub(
            r"\bby\s+the\s+end\s+of\s+Q[1-4]\s+\d{4}\b",
            f"by {date_long}",
            prompt,
            flags=re.IGNORECASE,
        )
        prompt = re.sub(
            r"\bbefore\s+the\s+end\s+of\s+Q[1-4]\s+\d{4}\b",
            f"by {date_long}",
            prompt,
            flags=re.IGNORECASE,
        )
        prompt = re.sub(
            r"\bbefore\s+the\s+end\s+of\s+\d{4}\b",
            f"by {date_long}",
            prompt,
            flags=re.IGNORECASE,
        )
        # Replace ISO date anchors like "by 2025-05-30".
        prompt = re.sub(
            r"\bby\s+\d{4}-\d{2}-\d{2}\b",
            f"by {date_iso}",
            prompt,
            flags=re.IGNORECASE,
        )

        by_date_re = re.compile(
            r"\bby\s+"
            r"(?:"
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
            r"Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
            r"\s+\d{1,2},\s+\d{4}"
            r"|(?:\d{4}-\d{2}-\d{2})"
            r")\b",
            flags=re.IGNORECASE,
        )
        if by_date_re.search(prompt):
            prompt = by_date_re.sub(f"by {date_long}", prompt)

        contract["prompt"] = prompt

    return contract


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
    ap.add_argument(
        "--scripts-only",
        action="store_true",
        help="Generate written arguments for review without archiving, TTS, or publishing",
    )
    ap.add_argument("--audio-only", action="store_true", help="TTS from last_debate_scripts.json only")
    ap.add_argument("--mark-resolved", metavar="FRIDAY_ISO", help="With --status, update history")
    ap.add_argument("--status", choices=("yes", "no", "void", "pending"), help="Bet resolution for --mark-resolved")
    ap.add_argument("--notes", default="", help="Resolution notes")
    ap.add_argument(
        "--sync-archive",
        action="store_true",
        help="Refresh debate_history audio_href + archive_manifest.json from disk",
    )
    args = ap.parse_args()

    if args.scripts_only and (
        args.audio_only or args.dry_run or args.sync_archive or args.mark_resolved
    ):
        ap.error("--scripts-only cannot be combined with --audio-only, --dry-run, --sync-archive, or --mark-resolved")

    if args.sync_archive:
        save_history(load_history())
        print(f"✓ Synced {ARCHIVE_MANIFEST_PATH.name}")
        return 0

    if args.mark_resolved:
        if not args.status:
            print("Use --status yes|no|void|pending with --mark-resolved")
            return 1
        return cmd_mark_resolved(args.mark_resolved, args.status, args.notes)

    if args.audio_only:
        if not SCRIPTS_STATE.exists():
            print("No last_debate_scripts.json — run full weekly generation first.")
            return 1
        # Best-effort metadata from current contract, if present.
        c = {}
        if CONTRACT_PATH.exists():
            try:
                c = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
            except Exception:
                c = {}
        run_tts(
            friday_iso=(c.get("friday_iso") or ""),
            expected_yes=(c.get("debater_a") or ""),
            expected_no=(c.get("debater_b") or ""),
            prompt=(c.get("prompt") or ""),
        )
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
    if prev_friday == friday and not args.force and not args.scripts_only:
        print(f"Contract already current for {friday}. Use --force to regenerate.")
        return 0

    ai = get_ai_client()
    if not ai:
        print("No LLM client. Configure Moonshot/OpenAI per pipeline.")
        return 1
    kind, client = ai

    overton, insights = load_context_from_db()
    avoid = [w.get("prompt", "") for w in history.get("weeks", []) if w.get("prompt")]
    if prev and prev.get("prompt"):
        avoid.append(prev["prompt"])

    poly = ""
    if fetch_polymarket_debate_context:
        try:
            poly = fetch_polymarket_debate_context()
        except Exception as e:
            poly = f"(Polymarket context failed: {type(e).__name__}: {e})"
    else:
        poly = "(Polymarket module not available.)"

    macro_block, spx_ref, btc_ref = build_macro_reference_block()
    resolves_iso = resolves_iso_from_friday(friday)
    retry_hint = ""
    editorial_contract = load_editorial_contract(friday)
    contract_core: Optional[Dict[str, Any]] = None
    contract_ok = False
    attempts = 1 if editorial_contract else 3
    for attempt in range(attempts):
        if editorial_contract:
            contract_core = dict(editorial_contract)
            print(f"  ✓ Using editorially approved contract for {friday}")
        else:
            contract_core = generate_contract(
                kind,
                client,
                overton,
                insights,
                avoid,
                friday_iso=friday,
                resolves_iso=resolves_iso,
                polymarket_context=poly,
                macro_reference_block=macro_block,
                retry_hint=retry_hint,
            )
            # Deterministic enforcement: generated contracts use friday_iso + 42 days.
            contract_core = _enforce_contract_resolution_dates(contract_core, friday)
        ok_macro, err_macro = validate_prompt_macro_sanity(
            (contract_core.get("prompt") or "").strip(),
            spx_ref,
            btc_ref,
        )
        ok_time, err_time = validate_prompt_temporal_window(
            (contract_core.get("prompt") or "").strip(),
            friday,
            (contract_core.get("resolves_iso") or resolves_iso),
        )
        ok_event, err_event = validate_prompt_event_plausibility(
            (contract_core.get("prompt") or "").strip(),
            friday,
            (contract_core.get("resolves_iso") or resolves_iso),
        )
        ok_repeat, err_repeat = (True, "")
        ok_rc, err_rc = (True, "")
        ok_note, err_note = (True, "")
        ok_spx, err_spx = (True, "")
        if validate_prompt_not_repetitive:
            ok_repeat, err_repeat = validate_prompt_not_repetitive(
                (contract_core.get("prompt") or "").strip(),
                avoid,
            )
        if validate_resolution_clarity:
            ok_rc, err_rc = validate_resolution_clarity(contract_core)
        if validate_editorial_note:
            ok_note, err_note = validate_editorial_note(
                str(contract_core.get("editorial_note") or "")
            )
        if validate_spx_strike_plausible:
            ok_spx, err_spx = validate_spx_strike_plausible(
                (contract_core.get("prompt") or "").strip(),
                spx_ref,
            )
        if ok_macro and ok_time and ok_event and ok_repeat and ok_rc and ok_note and ok_spx:
            contract_ok = True
            break
        errs = [
            e
            for e in (
                err_macro if not ok_macro else "",
                err_time if not ok_time else "",
                err_event if not ok_event else "",
                err_repeat if not ok_repeat else "",
                err_rc if not ok_rc else "",
                err_note if not ok_note else "",
                err_spx if not ok_spx else "",
            )
            if e
        ]
        retry_hint = " | ".join(errs) if errs else "validation failed"
        print(f"  ⚠ Contract validation {attempt + 1}/{attempts} failed: {retry_hint}")

    if not contract_ok or not contract_core:
        source = "Editorial contract" if editorial_contract else "Generated contract"
        print(f"✗ {source} did not pass contract quality checks.")
        return 1

    if args.dry_run:
        print(f"Friday (CST): {friday}")
        print(f"Context terms: {overton[:5]}...")
        print(json.dumps(contract_core, indent=2))
        return 0
    rotation = history["rotation_index"]
    pundits = load_pundits()
    p_a, p_b = pick_debaters(pundits, rotation)
    name_a = (p_a.get("name") or "Debater A").strip()
    name_b = (p_b.get("name") or "Debater B").strip()

    if validate_debaters:
        ok_debaters, err_debaters = validate_debaters(name_a, name_b)
        if not ok_debaters:
            print(f"✗ Debater validation failed: {err_debaters}")
            return 1

    yes_speech, no_speech = generate_speeches(
        kind,
        client,
        contract_core["prompt"],
        contract_core.get("crux_theme") or "",
        name_a,
        name_b,
        _debater_llm_context(p_a),
        _debater_llm_context(p_b),
        build_speech_evidence_context(contract_core),
    )
    validate_speeches(yes_speech, no_speech, name_a, name_b)
    host_s = build_host_script(contract_core["prompt"], name_a, name_b)
    write_scripts_state(
        host_s,
        yes_speech,
        no_speech,
        {
            "generated_at": datetime.now().isoformat(),
            "mode": "scripts_only" if args.scripts_only else "publish",
            "friday_iso": friday,
            "prompt": contract_core["prompt"],
            "crux_theme": contract_core.get("crux_theme") or "",
            "expires_rule": contract_core.get("expires_rule") or "",
            "debater_yes": name_a,
            "debater_no": name_b,
        },
    )
    if args.scripts_only:
        print(f"✓ Wrote review scripts to {SCRIPTS_STATE}")
        print("  No history, audio, contract, or public site files were changed.")
        return 0

    # Archive old week audio into history snapshot before overwriting current MP3.
    history_next = dict(history)
    history_next["weeks"] = list(history.get("weeks", []))
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
            archive_current_week(history_next, arch)

    prompt_hash = hashlib.sha256(contract_core["prompt"].encode("utf-8")).hexdigest()[:16]
    full_public = public_contract(contract_core, friday, name_a, name_b, p_a, p_b)
    full_public["prompt_hash"] = prompt_hash
    if stamp_contract_publishable:
        full_public = stamp_contract_publishable(full_public, avoid, spx_ref=spx_ref, btc_ref=btc_ref)
    elif validate_contract_publishable:
        ok_pub, reason, _ = validate_contract_publishable(full_public, avoid, spx_ref=spx_ref, btc_ref=btc_ref)
        full_public["publishable"] = ok_pub
        full_public["publish_block_reason"] = "" if ok_pub else reason
    if not full_public.get("publishable", True):
        print(f"✗ Contract failed publish quality gate: {full_public.get('publish_block_reason')}")
        return 1
    SITE_AUDIO.mkdir(parents=True, exist_ok=True)

    try:
        audio_meta = run_tts(
            friday_iso=friday,
            expected_yes=name_a,
            expected_no=name_b,
            prompt=contract_core["prompt"],
        )
    except Exception as e:
        print(f"⚠ Audio failed (contract not published): {e}")
        return 1

    validate_contract_audio_match(full_public, audio_meta)
    CONTRACT_PATH.write_text(json.dumps(full_public, indent=2), encoding="utf-8")
    history_next["rotation_index"] = rotation + 1
    save_history(history_next)

    print(f"✓ Week {friday} | {name_a} vs {name_b}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
