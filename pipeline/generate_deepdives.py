#!/usr/bin/env python3
"""
Generate Deep Dive content for insights that don't have it.

This script:
1. Finds all insights without deep_dive_content
2. Retrieves source content (transcript for podcasts, content for newsletters)
3. Uses AI to generate comprehensive deep dive analysis
4. Stores in deep_dive_content table

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
from pathlib import Path
from datetime import datetime

# Add pipeline to path
sys.path.insert(0, str(Path(__file__).parent))

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
INBOX_DIR = Path.home() / ".openclaw/workspace/pipeline/inbox"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"


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


def generate_deep_dive_with_ai(client_info, title: str, source_content: str, source_type: str) -> dict:
    """Generate deep dive content using AI."""
    
    prompt = f"""You are an elite investment analyst creating a "Deep Dive" analysis for a financial insights website.

SOURCE MATERIAL ({source_type}):
{source_content[:8000]}

INSIGHT TITLE: {title}

Generate a comprehensive Deep Dive analysis in JSON format with these fields:

{{
  "overview": "2-3 paragraph executive summary of the investment thesis and why it matters now",
  
  "key_takeaways_detailed": [
    "4-6 specific, actionable bullet points that investors should understand"
  ],
  
  "investment_thesis": "1-2 paragraph detailed thesis explaining the core investment logic, catalysts, and timeframe",
  
  "ticker_analysis": {{
    "AAPL": {{
      "rationale": "Why this ticker is relevant to this thesis",
      "positioning": "How to position (long/short, tactical vs strategic)",
      "risk": "Key risks for this specific position"
    }},
    "NVDA": {{...}}
  }},
  
  "positioning_guidance": "Specific guidance on portfolio positioning: sizing, entry points, timeframes, hedges",
  
  "risk_factors": [
    "3-5 specific risks that could invalidate the thesis"
  ],
  
  "contrarian_signals": [
    "2-3 contrarian angles or opposing viewpoints worth considering"
  ],
  
  "catalysts": [
    "3-5 specific upcoming events, dates, or milestones that could move the thesis forward"
  ]
}}

Requirements:
- Be specific and actionable - no generic fluff
- Include 3-6 tickers with detailed analysis. Use REAL ticker symbols as keys (e.g. AAPL, NVDA, SPY, TSLA). Extract tickers mentioned in the source material. NEVER use placeholder keys like TICKER1, TICKER2, or company names without a ticker symbol.
- Focus on investment implications, not just news summary
- Timeframe should be explicit (short-term: <3mo, medium: 3-12mo, long: >1yr)
- Contrarian signals should show sophisticated understanding of risks
- All output must be written in clear, professional English only (no other languages)
"""

    try:
        client_type, client = client_info
        
        if client_type == 'moonshot':
            resp = client.chat.completions.create(
                model="moonshot-v1-8k",
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                max_tokens=2000
            )
            result = json.loads(resp.choices[0].message.content)
        
        elif client_type == 'gemini':
            import google.generativeai as genai
            model = genai.GenerativeModel('gemini-1.5-flash')
            resp = model.generate_content(prompt)
            result = json.loads(resp.text)
        
        else:
            return None
        
        return result
        
    except Exception as e:
        print(f"    ✗ AI generation failed: {e}")
        return None


def store_deep_dive(insight_id: int, episode_id: int, content: dict) -> bool:
    """Store deep dive content in database."""
    conn = get_db_connection()
    
    try:
        # Sanitize ticker_analysis: drop placeholder keys (TICKER1, Ticker2, etc.)
        raw_tickers = content.get('ticker_analysis') or {}
        ticker_analysis = sanitize_ticker_analysis(raw_tickers)
        if len(ticker_analysis) < len(raw_tickers):
            # Avoid overwriting with empty if AI returned only placeholders
            content = {**content, 'ticker_analysis': ticker_analysis}
        
        conn.execute("""
            INSERT INTO deep_dive_content (
                insight_id, podcast_episode_id, overview, key_takeaways_detailed,
                investment_thesis, ticker_analysis, positioning_guidance,
                risk_factors, contrarian_signals, catalysts, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            insight_id,
            episode_id,
            content.get('overview', ''),
            json.dumps(content.get('key_takeaways_detailed', [])),
            content.get('investment_thesis', ''),
            json.dumps(content.get('ticker_analysis', {})),
            content.get('positioning_guidance', ''),
            json.dumps(content.get('risk_factors', [])),
            json.dumps(content.get('contrarian_signals', [])),
            json.dumps(content.get('catalysts', [])),
            datetime.now().isoformat()
        ))
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


def generate_missing_deepdives(insight_ids: list = None):
    """Generate deep dives for all insights that don't have them."""
    
    # Force unbuffered output for real-time logging
    sys.stdout.reconfigure(line_buffering=True)
    
    conn = get_db_connection()
    
    if insight_ids:
        # Specific insights requested
        placeholders = ','.join('?' * len(insight_ids))
        cursor = conn.execute(f"""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id
            FROM latest_insights li
            WHERE li.id IN ({placeholders})
        """, insight_ids)
    else:
        # All insights without deep dives
        cursor = conn.execute("""
            SELECT li.id, li.title, li.source_type, li.podcast_episode_id
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
        
        print(f"[{insight_id}] {title[:60]}", flush=True)
        
        # Get source content
        source_content = get_source_content(insight_id, source_type, episode_id)
        if not source_content:
            print(f"  ⚠ No source content found, skipping", flush=True)
            continue
        
        # Generate deep dive
        content = generate_deep_dive_with_ai(client_info, title, source_content, source_type)
        if not content:
            print(f"  ✗ Generation failed", flush=True)
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
    parser.add_argument('--insight-ids', type=str, help='Comma-separated list of insight IDs to process')
    parser.add_argument('--fix-placeholder-tickers', action='store_true', help='One-time: remove TICKER1/Ticker2 etc. from existing DB rows')
    args = parser.parse_args()
    
    if args.fix_placeholder_tickers:
        clean_placeholder_tickers_in_db()
        sys.exit(0)
    
    insight_ids = None
    if args.insight_ids:
        insight_ids = [int(x.strip()) for x in args.insight_ids.split(',')]
    
    generate_missing_deepdives(insight_ids)
