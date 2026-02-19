#!/usr/bin/env python3
"""
Fix script: Re-analyze the 5 new episodes and add ticker mentions.
Also fixes podcast names for episodes that were assigned 'Unknown Podcast'.
"""

import os
import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

# Try to import OpenAI
try:
    from openai import OpenAI
except ImportError:
    print("OpenAI not installed")
    sys.exit(1)

DB_PATH = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"

# Correct podcast names based on filename patterns
FILENAME_TO_PODCAST = {
    'DVVTS4101423217': 'Moonshots with Peter Diamandis',
    'EWWMN3482909708': 'Monetary Matters with Jack Farley',
    'cecdbe38125e2786cbfebe31dd083d4f': 'Dwarkesh Podcast',
    'https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-0-13%2F202cb903-9237-cf95-362f-50770b90d121': 'Network State Podcast',
    'https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-17%2F418255357-44100-2-b07eb0f35b621': 'The Jack Mallers Show',
}

EPISODE_IDS = {
    'DVVTS4101423217': 17,
    'EWWMN3482909708': 18,
    'cecdbe38125e2786cbfebe31dd083d4f': 19,
    'https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-1-17%2F418255357-44100-2-b07eb0f35b621': 20,
    'https%3A%2F%2Fd3ctxlq1ktw2nl.cloudfront.net%2Fstaging%2F2026-0-13%2F202cb903-9237-cf95-362f-50770b90d121': 21,
}


def get_ai_client():
    auth_profiles_path = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
    if auth_profiles_path.exists():
        with open(auth_profiles_path, 'r') as f:
            auth_data = json.load(f)
            profiles = auth_data.get('profiles', {})
            if 'moonshot:default' in profiles:
                moonshot_profile = profiles['moonshot:default']
                if moonshot_profile.get('type') == 'api_key':
                    kimi_key = moonshot_profile.get('key')
                    if kimi_key:
                        client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
                        print("Using Moonshot API")
                        return client
    
    openai_key = os.environ.get('OPENAI_API_KEY')
    if openai_key:
        client = OpenAI(api_key=openai_key)
        print("Using OpenAI API")
        return client
    
    print("No API key found!")
    return None


def analyze_for_tickers(client, transcript_content: str, podcast_name: str, episode_title: str) -> dict:
    """Use AI to extract ticker mentions from transcript."""
    
    max_chars = 12000
    if len(transcript_content) > max_chars:
        transcript_content = transcript_content[:max_chars] + "\n\n[Transcript truncated]"
    
    prompt = f"""Analyze this podcast transcript from "{podcast_name}" episode "{episode_title}" and extract all financial/investment ticker mentions and insights.

TRANSCRIPT:
{transcript_content}

Return ONLY valid JSON in this exact format:
{{
  "key_tickers": ["TICKER1", "TICKER2"],
  "ticker_mentions": [
    {{
      "ticker": "TICKER",
      "context": "Specific context about this ticker from the transcript (1-2 sentences)",
      "sentiment": "bullish",
      "conviction_score": 75,
      "timeframe": "long_term",
      "is_contrarian": false,
      "is_disruption_focused": true
    }}
  ]
}}

Rules:
- sentiment MUST be exactly: "bullish", "bearish", or "neutral"
- timeframe MUST be exactly: "short_term", "long_term", or "unspecified"
- conviction_score: 0-100 integer
- Include crypto tickers like BTC, ETH as well as stocks
- If no financial tickers are mentioned, return empty arrays
- Return ONLY valid JSON, no markdown"""

    try:
        response = client.chat.completions.create(
            model="moonshot-v1-8k",
            messages=[
                {"role": "system", "content": "You are a financial analyst. Return only valid JSON."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,
            max_tokens=2000
        )
        
        content = response.choices[0].message.content.strip()
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()
        
        return json.loads(content)
    except Exception as e:
        print(f"  AI error: {e}")
        return {"key_tickers": [], "ticker_mentions": []}


def fix_episode(conn, episode_id: int, stem: str, transcript_path: Path, client):
    """Fix a single episode: update podcast name and add ticker mentions."""
    
    c = conn.cursor()
    
    # Get current episode info
    c.execute("SELECT id, podcast_name, episode_title, key_tickers FROM podcast_episodes WHERE id = ?", (episode_id,))
    row = c.fetchone()
    if not row:
        print(f"  Episode {episode_id} not found!")
        return
    
    ep_id, current_podcast, episode_title, current_tickers = row
    correct_podcast = FILENAME_TO_PODCAST.get(stem, current_podcast)
    
    print(f"\nEpisode {episode_id}: {episode_title[:60]}")
    print(f"  Podcast: {current_podcast} -> {correct_podcast}")
    
    # Fix podcast name if it's "Unknown Podcast"
    if current_podcast == 'Unknown Podcast':
        c.execute("UPDATE podcast_episodes SET podcast_name = ? WHERE id = ?", (correct_podcast, episode_id))
        print(f"  ✓ Fixed podcast name to: {correct_podcast}")
    
    # Read transcript
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"  ✗ Could not read transcript: {e}")
        return
    
    # Analyze for tickers
    print(f"  Analyzing tickers with AI...")
    analysis = analyze_for_tickers(client, content, correct_podcast, episode_title)
    
    key_tickers = analysis.get('key_tickers', [])
    ticker_mentions = analysis.get('ticker_mentions', [])
    
    print(f"  Found tickers: {key_tickers}")
    
    # Update key_tickers in episode
    if key_tickers:
        c.execute("UPDATE podcast_episodes SET key_tickers = ? WHERE id = ?", 
                  (json.dumps(key_tickers), episode_id))
    
    # Delete any existing ticker mentions for this episode (clean slate)
    c.execute("DELETE FROM ticker_mentions WHERE episode_title = ?", (episode_title,))
    
    # Add ticker mentions
    added = 0
    for tm in ticker_mentions:
        try:
            ticker = tm.get('ticker', '').strip().upper()
            if not ticker or len(ticker) > 10:
                continue
            
            sentiment = tm.get('sentiment', 'neutral')
            if sentiment not in ('bullish', 'bearish', 'neutral'):
                sentiment = 'neutral'
            
            timeframe = tm.get('timeframe', 'unspecified')
            if timeframe not in ('short_term', 'long_term', 'unspecified'):
                timeframe = 'unspecified'
            
            conviction = int(tm.get('conviction_score', 50))
            conviction = max(-100, min(100, conviction))
            
            c.execute("""
                INSERT INTO ticker_mentions 
                (ticker, source_type, source_name, episode_title, context,
                 conviction_score, sentiment, timeframe, is_contrarian, is_disruption_focused)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ticker, 'podcast', correct_podcast, episode_title,
                tm.get('context', '')[:300], conviction, sentiment, timeframe,
                bool(tm.get('is_contrarian', False)), bool(tm.get('is_disruption_focused', False))
            ))
            added += 1
        except Exception as e:
            print(f"    ✗ Failed to add {tm.get('ticker')}: {e}")
    
    conn.commit()
    print(f"  ✓ Added {added} ticker mentions")


def main():
    client = get_ai_client()
    if not client:
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    
    # Process each of the 5 target transcripts
    for stem, episode_id in EPISODE_IDS.items():
        transcript_path = TRANSCRIPT_DIR / f"{stem}.txt"
        if not transcript_path.exists():
            print(f"Transcript not found: {transcript_path}")
            continue
        
        fix_episode(conn, episode_id, stem, transcript_path, client)
    
    conn.close()
    
    # Verify results
    print("\n" + "="*60)
    print("Verification:")
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT pe.id, pe.podcast_name, pe.episode_title, pe.key_tickers,
               COUNT(tm.id) as ticker_count
        FROM podcast_episodes pe
        LEFT JOIN ticker_mentions tm ON pe.episode_title = tm.episode_title
        WHERE pe.id >= 17
        GROUP BY pe.id
        ORDER BY pe.id
    """)
    for r in c.fetchall():
        print(f"  ID {r[0]}: {r[1]} - {r[2][:50]} | tickers: {r[3]} | mentions: {r[4]}")
    conn.close()


if __name__ == "__main__":
    main()
