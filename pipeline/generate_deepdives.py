#!/usr/bin/env python3
"""
Generate Deep Dive content for insights that don't have it.

This script:
1. Finds all insights without deep_dive_content
2. Retrieves source content (transcript for podcasts, content for newsletters)
3. Uses AI to generate v2 Deep Dives: source_quotes, whats_new, falsification_tracks, investment_implication
4. Validates quote-first evidence, anti-template phrases, and overlap vs the insight card (retries up to 4)
5. Stores in deep_dive_content (legacy column names preserved for export compatibility)

To run manually:
    python3 generate_deepdives.py

To run for specific insights only:
    python3 generate_deepdives.py --insight-ids 19,21,22
"""

import sys
import os
import json
import re
import sqlite3
import argparse
from difflib import SequenceMatcher
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent))

from workspace_paths import DB_PATH, INBOX_DIR, TRANSCRIPT_DIR

# Optional Stage A digest (same markdown file used for Insight + Deep Dive)
def _load_podcast_source_text(transcript_path: Path) -> str:
    from transcript_digest import load_digest_or_raw

    text, is_digest = load_digest_or_raw(transcript_path)
    if is_digest and text:
        print("  ℹ Deep Dive source: using evidence-preserving digest (.digest.md)", flush=True)
    return text

try:
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import google.generativeai as genai

    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False


def _load_dotenv_for_deepdives() -> None:
    """Load repo-root .env so MOONSHOT_API_KEY / GEMINI_API_KEY / OPENAI_API_KEY exist (same idea as auto_pipeline)."""
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k or not v:
                continue
            prev = str(os.environ.get(k, "")).strip()
            if k.endswith("_API_KEY") or k in ("GITHUB_PUSH_TOKEN", "MOONSHOT_API_KEY"):
                if not prev:
                    os.environ[k] = v
            elif k not in os.environ:
                os.environ[k] = v
    except Exception:
        pass


# Reject Deep Dives that mostly paraphrase the insight card (cheap overlap check).
INSIGHT_OVERLAP_REJECT = 0.62
WHATS_NEW_CARD_OVERLAP_REJECT = 0.55
EVIDENCE_CARD_OVERLAP_REJECT = 0.40
IMPL_VS_WHATS_NEW_OVERLAP_REJECT = 0.35
MAX_CANNED_PHRASES = 1
MAX_GENERATION_ATTEMPTS = 4
MAX_DEEP_DIVE_RETRIES = 3
SOURCE_SNIPPET_CHARS = 12000
DEEP_DIVE_SCHEMA_VERSION = 2

CANNED_PHRASES = (
    "unresolved tension",
    "competitive dynamic",
    "allocator-relevant",
    "core logic is that",
    "the core logic",
    "vindicated if",
    "invalidated if",
    "investors should monitor",
    "key differentiator",
    "observable development",
    "policy tradeoff",
)

RECAP_OPENING_RE = re.compile(
    r"^(?:the podcast episode|in this episode|this episode|the guest|the hosts?|"
    r"joon sung park, the guest|in the podcast)\b",
    re.I,
)


def _is_content_filter_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "content_filter" in msg or "high risk" in msg or "content filter" in msg


def ensure_deep_dive_failures_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS deep_dive_generation_failures (
            insight_id INTEGER PRIMARY KEY,
            insight_title TEXT,
            source_type TEXT,
            podcast_episode_id INTEGER,
            failure_reason TEXT,
            failure_detail TEXT,
            last_attempt_at TIMESTAMP,
            retry_count INTEGER DEFAULT 0,
            next_retry_after TIMESTAMP,
            status TEXT DEFAULT 'pending_retry'
        )
        """
    )
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='deep_dive_generation_failures'"
    ).fetchone()
    ddl = (row[0] or "") if row else ""
    if ddl and "'blocked'" not in ddl:
        conn.executescript(
            """
            CREATE TABLE deep_dive_generation_failures_migrated (
                insight_id INTEGER PRIMARY KEY,
                insight_title TEXT,
                source_type TEXT,
                podcast_episode_id INTEGER,
                failure_reason TEXT,
                failure_detail TEXT,
                last_attempt_at TIMESTAMP,
                retry_count INTEGER DEFAULT 0,
                next_retry_after TIMESTAMP,
                status TEXT DEFAULT 'pending_retry'
                    CHECK(status IN ('pending_retry', 'blocked', 'resolved')),
                FOREIGN KEY (insight_id) REFERENCES latest_insights(id) ON DELETE CASCADE
            );
            INSERT INTO deep_dive_generation_failures_migrated
                SELECT * FROM deep_dive_generation_failures;
            DROP TABLE deep_dive_generation_failures;
            ALTER TABLE deep_dive_generation_failures_migrated
                RENAME TO deep_dive_generation_failures;
            """
        )
        conn.commit()


def record_deep_dive_failure(
    conn: sqlite3.Connection,
    insight_id: int,
    title: str,
    source_type: str,
    episode_id: Optional[int],
    reason: str,
    detail: str,
    *,
    block_now: bool = False,
) -> str:
    """Record a failed Deep Dive attempt. Returns final status ('blocked' or 'pending_retry')."""
    ensure_deep_dive_failures_table(conn)
    row = conn.execute(
        "SELECT retry_count, status FROM deep_dive_generation_failures WHERE insight_id = ?",
        (insight_id,),
    ).fetchone()
    retry_count = int((row["retry_count"] if row else 0) or 0) + 1
    status = "blocked" if block_now or retry_count >= MAX_DEEP_DIVE_RETRIES else "pending_retry"
    now = datetime.now().isoformat()
    conn.execute(
        """
        INSERT INTO deep_dive_generation_failures (
            insight_id, insight_title, source_type, podcast_episode_id,
            failure_reason, failure_detail, last_attempt_at, retry_count, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(insight_id) DO UPDATE SET
            insight_title = excluded.insight_title,
            source_type = excluded.source_type,
            podcast_episode_id = excluded.podcast_episode_id,
            failure_reason = excluded.failure_reason,
            failure_detail = excluded.failure_detail,
            last_attempt_at = excluded.last_attempt_at,
            retry_count = excluded.retry_count,
            status = excluded.status
        """,
        (insight_id, title, source_type, episode_id, reason, detail[:2000], now, retry_count, status),
    )
    conn.commit()
    return status


def mark_deep_dive_failure_resolved(conn: sqlite3.Connection, insight_id: int) -> None:
    ensure_deep_dive_failures_table(conn)
    conn.execute(
        """
        UPDATE deep_dive_generation_failures
        SET status = 'resolved',
            failure_detail = 'Deep Dive generated successfully.',
            last_attempt_at = ?
        WHERE insight_id = ?
        """,
        (datetime.now().isoformat(), insight_id),
    )
    conn.commit()


def ensure_deep_dive_schema(conn: sqlite3.Connection) -> None:
    """Add optional deep_dive_content columns if missing (SQLite)."""
    cur = conn.execute("PRAGMA table_info(deep_dive_content)")
    existing = {row[1] for row in cur.fetchall()}
    if "episode_evidence" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN episode_evidence TEXT")
    if "falsification_tracks" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN falsification_tracks TEXT")
    if "schema_version" not in existing:
        conn.execute(
            "ALTER TABLE deep_dive_content ADD COLUMN schema_version INTEGER DEFAULT 1"
        )
    conn.commit()


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _pack_repeat_prone(content: Dict[str, Any]) -> str:
    parts: List[str] = [
        str(content.get("overview") or ""),
        str(content.get("investment_thesis") or ""),
    ]
    if int(content.get("schema_version") or 1) < DEEP_DIVE_SCHEMA_VERSION:
        kt = content.get("key_takeaways_detailed") or []
        if isinstance(kt, list):
            parts.extend(str(x) for x in kt[:4])
    return "\n".join(parts)


def count_canned_phrases(text: str) -> int:
    tl = _norm_text(text)
    return sum(1 for phrase in CANNED_PHRASES if phrase in tl)


def strip_recap_opening(text: str) -> str:
    """Drop leading episode-summary sentences; keep quote-first evidence."""
    lines = (text or "").splitlines()
    kept: List[str] = []
    skipped_opening = False
    for line in lines:
        s = line.strip()
        if not s:
            if kept:
                kept.append("")
            continue
        if (
            not skipped_opening
            and RECAP_OPENING_RE.match(s)
            and not s.startswith(("-", "•", '"', "'", "“"))
            and "Host:" not in s
            and "Guest:" not in s
        ):
            skipped_opening = True
            continue
        kept.append(line.rstrip())
    cleaned = "\n".join(kept).strip()
    return cleaned or (text or "").strip()


def evidence_vs_card_overlap(summary: str, key_takeaway: str, evidence: str) -> float:
    baseline = _norm_text(f"{summary or ''}\n{key_takeaway or ''}")
    ev = _norm_text(evidence or "")
    if len(baseline) < 40 or len(ev) < 40:
        return 0.0
    return SequenceMatcher(None, baseline, ev).ratio()


def section_overlap(a: str, b: str) -> float:
    na, nb = _norm_text(a), _norm_text(b)
    if len(na) < 40 or len(nb) < 40:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def normalize_from_ai_response(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Map v2 LLM JSON to internal storage fields (legacy keys kept for export/UI)."""
    if not any(k in raw for k in ("source_quotes", "whats_new", "investment_implication")):
        return {**raw, "schema_version": int(raw.get("schema_version") or 1)}

    impl = raw.get("investment_implication") or {}
    if isinstance(impl, str):
        impl = {"prose": impl, "tickers": {}, "watch_items": []}

    tickers_raw = impl.get("tickers") or {}
    ticker_analysis: Dict[str, Any] = {}
    if isinstance(tickers_raw, dict):
        for sym, val in tickers_raw.items():
            if isinstance(val, str):
                ticker_analysis[str(sym)] = {"rationale": val.strip(), "positioning": "", "risk": ""}
            elif isinstance(val, dict):
                ticker_analysis[str(sym)] = {
                    "rationale": (val.get("rationale") or val.get("why") or "").strip(),
                    "positioning": (val.get("positioning") or "").strip(),
                    "risk": (val.get("risk") or "").strip(),
                }

    watch = impl.get("watch_items") or []
    if not isinstance(watch, list):
        watch = []

    source_quotes = strip_recap_opening(_episode_evidence_text(raw.get("source_quotes")))

    return {
        "schema_version": DEEP_DIVE_SCHEMA_VERSION,
        "episode_evidence": source_quotes,
        "overview": str(raw.get("whats_new") or "").strip(),
        "investment_thesis": str(impl.get("prose") or "").strip(),
        "ticker_analysis": ticker_analysis,
        "falsification_tracks": raw.get("falsification_tracks") or [],
        "key_takeaways_detailed": [],
        "contrarian_signals": [],
        "catalysts": [str(x).strip() for x in watch if str(x).strip()],
    }


def insight_body_overlap_ratio(summary: str, key_takeaway: str, content: Dict[str, Any]) -> float:
    """How similar the 'main' Deep Dive prose is to the insight card (higher = more repetitive)."""
    baseline = _norm_text(f"{summary or ''}\n{key_takeaway or ''}")
    packed = _norm_text(_pack_repeat_prone(content))
    if len(baseline) < 40 or len(packed) < 80:
        return 0.0
    return SequenceMatcher(None, baseline, packed).ratio()


def overview_vs_card_overlap(summary: str, key_takeaway: str, overview: str) -> float:
    """Similarity between overview only and Insight card baseline (cheap anti-parrot check)."""
    baseline = _norm_text(f"{summary or ''}\n{key_takeaway or ''}")
    ov = _norm_text(overview or "")
    if len(baseline) < 40 or len(ov) < 80:
        return 0.0
    return SequenceMatcher(None, baseline, ov).ratio()


def _episode_evidence_text(ev_raw: Any) -> str:
    """Normalize episode_evidence payloads (string/list/dict) to storable text."""
    if isinstance(ev_raw, list):
        return "\n".join(str(x).strip() for x in ev_raw if str(x).strip())
    if isinstance(ev_raw, dict):
        return "\n".join(
            f"{k}: {str(v).strip()}" for k, v in ev_raw.items() if str(v).strip()
        )
    return str(ev_raw or "").strip()


def overview_vs_card_overlap(summary: str, key_takeaway: str, overview: str) -> float:
    """Similarity between whats_new/overview and the insight card."""
    return evidence_vs_card_overlap(summary, key_takeaway, overview)


def deep_dive_structural_ok(content: Dict[str, Any]) -> Tuple[bool, str]:
    """Require quote-first evidence, whats_new, falsifiers, and investment implication."""
    ev = _episode_evidence_text(content.get("episode_evidence"))
    if len(ev) < 80:
        return False, "source_quotes too short or missing"
    quote_like = sum(ev.count(q) for q in ('"', "'", "“", "”", "‘", "’"))
    lines = [ln.strip() for ln in ev.splitlines() if ln.strip()]
    quote_first_lines = sum(
        1
        for ln in lines
        if ln.startswith(("-", "•", '"', "'", "“", "Host:", "Guest:", "Author:"))
    )
    if quote_like < 2 and quote_first_lines < 2:
        return False, "source_quotes must be quote-first (bullets or quoted lines)"
    if lines and RECAP_OPENING_RE.match(lines[0]) and quote_like < 1:
        return False, "source_quotes must not open with episode summary prose"

    whats_new = str(content.get("overview") or "").strip()
    if len(whats_new) < 60:
        return False, "whats_new too short or missing"

    thesis = str(content.get("investment_thesis") or "").strip()
    if len(thesis) < 40:
        return False, "investment_implication prose too short or missing"

    ft = content.get("falsification_tracks")
    if not isinstance(ft, list) or len(ft) < 2:
        return False, "falsification_tracks must be a list with at least 2 items"
    good = [str(x).strip() for x in ft if len(str(x).strip()) >= 25]
    if len(good) < 2:
        return False, "falsification_tracks items too short"
    return True, ""


def sanitize_ticker_analysis(ticker_analysis: dict) -> dict:
    """Remove placeholder keys (TICKER1, Ticker2, etc.) so only real symbols are stored."""
    if not ticker_analysis or not isinstance(ticker_analysis, dict):
        return ticker_analysis or {}
    placeholder_pattern = re.compile(r"^TICKER\d+$", re.IGNORECASE)
    # Real tickers are typically 1-5 uppercase letters (e.g. AAPL, NVDA, SPY, BRK.A)
    valid_pattern = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
    return {
        k: v for k, v in ticker_analysis.items()
        if not placeholder_pattern.match(k) and valid_pattern.match(k.strip())
    }


def get_db_connection():
    """Get database connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def get_ai_clients() -> List[Tuple[str, Any]]:
    """Return all configured AI clients in priority order for Deep Dive generation."""
    _load_dotenv_for_deepdives()
    clients: List[Tuple[str, Any]] = []
    seen: set[str] = set()

    def _add(client_type: str, client: Any) -> None:
        if client_type not in seen:
            clients.append((client_type, client))
            seen.add(client_type)

    if not OPENAI_AVAILABLE:
        print("  ✗ openai package not installed (pip install openai)", flush=True)
        return clients

    from workspace_paths import agent_auth_profiles_path

    auth_profiles_path = agent_auth_profiles_path()
    if auth_profiles_path and auth_profiles_path.exists():
        try:
            with open(auth_profiles_path) as f:
                auth_data = json.load(f)
            profiles = auth_data.get("profiles", {})
            if "moonshot:default" in profiles:
                profile = profiles["moonshot:default"]
                if profile.get("type") == "api_key":
                    kimi_key = (profile.get("key") or "").strip()
                    if kimi_key:
                        client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
                        print("  Using Moonshot/Kimi API (auth profiles)", flush=True)
                        _add("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot (profiles) init failed: {e}", flush=True)

    kimi_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if kimi_key:
        try:
            client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
            print("  Using Moonshot/Kimi API (MOONSHOT_API_KEY)", flush=True)
            _add("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot env init failed: {e}", flush=True)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            print("  Using OpenAI API", flush=True)
            _add("openai", client)
        except Exception as e:
            print(f"  ⚠ OpenAI init failed: {e}", flush=True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key and GEMINI_AVAILABLE:
        try:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API", flush=True)
            _add("gemini", None)
        except Exception as e:
            print(f"  ⚠ Gemini init failed: {e}", flush=True)

    if not clients:
        print(
            "  ✗ No AI client: set MOONSHOT_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in .env "
            "(or Moonshot in Cursor auth profiles).",
            flush=True,
        )
    return clients


def get_ai_client():
    """Single client for backward compatibility."""
    clients = get_ai_clients()
    return clients[0] if clients else None


def get_source_content(insight_id: int, source_type: str, episode_id: int = None) -> str:
    """Get the source content for an insight."""
    conn = get_db_connection()
    
    if source_type == 'podcast' and episode_id:
        # Get transcript content
        c = conn.execute(
            "SELECT transcript_path FROM podcast_episodes WHERE id=?",
            (episode_id,)
        )
        row = c.fetchone()
        if row and row['transcript_path']:
            transcript_path = Path(row['transcript_path'])
            # Resolve relative paths against pipeline dir (e.g. "transcripts/foo.txt")
            if not transcript_path.is_absolute():
                transcript_path = Path(__file__).parent / transcript_path
            if transcript_path.exists():
                return _load_podcast_source_text(transcript_path)
    
    elif source_type == 'newsletter':
        # Get from inbox JSON - match by title (which corresponds to email subject)
        c = conn.execute(
            "SELECT title FROM latest_insights WHERE id=?",
            (insight_id,)
        )
        row = c.fetchone()
        if row:
            # Find matching inbox file
            title = row['title']
            for json_file in INBOX_DIR.glob("*.json"):
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                    # Match by subject field in the JSON
                    json_subject = data.get('subject', '')
                    if json_subject == title or title in json_subject or json_subject in title:
                        return data.get('content', data.get('content_preview', ''))
                except Exception:
                    pass
    
    # Fallback: use summary from insight
    c = conn.execute(
        "SELECT summary, key_takeaway FROM latest_insights WHERE id=?",
        (insight_id,)
    )
    row = c.fetchone()
    conn.close()
    
    if row:
        return f"{row['summary']}\n\nKey Takeaway: {row['key_takeaway']}"
    
    return ""


def _call_json_model(clients: List[Tuple[str, Any]], prompt: str) -> Tuple[Optional[dict], Optional[str]]:
    """Try each configured provider; return (parsed_json, last_error_detail)."""
    last_error = ""
    content_filter_hit = False
    for client_type, client in clients:
        try:
            if client_type == "moonshot":
                resp = client.chat.completions.create(
                    model="moonshot-v1-8k",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=3200,
                )
                return json.loads(resp.choices[0].message.content), None

            if client_type == "openai":
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    max_tokens=3200,
                )
                return json.loads(resp.choices[0].message.content), None

            if client_type == "gemini":
                import google.generativeai as genai

                model = genai.GenerativeModel("gemini-1.5-flash")
                resp = model.generate_content(prompt)
                return json.loads(resp.text), None
        except Exception as e:
            last_error = str(e)
            if _is_content_filter_error(e):
                content_filter_hit = True
                print(f"    ⚠ {client_type} content filter — trying next provider", flush=True)
            else:
                print(f"    ✗ {client_type} failed: {e}", flush=True)
            continue
    if content_filter_hit:
        return None, "content_filter: blocked by provider safety filter"
    return None, last_error or "all providers failed"


def generate_deep_dive_with_ai(
    clients: List[Tuple[str, Any]],
    title: str,
    source_content: str,
    source_type: str,
    insight_summary: str,
    key_takeaway: str,
    retry_hint: str = "",
) -> Tuple[Optional[dict], Optional[str]]:
    """Generate deep dive content using AI (high-ROI: source evidence + falsifiers + anti-paraphrase)."""

    src = source_content[:SOURCE_SNIPPET_CHARS]
    label = "Podcast / transcript" if source_type == "podcast" else "Newsletter / source body"

    retry_block = ""
    if retry_hint.strip():
        retry_block = f"\n\nVALIDATION RETRY — fix the following and keep valid JSON only:\n{retry_hint}\n"

    prompt = f"""You are an elite investment analyst writing a "Deep Dive" that MUST add depth beyond the insight card — not a longer restatement of it.

ALREADY-PUBLISHED INSIGHT CARD (treat this as ALREADY SHOWN TO THE USER; do not paraphrase it or replay its thematic bullets):
Summary: {insight_summary or "(none)"}
Key takeaway: {key_takeaway or "(none)"}

{label.upper()}:
{src}

INSIGHT TITLE: {title}

Return ONLY valid JSON with these keys:

{{
  "source_quotes": "Quote-first evidence ONLY. Each line must start with - or a quotation mark or Host:/Guest:/Author:. Include at least TWO short verbatim quotes from the source. NO opening sentence summarizing the episode (forbidden: 'The podcast episode…', 'In this episode…', 'The guest discusses…').",
  "whats_new": "ONE paragraph (80–180 words): mechanisms, numbers, disagreements, or second-order effects that are NOT already on the Insight card. Plain language. If a sentence could appear on 50 unrelated podcast Deep Dives, delete it.",
  "falsification_tracks": [
    "3–5 bullets: specific, observable data, events, or market outcomes that would materially REDUCE conviction in the thesis (or flip it). Each bullet must be testable — not vibes."
  ],
  "investment_implication": {{
    "prose": "2–4 sentences: if the thesis is directionally true, what follows for allocators — include timeframe and what would prove/disprove it. No bullet list.",
    "tickers": {{
      "NVDA": "One sentence: why this ticker is the cleanest expression of the idea (only REAL tickers explicitly relevant in the source; 0–4 tickers)."
    }},
    "watch_items": ["0–3 optional dated milestones — only if NOT already covered in falsification_tracks"]
  }}
}}

Hard rules:
- Do NOT use these phrases anywhere: unresolved tension, competitive dynamic, allocator-relevant, core logic is that, vindicated, invalidated, investors should monitor, key differentiator, observable development, policy tradeoff.
- source_quotes MUST cite the SOURCE MATERIAL; do not invent quotes.
- whats_new + investment_implication.prose must NOT read like a light edit of the Insight card.
- ticker keys: REAL symbols only (never TICKER1, placeholders).
- English only.
{retry_block}"""

    raw, err = _call_json_model(clients, prompt)
    if raw:
        return normalize_from_ai_response(raw), err
    return None, err


def store_deep_dive(insight_id: int, episode_id: int, content: dict) -> bool:
    """Store deep dive content in database."""
    conn = get_db_connection()

    try:
        ensure_deep_dive_schema(conn)
        # Sanitize ticker_analysis: drop placeholder keys (TICKER1, Ticker2, etc.)
        raw_tickers = content.get('ticker_analysis') or {}
        ticker_analysis = sanitize_ticker_analysis(raw_tickers)
        if len(ticker_analysis) < len(raw_tickers):
            # Avoid overwriting with empty if AI returned only placeholders
            content = {**content, 'ticker_analysis': ticker_analysis}

        conn.execute(
            """
            INSERT INTO deep_dive_content (
                insight_id, podcast_episode_id, overview, key_takeaways_detailed,
                investment_thesis, ticker_analysis, positioning_guidance,
                risk_factors, contrarian_signals, catalysts,
                episode_evidence, falsification_tracks, schema_version, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                insight_id,
                episode_id,
                content.get("overview", ""),
                json.dumps(content.get("key_takeaways_detailed", [])),
                content.get("investment_thesis", ""),
                json.dumps(content.get("ticker_analysis", {})),
                "",
                json.dumps([]),
                json.dumps(content.get("contrarian_signals", [])),
                json.dumps(content.get("catalysts", [])),
                _episode_evidence_text(content.get("episode_evidence")),
                json.dumps(content.get("falsification_tracks", [])),
                int(content.get("schema_version") or DEEP_DIVE_SCHEMA_VERSION),
                datetime.now().isoformat(),
            ),
        )
        # If latest_insights.tickers_mentioned is empty, backfill it from ticker_analysis keys
        try:
            tickers = list((content.get('ticker_analysis') or {}).keys())
            if tickers:
                cur = conn.execute(
                    "SELECT tickers_mentioned FROM latest_insights WHERE id = ?",
                    (insight_id,)
                )
                row = cur.fetchone()
                current = row[0] if row else None
                if not current or current in ("", "[]"):
                    conn.execute(
                        "UPDATE latest_insights SET tickers_mentioned = ? WHERE id = ?",
                        (json.dumps(tickers), insight_id)
                    )
        except Exception as e:
            print(f"    ⚠ Could not backfill tickers_mentioned from deep dive: {e}")

        conn.commit()
        return True
    except Exception as e:
        print(f"    ✗ Database insert failed: {e}")
        return False
    finally:
        conn.close()


def clean_placeholder_tickers_in_db():
    """One-time fix: remove TICKER1/Ticker2-style keys from deep_dive_content and latest_insights."""
    conn = get_db_connection()
    updated_ddc = 0
    updated_li = 0
    try:
        cursor = conn.execute(
            "SELECT id, insight_id, ticker_analysis FROM deep_dive_content WHERE ticker_analysis != '' AND ticker_analysis IS NOT NULL"
        )
        for row in cursor:
            try:
                data = json.loads(row['ticker_analysis'])
            except (json.JSONDecodeError, TypeError):
                continue
            cleaned = sanitize_ticker_analysis(data)
            if len(cleaned) != len(data):
                conn.execute(
                    "UPDATE deep_dive_content SET ticker_analysis = ? WHERE id = ?",
                    (json.dumps(cleaned), row['id'])
                )
                updated_ddc += 1
                # Update latest_insights.tickers_mentioned for this insight if it had placeholders
                cur = conn.execute(
                    "SELECT tickers_mentioned FROM latest_insights WHERE id = ?",
                    (row['insight_id'],)
                )
                li_row = cur.fetchone()
                if li_row and li_row['tickers_mentioned']:
                    try:
                        mentioned = json.loads(li_row['tickers_mentioned'])
                        if mentioned and any(re.match(r"^TICKER\d+$", str(t), re.IGNORECASE) for t in mentioned):
                            new_mentioned = [t for t in mentioned if not re.match(r"^TICKER\d+$", str(t), re.IGNORECASE)]
                            conn.execute(
                                "UPDATE latest_insights SET tickers_mentioned = ? WHERE id = ?",
                                (json.dumps(new_mentioned), row['insight_id'])
                            )
                            updated_li += 1
                    except (json.JSONDecodeError, TypeError):
                        pass
        conn.commit()
        print(f"Cleaned placeholder tickers: {updated_ddc} deep_dive_content rows, {updated_li} latest_insights rows.", flush=True)
    finally:
        conn.close()
    return updated_ddc + updated_li


def run_deep_dive_generation_attempts(
    clients: List[Tuple[str, Any]],
    insight_id: int,
    title: str,
    source_type: str,
    episode_id: int,
    insight_summary: str,
    key_takeaway: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Generate with retries when overlap or structural checks fail."""
    source_content = get_source_content(insight_id, source_type, episode_id)
    if not source_content:
        return None, "missing source content"

    retry_hint = ""
    last_error = ""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        content, err = generate_deep_dive_with_ai(
            clients,
            title,
            source_content,
            source_type,
            insight_summary,
            key_takeaway,
            retry_hint=retry_hint,
        )
        if err:
            last_error = err
        if not content:
            if err and _is_content_filter_error(Exception(err)):
                return None, err
            continue

        evidence = _episode_evidence_text(content.get("episode_evidence"))
        whats_new = str(content.get("overview") or "")
        thesis = str(content.get("investment_thesis") or "")

        overlap = insight_body_overlap_ratio(insight_summary, key_takeaway, content)
        wn_sim = overview_vs_card_overlap(insight_summary, key_takeaway, whats_new)
        ev_sim = evidence_vs_card_overlap(insight_summary, key_takeaway, evidence)
        impl_sim = section_overlap(whats_new, thesis)
        canned = count_canned_phrases("\n".join([whats_new, thesis, evidence]))
        ok_struct, struct_reason = deep_dive_structural_ok(content)

        validation_errors: List[str] = []
        if overlap > INSIGHT_OVERLAP_REJECT:
            validation_errors.append(
                f"Aggregate Deep Dive prose is too similar to the insight card (overlap {overlap:.2f})."
            )
        if wn_sim > WHATS_NEW_CARD_OVERLAP_REJECT:
            validation_errors.append(
                f"whats_new is too similar to the insight card (overlap {wn_sim:.2f})."
            )
        if ev_sim > EVIDENCE_CARD_OVERLAP_REJECT:
            validation_errors.append(
                f"source_quotes recap the insight card (overlap {ev_sim:.2f}). Start with quotes, not summary."
            )
        if impl_sim > IMPL_VS_WHATS_NEW_OVERLAP_REJECT:
            validation_errors.append(
                f"investment_implication repeats whats_new (overlap {impl_sim:.2f})."
            )
        if canned > MAX_CANNED_PHRASES:
            validation_errors.append(
                f"Too many template phrases ({canned}); rewrite in plain language."
            )
        if not ok_struct:
            validation_errors.append(f"Structural check failed: {struct_reason}.")

        if validation_errors:
            retry_hint = " ".join(validation_errors) + (
                " Rewrite whats_new with fresh mechanisms/numbers not on the Insight card. "
                "Rewrite source_quotes as quote-first bullets with no episode intro. "
                "Keep investment_implication distinct and concise."
            )
            print(
                f"    ⚠ Attempt {attempt}: "
                + "; ".join(validation_errors[:3]),
                flush=True,
            )
            if attempt >= MAX_GENERATION_ATTEMPTS:
                print(
                    f"    ✗ Giving up after {MAX_GENERATION_ATTEMPTS} attempts (validation failed)",
                    flush=True,
                )
                return None, validation_errors[0]
            continue

        if attempt > 1:
            print(
                f"    ✓ Passed validation on attempt {attempt} "
                f"(card overlap {overlap:.2f}, evidence {ev_sim:.2f}, canned {canned})",
                flush=True,
            )
        return content, None

    return None, last_error or "generation failed after retries"


def generate_missing_deepdives(insight_ids: list = None) -> Tuple[int, int, int]:
    """Generate deep dives for insights that don't have them.

    Returns (generated_count, attempted_count, quarantined_count).
    attempted_count excludes insights already blocked from retry.
    """

    # Force unbuffered output for real-time logging
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    conn = get_db_connection()
    ensure_deep_dive_failures_table(conn)

    blocked_clause = """
        AND NOT EXISTS (
            SELECT 1 FROM deep_dive_generation_failures dgf
            WHERE dgf.insight_id = li.id AND dgf.status = 'blocked'
        )
    """

    if insight_ids:
        # Specific insights requested (manual retry — include blocked)
        placeholders = ",".join("?" * len(insight_ids))
        cursor = conn.execute(
            f"""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            LEFT JOIN deep_dive_content ddc ON li.id = ddc.insight_id
            WHERE li.id IN ({placeholders}) AND ddc.id IS NULL
        """,
            insight_ids,
        )
    else:
        cursor = conn.execute(
            f"""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            LEFT JOIN deep_dive_content ddc ON li.id = ddc.insight_id
            WHERE ddc.id IS NULL
            {blocked_clause}
        """
        )

    insights = cursor.fetchall()

    if not insights:
        conn.close()
        print("No insights need Deep Dives!", flush=True)
        return 0, 0, 0

    need = len(insights)
    print(f"Generating Deep Dives for {need} insights...\n", flush=True)

    clients = get_ai_clients()
    if not clients:
        conn.close()
        return 0, need, 0

    generated = 0
    quarantined = 0

    for row in insights:
        insight_id = row['id']
        title = row['title']
        source_type = row['source_type']
        episode_id = row['podcast_episode_id']
        insight_summary = row["summary"] or ""
        key_takeaway = row["key_takeaway"] or ""

        print(f"[{insight_id}] {title[:60]}", flush=True)

        content, err_detail = run_deep_dive_generation_attempts(
            clients,
            insight_id,
            title,
            source_type,
            episode_id,
            insight_summary,
            key_takeaway,
        )
        if not content:
            reason = "content_filter" if err_detail and _is_content_filter_error(Exception(err_detail)) else "generation_failed"
            status = record_deep_dive_failure(
                conn,
                insight_id,
                title,
                source_type,
                episode_id,
                reason,
                err_detail or "unknown error",
                block_now=(reason == "content_filter"),
            )
            print(f"  ✗ Generation failed or rejected ({status})", flush=True)
            if status == "blocked":
                quarantined += 1
            continue

        if store_deep_dive(insight_id, episode_id, content):
            mark_deep_dive_failure_resolved(conn, insight_id)
            print(f"  ✓ Deep Dive stored", flush=True)
            generated += 1
        else:
            record_deep_dive_failure(
                conn,
                insight_id,
                title,
                source_type,
                episode_id,
                "storage_failed",
                "store_deep_dive returned false",
            )
            print(f"  ✗ Storage failed", flush=True)

    conn.close()
    print(f"\n✓ Generated {generated}/{need} Deep Dives", flush=True)
    if quarantined:
        print(f"  ⏭ Quarantined {quarantined} insight(s) — site publish will continue without them on main", flush=True)
    return generated, need, quarantined


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Generate Deep Dive content for insights')
    parser.add_argument('--insight-ids', type=str, help='Comma-separated insight IDs (only those missing Deep Dives)')
    parser.add_argument(
        '--force-ids',
        type=str,
        help='Comma-separated insight IDs: delete existing Deep Dive row(s) then regenerate',
    )
    parser.add_argument('--fix-placeholder-tickers', action='store_true', help='One-time: remove TICKER1/Ticker2 etc. from existing DB rows')
    args = parser.parse_args()
    
    if args.fix_placeholder_tickers:
        clean_placeholder_tickers_in_db()
        sys.exit(0)

    insight_ids = None
    if args.force_ids:
        raw = [int(x.strip()) for x in args.force_ids.split(',') if x.strip()]
        if not raw:
            print('No IDs in --force-ids', flush=True)
            sys.exit(1)
        conn = get_db_connection()
        ensure_deep_dive_schema(conn)
        ph = ','.join('?' * len(raw))
        conn.execute(f'DELETE FROM deep_dive_content WHERE insight_id IN ({ph})', raw)
        conn.commit()
        conn.close()
        print(f'Removed Deep Dive row(s) for insight_id(s): {raw}', flush=True)
        insight_ids = raw
    elif args.insight_ids:
        insight_ids = [int(x.strip()) for x in args.insight_ids.split(',')]

    gen, need, quarantined = generate_missing_deepdives(insight_ids)
    # Fail only when no AI client was available. Otherwise publish proceeds with
    # insights that already have Deep Dives; blocked insights stay off main.
    if need > 0 and gen == 0 and quarantined == 0:
        clients = get_ai_clients()
        if not clients:
            print("✗ Deep Dive step failed: no AI client configured.", flush=True)
            sys.exit(1)
        print(
            "⚠ Deep Dive step: no new dives generated; failures recorded for retry. "
            "Site export may continue.",
            flush=True,
        )
    sys.exit(0)
