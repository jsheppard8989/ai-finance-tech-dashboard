#!/usr/bin/env python3
"""
Generate Deep Dive content for insights that don't have it.

This script:
1. Finds all insights without deep_dive_content
2. Retrieves source content (transcript for podcasts, content for newsletters)
3. Uses AI to generate deep dives with: source-grounded evidence, falsification tracks,
   overlap rejection vs the insight card including overview-specific similarity (retries up to 4)
4. Stores in deep_dive_content table (`positioning_guidance` / `risk_factors` DB columns kept but no longer populated)

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
# Overview alone tends to regress into a longer Insight summary; judge it separately too.
OVERVIEW_CARD_OVERLAP_REJECT = 0.55
MAX_GENERATION_ATTEMPTS = 4
SOURCE_SNIPPET_CHARS = 12000


def ensure_deep_dive_schema(conn: sqlite3.Connection) -> None:
    """Add episode_evidence / falsification_tracks columns if missing (SQLite)."""
    cur = conn.execute("PRAGMA table_info(deep_dive_content)")
    existing = {row[1] for row in cur.fetchall()}
    if "episode_evidence" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN episode_evidence TEXT")
    if "falsification_tracks" not in existing:
        conn.execute("ALTER TABLE deep_dive_content ADD COLUMN falsification_tracks TEXT")
    conn.commit()


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _pack_repeat_prone(content: Dict[str, Any]) -> str:
    parts: List[str] = [
        str(content.get("overview") or ""),
        str(content.get("investment_thesis") or ""),
    ]
    kt = content.get("key_takeaways_detailed") or []
    if isinstance(kt, list):
        parts.extend(str(x) for x in kt[:4])
    return "\n".join(parts)


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


def deep_dive_structural_ok(content: Dict[str, Any]) -> Tuple[bool, str]:
    """Require episode-anchored evidence and explicit falsifiers."""
    ev = _episode_evidence_text(content.get("episode_evidence"))
    if len(ev) < 120:
        return False, "episode_evidence too short or missing"
    wc = len(ev.split())
    quote_like = sum(ev.count(q) for q in ('"', "'", "“", "”", "‘", "’"))
    if quote_like < 2 and "\n-" not in ev and "•" not in ev:
        # Allow long analytical grounding without ASCII quotes
        if wc < 180 and not re.search(
            r"\b(said|argues|according|host|guest|newsletter|writes|email|author)\b", ev, re.I
        ):
            return False, "episode_evidence should include quotes, bullets, or labeled speaker/source lines"

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


def get_ai_client():
    """Match analyze_transcript priority: .env keys, then Cursor auth profiles Moonshot, Gemini, OpenAI."""
    _load_dotenv_for_deepdives()

    if not OPENAI_AVAILABLE:
        print("  ✗ openai package not installed (pip install openai)", flush=True)
        return None

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
                        return ("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot (profiles) init failed: {e}", flush=True)

    kimi_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
    if kimi_key:
        try:
            client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
            print("  Using Moonshot/Kimi API (MOONSHOT_API_KEY)", flush=True)
            return ("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot env init failed: {e}", flush=True)

    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if gemini_key and GEMINI_AVAILABLE:
        try:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API", flush=True)
            return ("gemini", None)
        except Exception as e:
            print(f"  ⚠ Gemini init failed: {e}", flush=True)

    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if openai_key:
        try:
            client = OpenAI(api_key=openai_key)
            print("  Using OpenAI API", flush=True)
            return ("openai", client)
        except Exception as e:
            print(f"  ⚠ OpenAI init failed: {e}", flush=True)

    print(
        "  ✗ No AI client: set MOONSHOT_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY in .env "
        "(or Moonshot in Cursor auth profiles).",
        flush=True,
    )
    return None


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


def _call_json_model(client_info, prompt: str) -> Optional[dict]:
    try:
        client_type, client = client_info

        if client_type == "moonshot":
            resp = client.chat.completions.create(
                model="moonshot-v1-8k",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=3200,
            )
            return json.loads(resp.choices[0].message.content)

        if client_type == "openai":
            resp = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=3200,
            )
            return json.loads(resp.choices[0].message.content)

        if client_type == "gemini":
            import google.generativeai as genai

            model = genai.GenerativeModel("gemini-1.5-flash")
            resp = model.generate_content(prompt)
            return json.loads(resp.text)

        return None
    except Exception as e:
        print(f"    ✗ AI generation failed: {e}", flush=True)
        return None


def generate_deep_dive_with_ai(
    client_info,
    title: str,
    source_content: str,
    source_type: str,
    insight_summary: str,
    key_takeaway: str,
    retry_hint: str = "",
) -> Optional[dict]:
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
  "episode_evidence": "A dedicated section (3-6 short paragraphs OR tight bullets) grounded in the SOURCE MATERIAL above. Include at least TWO short verbatim quotes (use quotation marks) OR clearly labeled paraphrases (e.g. Host: … / Guest: …). Explain mechanisms, numbers, or causal claims the insight summary did not spell out. If the source is a newsletter, attribute lines to the author or document. Minimum ~150 words.",
  "falsification_tracks": [
    "3-5 bullets: specific, observable data, events, or market outcomes that would materially REDUCE conviction in the thesis (or flip it). Each bullet must be testable — not vibes.",
    "Example: 'If X metric prints below Y for two consecutive quarters, the labor-shortage narrative is weakened.'"
  ],
  "overview": "EXACTLY 2 short paragraphs totaling ~120–220 words. Paragraph 1: name the unresolved tension / competitive dynamic / policy tradeoff implied by the source — NOT what was SAID sentence-by-sentence and NOT thematic recap (forbidden roles: synopsis, elongated headline, 'guest argued X therefore Y' unless X is genuinely new versus the Insight card). Paragraph 2: allocator-relevant implication: WHO wins or loses, what metric or institution arbitrates uncertainty, horizon of proof. HARD BAN on reusing distinctive multi-word phrases from the Insight Summary/Key takeaway (if you recycle the card's wording, rewrite completely). Prefer structure ('what is contested', 'what converts belief') over narration.",
  "key_takeaways_detailed": [
    "4-6 bullets: actionable, distinct from BOTH the Insight card bullets AND episode_evidence (no copy-paste; each bullet must add framing, contingency, or a decision rule)"
  ],
  "investment_thesis": "Core logic tied to contested claims in the SOURCE (not repetition of Insight summary). Include timeframe AND what observable development would vindicate vs invalidate it.",
  "ticker_analysis": {{
    "AAPL": {{
      "rationale": "Why this ticker is relevant to this thesis",
      "positioning": "How to position (long/short, tactical vs strategic)",
      "risk": "Key risks for this specific position"
    }}
  }},
  "contrarian_signals": ["2-4 opposing angles an informed skeptic would raise"],
  "catalysts": ["3-5 milestones, rulings, prints, or dates to watch"]
}}

Hard rules:
- episode_evidence MUST cite the SOURCE MATERIAL; do not invent quotes. If a detail is not in the source, say so in analysis elsewhere, not inside quoted lines.
- overview + investment_thesis + key_takeaways_detailed must NOT read like a light edit of the Summary/Key takeaway — they must reflect mechanism, second-order effects, allocation tradeoffs, or institutional process the card did not carry.
- Put portfolio 'how to size / hedge' thinking inside ticker_analysis or investment_thesis if needed; do NOT output separate positioning or generic risk lists.
- falsification_tracks must be concrete (what would change your mind).
- ticker_analysis: 3-6 REAL tickers from the source as keys. NEVER use TICKER1, TICKER2, placeholders.
- English only.
{retry_block}"""

    return _call_json_model(client_info, prompt)


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
                episode_evidence, falsification_tracks, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
    client_info,
    insight_id: int,
    title: str,
    source_type: str,
    episode_id: int,
    insight_summary: str,
    key_takeaway: str,
) -> Optional[Dict[str, Any]]:
    """Generate with retries when overlap or structural checks fail."""
    source_content = get_source_content(insight_id, source_type, episode_id)
    if not source_content:
        return None

    retry_hint = ""
    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        content = generate_deep_dive_with_ai(
            client_info,
            title,
            source_content,
            source_type,
            insight_summary,
            key_takeaway,
            retry_hint=retry_hint,
        )
        if not content:
            return None

        overlap = insight_body_overlap_ratio(insight_summary, key_takeaway, content)
        ov_sim = overview_vs_card_overlap(insight_summary, key_takeaway, str(content.get("overview") or ""))
        ok_struct, struct_reason = deep_dive_structural_ok(content)

        if overlap > INSIGHT_OVERLAP_REJECT or ov_sim > OVERVIEW_CARD_OVERLAP_REJECT:
            parts = []
            if overlap > INSIGHT_OVERLAP_REJECT:
                parts.append(
                    f"Aggregate Deep Dive prose is too similar to the insight card (overlap {overlap:.2f})."
                )
            if ov_sim > OVERVIEW_CARD_OVERLAP_REJECT:
                parts.append(
                    f"Overview alone is too similar to the insight card (overlap {ov_sim:.2f})."
                )
            retry_hint = (
                " ".join(parts)
                + " Rewrite overview from scratch: focus on unresolved tension, who arbitrates truth, and allocator tradeoffs — "
                "zero reuse of distinctive phrases from Summary/Key takeaway. "
                "Rewrite investment_thesis and key_takeaways_detailed to add NEW mechanisms and contingencies — do not restate the card."
            )
            print(
                f"    ⚠ Attempt {attempt}: insight overlap {overlap:.2f} (max {INSIGHT_OVERLAP_REJECT}); "
                f"overview vs card {ov_sim:.2f} (max {OVERVIEW_CARD_OVERLAP_REJECT})",
                flush=True,
            )
            if attempt >= MAX_GENERATION_ATTEMPTS:
                print(f"    ✗ Giving up after {MAX_GENERATION_ATTEMPTS} attempts (still too similar to insight)", flush=True)
                return None
            continue

        if not ok_struct:
            retry_hint = f"Structural check failed: {struct_reason}. Fix episode_evidence and falsification_tracks."
            print(f"    ⚠ Attempt {attempt}: {struct_reason}", flush=True)
            if attempt >= MAX_GENERATION_ATTEMPTS:
                print(f"    ✗ Giving up: {struct_reason}", flush=True)
                return None
            continue

        if attempt > 1:
            print(
                f"    ✓ Passed overlap aggregate={overlap:.2f}, overview-vs-card={ov_sim:.2f} on attempt {attempt}",
                flush=True,
            )
        return content

    return None


def generate_missing_deepdives(insight_ids: list = None) -> Tuple[int, int]:
    """Generate deep dives for all insights that don't have them.

    Returns (generated_count, attempted_count). attempted_count is the number of
    insights that needed a Deep Dive when the run started.
    """

    # Force unbuffered output for real-time logging
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    conn = get_db_connection()

    if insight_ids:
        # Specific insights requested
        placeholders = ",".join("?" * len(insight_ids))
        cursor = conn.execute(
            f"""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            WHERE li.id IN ({placeholders})
        """,
            insight_ids,
        )
    else:
        # All insights without deep dives
        cursor = conn.execute(
            """
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            LEFT JOIN deep_dive_content ddc ON li.id = ddc.insight_id
            WHERE ddc.id IS NULL
        """
        )

    insights = cursor.fetchall()
    conn.close()

    if not insights:
        print("No insights need Deep Dives!", flush=True)
        return 0, 0

    need = len(insights)
    print(f"Generating Deep Dives for {need} insights...\n", flush=True)

    # Get AI client
    client_info = get_ai_client()
    if not client_info:
        print("✗ Cannot proceed without AI client", flush=True)
        return 0, need

    generated = 0

    for row in insights:
        insight_id = row['id']
        title = row['title']
        source_type = row['source_type']
        episode_id = row['podcast_episode_id']
        insight_summary = row["summary"] or ""
        key_takeaway = row["key_takeaway"] or ""

        print(f"[{insight_id}] {title[:60]}", flush=True)

        content = run_deep_dive_generation_attempts(
            client_info,
            insight_id,
            title,
            source_type,
            episode_id,
            insight_summary,
            key_takeaway,
        )
        if not content:
            print(f"  ✗ Generation failed or rejected", flush=True)
            continue

        # Store it
        if store_deep_dive(insight_id, episode_id, content):
            print(f"  ✓ Deep Dive stored", flush=True)
            generated += 1
        else:
            print(f"  ✗ Storage failed", flush=True)
    
    print(f"\n✓ Generated {generated}/{need} Deep Dives", flush=True)
    return generated, need


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

    gen, need = generate_missing_deepdives(insight_ids)
    # Fail the step if nothing was produced when work was required (e.g. no AI client).
    # Partial success still exits 0 so the site can publish insights that did get Deep Dives;
    # insights without Deep Dives stay off the main list until a later run succeeds.
    if need > 0 and gen == 0:
        print("✗ Deep Dive step failed: zero generated while insights still need dives.", flush=True)
        sys.exit(1)
    sys.exit(0)
