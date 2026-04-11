#!/usr/bin/env python3
"""
Generate Deep Dive content for insights that don't have it.

This script:
1. Finds all insights without deep_dive_content
2. Retrieves source content (transcript for podcasts, content for newsletters)
3. Uses AI to generate deep dives with: source-grounded evidence, falsification tracks,
   and overlap rejection vs the insight card (retries up to 3)
4. Stores in deep_dive_content table (episode_evidence, falsification_tracks columns)

To run manually:
    python3 generate_deepdives.py

To run for specific insights only:
    python3 generate_deepdives.py --insight-ids 19,21,22
"""

import sys
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

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"


# Reject Deep Dives that mostly paraphrase the insight card (cheap overlap check).
INSIGHT_OVERLAP_REJECT = 0.68
MAX_GENERATION_ATTEMPTS = 3
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


def deep_dive_structural_ok(content: Dict[str, Any]) -> Tuple[bool, str]:
    """Require episode-anchored evidence and explicit falsifiers."""
    ev = (content.get("episode_evidence") or "").strip()
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
    """Get AI client - prefers Moonshot/Kimi (cheapest for us)."""
    # Try Moonshot first (what we have working)
    auth_profiles_path = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
    if auth_profiles_path.exists():
        try:
            with open(auth_profiles_path) as f:
                auth_data = json.load(f)
            profiles = auth_data.get('profiles', {})
            if 'moonshot:default' in profiles:
                profile = profiles['moonshot:default']
                if profile.get('type') == 'api_key':
                    kimi_key = profile.get('key', '')
                    if kimi_key:
                        from openai import OpenAI
                        client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
                        print("  Using Moonshot/Kimi API", flush=True)
                        return ('moonshot', client)
        except Exception as e:
            print(f"  ⚠ Moonshot init failed: {e}", flush=True)
    
    # Try Gemini (if configured)
    try:
        import google.generativeai as genai
        import os
        gemini_key = os.environ.get('GEMINI_API_KEY')
        if gemini_key:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API", flush=True)
            return ('gemini', None)
    except Exception as e:
        print(f"  ⚠ Gemini not available: {e}", flush=True)
    
    print("  ✗ No AI client available", flush=True)
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
                with open(transcript_path, encoding='utf-8') as f:
                    return f.read()
    
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

ALREADY-PUBLISHED INSIGHT CARD (do NOT paraphrase this; add new angles, mechanisms, and source-grounded detail):
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
  "overview": "1-2 tight paragraphs: frame the debate and why it matters NOW — avoid repeating the insight summary sentences.",
  "key_takeaways_detailed": [
    "4-6 bullets: actionable, distinct from the insight card bullets"
  ],
  "investment_thesis": "Core logic, timeframe, and what has to go right",
  "ticker_analysis": {{
    "AAPL": {{
      "rationale": "Why this ticker is relevant to this thesis",
      "positioning": "How to position (long/short, tactical vs strategic)",
      "risk": "Key risks for this specific position"
    }}
  }},
  "positioning_guidance": "Sizing, hedges, time horizon",
  "risk_factors": ["3-5 risks"],
  "contrarian_signals": ["2-3 opposing angles"],
  "catalysts": ["3-5 milestones or dates to watch"]
}}

Hard rules:
- episode_evidence MUST cite the SOURCE MATERIAL; do not invent quotes. If a detail is not in the source, say so in analysis elsewhere, not inside quoted lines.
- overview + investment_thesis + key_takeaways_detailed must NOT be a close paraphrase of the Summary/Key takeaway above — add mechanism, second-order effects, or contested assumptions.
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
                content.get("positioning_guidance", ""),
                json.dumps(content.get("risk_factors", [])),
                json.dumps(content.get("contrarian_signals", [])),
                json.dumps(content.get("catalysts", [])),
                content.get("episode_evidence", ""),
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
        ok_struct, struct_reason = deep_dive_structural_ok(content)

        if overlap > INSIGHT_OVERLAP_REJECT:
            retry_hint = (
                f"Previous output was too similar to the insight card (overlap {overlap:.2f}). "
                "Rewrite overview, investment_thesis, and key_takeaways_detailed to add NEW mechanisms, "
                "second-order effects, or contested assumptions — do not restate the summary."
            )
            print(f"    ⚠ Attempt {attempt}: insight overlap {overlap:.2f} > {INSIGHT_OVERLAP_REJECT}", flush=True)
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
            print(f"    ✓ Passed overlap {overlap:.2f} and structural checks on attempt {attempt}", flush=True)
        return content

    return None


def generate_missing_deepdives(insight_ids: list = None):
    """Generate deep dives for all insights that don't have them."""
    
    # Force unbuffered output for real-time logging
    sys.stdout.reconfigure(line_buffering=True)
    
    conn = get_db_connection()
    
    if insight_ids:
        # Specific insights requested
        placeholders = ','.join('?' * len(insight_ids))
        cursor = conn.execute(f"""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            WHERE li.id IN ({placeholders})
        """, insight_ids)
    else:
        # All insights without deep dives
        cursor = conn.execute("""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id,
                   li.summary, li.key_takeaway
            FROM latest_insights li
            LEFT JOIN deep_dive_content ddc ON li.id = ddc.insight_id
            WHERE ddc.id IS NULL
        """)
    
    insights = cursor.fetchall()
    conn.close()
    
    if not insights:
        print("No insights need Deep Dives!", flush=True)
        return 0
    
    print(f"Generating Deep Dives for {len(insights)} insights...\n", flush=True)
    
    # Get AI client
    client_info = get_ai_client()
    if not client_info:
        print("✗ Cannot proceed without AI client")
        return 0
    
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
    
    print(f"\n✓ Generated {generated}/{len(insights)} Deep Dives", flush=True)
    return generated


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

    generate_missing_deepdives(insight_ids)
