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
    """Raw transcript. Stage A digests are too short to support named quotes."""
    try:
        return transcript_path.read_text(encoding="utf-8", errors="ignore")
    except Exception as exc:
        print(f"  Could not read transcript {transcript_path}: {exc}", flush=True)
        return ""

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
SOURCE_SNIPPET_CHARS = 100_000  # same window as analyze_transcript / transcript_window.py
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
    # Cost tracking columns (added for PR #xxx)
    if "model_used" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN model_used TEXT")
    if "input_tokens" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN input_tokens INTEGER")
    if "output_tokens" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN output_tokens INTEGER")
    if "cost_usd" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN cost_usd REAL")
    if "attempt_count" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN attempt_count INTEGER")
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


QUARTER_TO_MONTH = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}
CATALYST_QUARTER_YEAR_RE = re.compile(r"\b(Q[1-4])\s*(20\d{2})\b", re.IGNORECASE)
CATALYST_H_YEAR_RE = re.compile(r"\b(H[12])\s*(20\d{2})\b", re.IGNORECASE)
CATALYST_YEAR_PREFIX_RE = re.compile(r"^\s*(\d{4}):")
CATALYST_LATE_YEAR_RE = re.compile(r"\b(Late|End of|end-of-year)\s+(20\d{2})\b", re.IGNORECASE)
CATALYST_MID_YEAR_RE = re.compile(r"\bmid[- ]?(20\d{2})\b", re.IGNORECASE)
CATALYST_EARLY_YEAR_RE = re.compile(r"\b(early|beginning of)\s+(20\d{2})\b", re.IGNORECASE)


def _extract_catalyst_target_date(catalyst: str) -> Optional[Tuple[int, int]]:
    """Extract (year, month) from a catalyst string. Returns None if no date found."""
    qy = CATALYST_QUARTER_YEAR_RE.search(catalyst)
    if qy:
        quarter = qy.group(1).upper()
        year = int(qy.group(2))
        return (year, QUARTER_TO_MONTH[quarter])

    hy = CATALYST_H_YEAR_RE.search(catalyst)
    if hy:
        half = hy.group(1).upper()
        year = int(hy.group(2))
        return (year, 6 if half == "H1" else 12)

    standalone_year = CATALYST_YEAR_PREFIX_RE.match(catalyst)
    if standalone_year:
        return (int(standalone_year.group(1)), 12)

    late_year = CATALYST_LATE_YEAR_RE.search(catalyst)
    if late_year:
        return (int(late_year.group(2)), 12)

    mid_year = CATALYST_MID_YEAR_RE.search(catalyst)
    if mid_year:
        return (int(mid_year.group(1)), 6)

    early_year = CATALYST_EARLY_YEAR_RE.search(catalyst)
    if early_year:
        return (int(early_year.group(2)), 3)

    return None


def filter_stale_catalysts(catalysts: List[str], episode_date: Optional[str]) -> List[str]:
    """Remove catalyst items whose target date is clearly before the episode date."""
    if not episode_date or not catalysts:
        return catalysts

    try:
        ep_year = int(episode_date[:4])
        ep_month = int(episode_date[5:7])
    except (ValueError, IndexError):
        return catalysts

    def is_stale(catalyst: str) -> bool:
        target = _extract_catalyst_target_date(catalyst)
        if not target:
            return False
        target_year, target_month = target
        if target_year < ep_year:
            return True
        if target_year == ep_year and target_month < ep_month:
            return True
        return False

    clean = [c for c in catalysts if not is_stale(c)]
    removed = len(catalysts) - len(clean)
    if removed > 0:
        print(f"    ⚠ Filtered {removed} stale catalyst(s) with dates before episode date", flush=True)
    return clean


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
    # Match speaker names like "J Mintzmyer:", "Jack Farley:", allowing single-letter first names
    named = re.findall(
        r"(?:^|\n)\s*[-•]?\s*([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]+)+)\s*:",
        ev,
    )
    named = [n for n in named if n.lower() not in {"host", "guest", "author", "speaker"}]
    if len(named) < 2:
        return False, "source_quotes need at least two lines that name the speaker (Full Name: \"quote\")"
    if lines and RECAP_OPENING_RE.match(lines[0]) and quote_like < 1:
        return False, "source_quotes must not open with episode summary prose"

    whats_new = str(content.get("overview") or "").strip()
    if len(whats_new) < 60:
        return False, "whats_new too short or missing"

    thesis = str(content.get("investment_thesis") or "").strip()
    if len(thesis) < 40:
        return False, "investment_implication prose too short or missing"
    if "investors should" in (ev + " " + whats_new + " " + thesis).lower():
        return False, "contains Investors should"

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
    """Configured clients for Deep Dives. OpenAI first. Moonshot/Kimi is never called."""
    _load_dotenv_for_deepdives()
    clients: List[Tuple[str, Any]] = []
    seen: set[str] = set()

    def _add(client_type: str, client: Any) -> None:
        if client_type not in seen:
            clients.append((client_type, client))
            seen.add(client_type)

    if not OPENAI_AVAILABLE:
        print("  openai package not installed (pip install openai)", flush=True)
        return clients

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            print("  Using OpenAI API", flush=True)
            _add("openai", client)
        except Exception as e:
            print(f"  OpenAI init failed: {e}", flush=True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key and GEMINI_AVAILABLE:
        try:
            from analyze_transcript import resolve_llm_model
            gemini_model = resolve_llm_model("gemini")
            if "flash" in gemini_model.lower():
                print(f"  Skipping Gemini {gemini_model} (Flash is not used for deep dives).", flush=True)
            else:
                genai.configure(api_key=gemini_key)
                print("  Using Gemini API", flush=True)
                _add("gemini", None)
        except Exception as e:
            print(f"  Gemini init failed: {e}", flush=True)

    print("  Moonshot/Kimi skipped (suspended; not called).", flush=True)
    if not clients:
        print("  No AI client: set OPENAI_API_KEY.", flush=True)
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


def _call_json_model(clients: List[Tuple[str, Any]], prompt: str) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
    """Try each configured provider; return (parsed_json, last_error_detail, usage_info).
    
    usage_info dict has keys: model, input_tokens, output_tokens, cost_usd
    """
    from analyze_transcript import resolve_llm_model
    last_error = ""
    content_filter_hit = False
    from transcript_window import openai_chat_kwargs
    for client_type, client in clients:
        try:
            if client_type == "moonshot":
                print("    Skipping Moonshot/Kimi (not called).", flush=True)
                continue

            if client_type == "openai":
                model = resolve_llm_model("openai")
                print(f"    OpenAI model: {model}", flush=True)
                resp = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    response_format={"type": "json_object"},
                    **openai_chat_kwargs(model, 6000),
                )
                raw = resp.choices[0].message.content
                if not raw or not str(raw).strip():
                    raise ValueError(f"OpenAI returned empty content (model={model})")
                
                # Extract usage info
                usage = resp.usage
                input_tokens = usage.prompt_tokens if usage else 0
                output_tokens = usage.completion_tokens if usage else 0
                # gpt-5.5 pricing: $5/M input, $30/M output
                cost_usd = (input_tokens / 1_000_000 * 5.0) + (output_tokens / 1_000_000 * 30.0)
                usage_info = {
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "cost_usd": cost_usd,
                }
                print(f"    Deep dive tokens: {input_tokens:,} in / {output_tokens:,} out, cost=${cost_usd:.4f}", flush=True)
                return json.loads(raw), None, usage_info

            if client_type == "gemini":
                import google.generativeai as genai

                model = genai.GenerativeModel(resolve_llm_model("gemini"))
                resp = model.generate_content(prompt)
                # Gemini doesn't provide detailed usage in the same way
                return json.loads(resp.text), None, {"model": str(model), "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}
        except Exception as e:
            last_error = str(e)
            if _is_content_filter_error(e):
                content_filter_hit = True
                print(f"    ⚠ {client_type} content filter — trying next provider", flush=True)
            else:
                print(f"    ✗ {client_type} failed: {e}", flush=True)
            continue
    if content_filter_hit:
        return None, "content_filter: blocked by provider safety filter", None
    return None, last_error or "all providers failed", None


def _extract_host_from_source_name(source_name: str) -> Optional[str]:
    """Extract host name from source_name like 'Monetary Matters with Jack Farley'."""
    if not source_name:
        return None
    # Match "with FirstName LastName" patterns, allowing apostrophes in names
    m = re.search(r"\bwith\s+([A-Z][a-zA-Z']+(?:\s+[A-Z][a-zA-Z']+)+)", source_name)
    if m:
        return m.group(1)
    return None


def _extract_speakers_from_notable_quotes(notable_quotes_json: str) -> List[str]:
    """Extract unique speaker names from notable_quotes JSON array."""
    if not notable_quotes_json:
        return []
    try:
        quotes = json.loads(notable_quotes_json)
        if isinstance(quotes, list):
            speakers = set()
            for q in quotes:
                if isinstance(q, dict) and q.get("speaker"):
                    speakers.add(q["speaker"])
            return sorted(speakers)
    except (json.JSONDecodeError, TypeError):
        pass
    return []


def generate_deep_dive_with_ai(
    clients: List[Tuple[str, Any]],
    title: str,
    source_content: str,
    source_type: str,
    insight_summary: str,
    key_takeaway: str,
    retry_hint: str = "",
    host_name: Optional[str] = None,
    guest_names: Optional[List[str]] = None,
) -> Tuple[Optional[dict], Optional[str], Optional[dict]]:
    """Generate deep dive content using AI (high-ROI: source evidence + falsifiers + anti-paraphrase).
    
    Returns: (content_dict, error_string, usage_info)
    usage_info dict has keys: model, input_tokens, output_tokens, cost_usd
    """

    from transcript_window import sample_transcript_window
    src = sample_transcript_window(source_content, SOURCE_SNIPPET_CHARS)
    print(
        f"    Deep dive transcript window: {len(src)} chars (limit {SOURCE_SNIPPET_CHARS}, raw {len(source_content or '')})",
        flush=True,
    )
    label = "Podcast / transcript" if source_type == "podcast" else "Newsletter / source body"

    retry_block = ""
    if retry_hint.strip():
        retry_block = f"\n\nVALIDATION RETRY — fix the following and keep valid JSON only:\n{retry_hint}\n"

    speaker_block = ""
    if source_type == "podcast" and (host_name or guest_names):
        speakers = []
        if host_name:
            speakers.append(f"Host: {host_name}")
        if guest_names:
            speakers.append(f"Guest(s): {', '.join(guest_names)}")
        speaker_block = f"\nSPEAKERS (use these exact names for source_quotes attribution):\n" + "\n".join(speakers) + "\n"

    prompt = f"""You are an elite investment analyst writing a "Deep Dive" that MUST add depth beyond the insight card — not a longer restatement of it.

ALREADY-PUBLISHED INSIGHT CARD (treat this as ALREADY SHOWN TO THE USER; do not paraphrase it or replay its thematic bullets):
Summary: {insight_summary or "(none)"}
Key takeaway: {key_takeaway or "(none)"}
{speaker_block}
{label.upper()}:
{src}

INSIGHT TITLE: {title}

Return ONLY valid JSON with these keys:

{{
  "source_quotes": "Exactly 2 or 3 lines. Each line MUST be: - Full Name: \"verbatim quote from the source\". Use the SPEAKERS names above when attributing quotes (e.g., 'J Mintzmyer: \"quote\"' not 'Guest: \"quote\"'). Never write Host or Guest when the name is known. Never invent a phonetic misspelling. NO opening sentence summarizing the episode.",
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

    raw, err, usage_info = _call_json_model(clients, prompt)
    if raw:
        return normalize_from_ai_response(raw), err, usage_info
    return None, err, usage_info


def store_deep_dive(insight_id: int, episode_id: int, content: dict, usage_info: Optional[dict] = None) -> bool:
    """Store deep dive content in database.
    
    Args:
        insight_id: ID in latest_insights
        episode_id: ID in podcast_episodes
        content: Deep dive content dict
        usage_info: Optional dict with model, input_tokens, output_tokens, cost_usd, attempt_count
    """
    conn = get_db_connection()

    try:
        ensure_deep_dive_schema(conn)
        # Sanitize ticker_analysis: drop placeholder keys (TICKER1, Ticker2, etc.)
        raw_tickers = content.get('ticker_analysis') or {}
        ticker_analysis = sanitize_ticker_analysis(raw_tickers)
        if len(ticker_analysis) < len(raw_tickers):
            # Avoid overwriting with empty if AI returned only placeholders
            content = {**content, 'ticker_analysis': ticker_analysis}

        # Extract usage info
        model_used = usage_info.get("model") if usage_info else None
        input_tokens = usage_info.get("input_tokens") if usage_info else None
        output_tokens = usage_info.get("output_tokens") if usage_info else None
        cost_usd = usage_info.get("cost_usd") if usage_info else None
        attempt_count = usage_info.get("attempt_count") if usage_info else None

        conn.execute(
            """
            INSERT INTO deep_dive_content (
                insight_id, podcast_episode_id, overview, key_takeaways_detailed,
                investment_thesis, ticker_analysis, positioning_guidance,
                risk_factors, contrarian_signals, catalysts,
                episode_evidence, falsification_tracks, schema_version, created_at,
                model_used, input_tokens, output_tokens, cost_usd, attempt_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                model_used,
                input_tokens,
                output_tokens,
                cost_usd,
                attempt_count,
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
    host_name: Optional[str] = None,
    guest_names: Optional[List[str]] = None,
) -> Tuple[Optional[Dict[str, Any]], Optional[str], Optional[dict]]:
    """Generate with retries when overlap or structural checks fail.
    
    Returns: (content_dict, error_string, usage_info)
    usage_info includes total tokens/cost across all attempts and attempt_count.
    """
    source_content = get_source_content(insight_id, source_type, episode_id)
    if not source_content:
        return None, "missing source content", None

    retry_hint = ""
    last_error = ""
    total_input_tokens = 0
    total_output_tokens = 0
    total_cost = 0.0
    model_used = None
    
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        content, err, usage_info = generate_deep_dive_with_ai(
            clients,
            title,
            source_content,
            source_type,
            insight_summary,
            key_takeaway,
            retry_hint=retry_hint,
            host_name=host_name,
            guest_names=guest_names,
        )
        
        # Accumulate usage across attempts
        if usage_info:
            total_input_tokens += usage_info.get("input_tokens", 0)
            total_output_tokens += usage_info.get("output_tokens", 0)
            total_cost += usage_info.get("cost_usd", 0.0)
            model_used = usage_info.get("model")
        
        if err:
            last_error = err
        if not content:
            if err and _is_content_filter_error(Exception(err)):
                return None, err, {"model": model_used, "input_tokens": total_input_tokens, "output_tokens": total_output_tokens, "cost_usd": total_cost, "attempt_count": attempt}
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
                final_usage = {"model": model_used, "input_tokens": total_input_tokens, "output_tokens": total_output_tokens, "cost_usd": total_cost, "attempt_count": attempt}
                return None, validation_errors[0], final_usage
            continue

        if attempt > 1:
            print(
                f"    ✓ Passed validation on attempt {attempt} "
                f"(card overlap {overlap:.2f}, evidence {ev_sim:.2f}, canned {canned})",
                flush=True,
            )
        final_usage = {"model": model_used, "input_tokens": total_input_tokens, "output_tokens": total_output_tokens, "cost_usd": total_cost, "attempt_count": attempt}
        return content, None, final_usage

    final_usage = {"model": model_used, "input_tokens": total_input_tokens, "output_tokens": total_output_tokens, "cost_usd": total_cost, "attempt_count": MAX_GENERATION_ATTEMPTS}
    return None, last_error or "generation failed after retries", final_usage


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
                   li.summary, li.key_takeaway, li.source_date,
                   li.notable_quotes, li.source_name
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
                   li.summary, li.key_takeaway, li.source_date,
                   li.notable_quotes, li.source_name
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
        source_date = row["source_date"] or ""
        notable_quotes = row["notable_quotes"] or ""
        source_name = row["source_name"] or ""

        # Extract speaker names for podcasts
        host_name = _extract_host_from_source_name(source_name) if source_type == "podcast" else None
        guest_names = _extract_speakers_from_notable_quotes(notable_quotes) if source_type == "podcast" else None

        print(f"[{insight_id}] {title[:60]}", flush=True)
        if host_name or guest_names:
            speakers_info = []
            if host_name:
                speakers_info.append(f"Host: {host_name}")
            if guest_names:
                speakers_info.append(f"Guest(s): {', '.join(guest_names)}")
            print(f"    Speakers: {'; '.join(speakers_info)}", flush=True)

        content, err_detail, usage_info = run_deep_dive_generation_attempts(
            clients,
            insight_id,
            title,
            source_type,
            episode_id,
            insight_summary,
            key_takeaway,
            host_name=host_name,
            guest_names=guest_names,
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

        if "catalysts" in content and content["catalysts"]:
            content["catalysts"] = filter_stale_catalysts(content["catalysts"], source_date)

        if store_deep_dive(insight_id, episode_id, content, usage_info=usage_info):
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
