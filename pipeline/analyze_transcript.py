#!/usr/bin/env python3
"""
Transcript Analyzer - Uses AI to extract structured data from podcast transcripts.
Adds PodcastEpisode and TickerMention records to the database.
"""

import os
import sys
import json
import re
from pathlib import Path
from datetime import datetime, date
from typing import List, Dict, Optional, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db, PodcastEpisode, TickerMention

# Try to import OpenAI
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("  ⚠ OpenAI library not installed. Run: pip install openai")

# Try to import Gemini
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False
    print("  ⚠ Google Generative AI library not installed. Run: pip install google-generativeai")

# Paths
TRANSCRIPT_DIR = Path.home() / ".openclaw/workspace/pipeline/transcripts"
PROCESSED_MARKER_DIR = Path.home() / ".openclaw/workspace/pipeline/processed"
PROCESSED_MARKER_DIR.mkdir(parents=True, exist_ok=True)

# Podcast name mappings from filename patterns
PODCAST_PATTERNS = {
    'EWWMN': ('Monetary Matters with Jack Farley', r'EWWMN(\d+)'),
    'IMP': ('The Moonshot Podcast', r'IMP(\d+)'),
    'jack_mallers': ('The Jack Mallers Show', r'jack_mallers'),
    'dario_amodei': ('a16z Live', r'dario_amodei'),
    'elon_musk': ('The Moonshot Podcast', r'elon_musk'),
    'peter_diamandis': ('Moonshots with Peter Diamandis', r'peter_diamandis_(\d+)'),
    'default': ('a16z Live', r'default'),
}

# Content-based podcast detection: scan transcript text for show identity clues
CONTENT_PODCAST_HINTS = [
    (r'welcome to moonshots|moonshot mates|ladies and gentlemen.*moonshots|this is moonshots', 'Moonshots with Peter Diamandis'),
    (r'university of podcast', 'University of Podcast'),
    (r'monetary matters|jack farley', 'Monetary Matters with Jack Farley'),
    (r'network state podcast|balaji srinivasan', 'Network State Podcast'),
    (r'jack mallers show|strike.*bitcoin', 'The Jack Mallers Show'),
    (r'dwarkesh.*patel|patel.*dwarkesh', 'Dwarkesh Podcast'),
    (r'all-in podcast|all in with chamath|bestie', 'All-In Podcast'),
    (r'lex fridman podcast|lex fridman', 'Lex Fridman Podcast'),
    (r'acquired\.fm|acquired podcast|ben gilbert.*david rosenthal', 'Acquired'),
    (r'invest like the best|patrick o\'shaughnessy', 'Invest Like the Best'),
    (r'we study billionaires|the investor\'s podcast', 'We Study Billionaires'),
]


def get_ai_client() -> Optional[any]:
    """Get AI client - tries Gemini FIRST (cheapest), falls back to OpenAI."""
    
    # Try Gemini API from environment (cheapest option)
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key and GEMINI_AVAILABLE:
        try:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API (primary - cheapest)")
            return ('gemini', gemini_key)
        except Exception as e:
            print(f"  ⚠ Gemini init failed: {e}")

    # Fall back to OpenAI
    openai_key = os.environ.get('OPENAI_API_KEY')
    if openai_key and OPENAI_AVAILABLE:
        try:
            client = OpenAI(api_key=openai_key)
            print("  Using OpenAI API (fallback)")
            return ('openai', client)
        except Exception as e:
            print(f"  ⚠ OpenAI init failed: {e}")

    print("  ⚠ No AI API keys found. Set GEMINI_API_KEY or OPENAI_API_KEY")
    return None


def parse_podcast_info(filename: str, content: str = '') -> Tuple[str, str]:
    """Extract podcast name and episode info from filename.
    
    Priority:
    1. Sidecar .meta.json file written by fetch_latest.py (RSS feed title — most accurate)
    2. Filename pattern matching
    3. Transcript content scanning
    4. 'Unknown Podcast' fallback
    """
    path = Path(filename)
    stem = path.stem
    
    # 1. Check for sidecar metadata (RSS-sourced, most reliable)
    transcript_dir = path.parent if path.is_absolute() else Path(__file__).parent / 'transcripts'
    meta_file = transcript_dir / f"{stem}.meta.json"
    if not meta_file.exists():
        # Also check relative to the transcript file itself
        meta_file = path.parent / f"{stem}.meta.json"
    if meta_file.exists():
        try:
            import json as _json
            with open(meta_file) as mf:
                meta = _json.load(mf)
            podcast_name = meta.get('podcast_name', '').strip()
            if podcast_name and podcast_name not in ('Unknown', 'Unknown Podcast', ''):
                return podcast_name, stem
        except Exception:
            pass
    
    # 2. Filename pattern matching
    for pattern_key, (podcast_name, regex) in PODCAST_PATTERNS.items():
        if pattern_key in stem or re.match(regex, stem):
            return podcast_name, stem
    
    # 3. Fallback: scan transcript content for show identity clues
    if content:
        content_lower = content[:3000].lower()
        for pattern, podcast_name in CONTENT_PODCAST_HINTS:
            if re.search(pattern, content_lower):
                return podcast_name, stem
    
    # 4. Final fallback
    return 'Unknown Podcast', stem


def extract_date_from_content(content: str) -> Optional[date]:
    """Try to extract episode date from transcript content."""
    # Look for common date patterns
    date_patterns = [
        r'(\w+),?\s+(\d{1,2})[,\s]+(\d{4})',  # Monday, February 9, 2026
        r'(\d{1,2})\s+(\w+)\s+(\d{4})',  # 9 February 2026
        r'(\w+)\s+(\d{1,2}),?\s+(\d{4})',  # February 9, 2026
    ]
    
    months = {
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'may': 5, 'june': 6, 'july': 7, 'august': 8,
        'september': 9, 'october': 10, 'november': 11, 'december': 12
    }
    
    content_lower = content[:5000].lower()  # Check first 5000 chars
    
    for pattern in date_patterns:
        match = re.search(pattern, content_lower)
        if match:
            try:
                groups = match.groups()
                if len(groups) == 3:
                    # Try to parse
                    for i, g in enumerate(groups):
                        if g.lower() in months:
                            month = months[g.lower()]
                            day = int(groups[1] if i == 0 else groups[0] if i == 2 else groups[1])
                            year = int(groups[2] if i == 0 else groups[2] if i == 2 else groups[2])
                            return date(year, month, day)
            except (ValueError, IndexError):
                continue
    
    return None


def is_transcript_processed(transcript_path: Path) -> bool:
    """Check if transcript has already been processed."""
    marker_file = PROCESSED_MARKER_DIR / f"{transcript_path.stem}.processed"
    return marker_file.exists()


def mark_transcript_processed(transcript_path: Path, episode_id: int):
    """Mark transcript as processed (file marker + DB flag)."""
    marker_file = PROCESSED_MARKER_DIR / f"{transcript_path.stem}.processed"
    with open(marker_file, 'w') as f:
        f.write(json.dumps({
            'processed_at': datetime.now().isoformat(),
            'episode_id': episode_id,
            'transcript_path': str(transcript_path)
        }))
    # Also set is_processed=1 in the database so the pipeline can query it
    if episode_id and episode_id > 0:
        try:
            import sqlite3 as _sqlite3
            _conn = _sqlite3.connect(str(Path.home() / ".openclaw/workspace/pipeline/dashboard.db"))
            _conn.execute("UPDATE podcast_episodes SET is_processed = 1 WHERE id = ?", (episode_id,))
            _conn.commit()
            _conn.close()
        except Exception as e:
            print(f"    ⚠ Could not set is_processed in DB for episode {episode_id}: {e}")


def analyze_transcript_with_ai(client_info, transcript_content: str, podcast_name: str) -> Dict:
    """Use AI to extract structured data from transcript."""
    
    if client_info is None:
        return None
    
    client_type, client = client_info
    
    # Smart sampling: send beginning + middle + end rather than just truncating top
    # This gives the AI context from across the full episode, not just the intro
    max_chars = 12000
    if len(transcript_content) > max_chars:
        chunk = max_chars // 3
        beginning = transcript_content[:chunk]
        mid_start = len(transcript_content) // 2 - chunk // 2
        middle = transcript_content[mid_start:mid_start + chunk]
        ending = transcript_content[-chunk:]
        transcript_content = (
            beginning + "\n\n[...middle of transcript...]\n\n" +
            middle + "\n\n[...end of transcript...]\n\n" +
            ending
        )
    
    prompt = f"""You are an expert financial analyst and podcast curator. Analyze this podcast transcript from "{podcast_name}" and extract structured investment insights.

TRANSCRIPT:
{transcript_content}

Please provide your analysis in this exact JSON format:
{{
  "episode_title": "Full episode title (infer from content or use descriptive title)",
  "episode_date": "YYYY-MM-DD (infer from content, or use today's date if unclear)",
  "summary": "2-3 paragraph summary of key investment themes and market insights discussed",
  "key_takeaways": [
    "5-7 bullet points of specific investment insights, market calls, or key arguments made"
  ],
  "key_tickers": ["LIST", "OF", "TICKERS", "MENTIONED"],
  "investment_thesis": "1-2 sentence summary of the core investment opportunity or thesis presented",
  "relevance_score": 85,
  "ticker_mentions": [
    {{
      "ticker": "TICKER",
      "context": "Specific context from transcript about this ticker (1-2 sentences)",
      "sentiment": "bullish|bearish|neutral",
      "conviction_score": 75,
      "timeframe": "short_term|medium_term|long_term",
      "is_contrarian": false,
      "is_disruption_focused": false
    }}
  ]
}}

Scoring guidelines:
- relevance_score: 0-100 based on investment value (90+ for exceptional insights, 70-89 for solid content, <70 for light mentions)
- conviction_score: 0-100 per ticker based on strength of argument (90+ for "deep dive/thesis", 70-89 for strong preference, 50-69 for positive mention, <50 for tracking/watching)
- sentiment: Use explicit statements from speakers, not your inference
- is_contrarian: true if speaker explicitly mentions going against consensus, "unloved", "underowned"
- is_disruption_focused: true if discussing paradigm shifts, game changers, industry transformation

Return ONLY valid JSON. No markdown, no explanations."""

    try:
        if client_type == 'openai':
            model = "gpt-4o-mini"
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "You are a precise financial analyst. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            content = response.choices[0].message.content.strip()
        elif client_type == 'gemini':
            # Gemini API - cheapest option
            model = genai.GenerativeModel('gemini-1.5-flash')
            response = model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.3,
                    max_output_tokens=4000
                )
            )
            content = response.text.strip()
        else:
            raise ValueError(f"Unknown client type: {client_type}")
        
        # Clean up any markdown code blocks
        if content.startswith('```json'):
            content = content[7:]
        if content.startswith('```'):
            content = content[3:]
        if content.endswith('```'):
            content = content[:-3]
        content = content.strip()
        
        return json.loads(content)
        
    except Exception as e:
        print(f"    ⚠ AI analysis failed: {e}")
        return None


def episode_exists_in_db(db, podcast_name: str, episode_title: str, rss_guid: str = None) -> bool:
    """Check if an episode already exists in database.
    
    Priority:
    1. rss_guid match (canonical, bulletproof)
    2. Exact podcast_name + episode_title match
    3. Fuzzy title match (first 50 chars, case-insensitive)
    """
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(str(Path.home() / ".openclaw/workspace/pipeline/dashboard.db"))

        # 1. GUID match — most reliable
        if rss_guid:
            row = conn.execute(
                "SELECT id FROM podcast_episodes WHERE rss_guid = ?", (rss_guid,)
            ).fetchone()
            if row:
                conn.close()
                return True

        # 2. Exact title match
        row = conn.execute(
            "SELECT id FROM podcast_episodes WHERE podcast_name = ? AND episode_title = ?",
            (podcast_name, episode_title)
        ).fetchone()
        if row:
            conn.close()
            return True

        # 3. Fuzzy title match (first 50 chars)
        row = conn.execute(
            """SELECT id FROM podcast_episodes
               WHERE podcast_name = ?
               AND LOWER(SUBSTR(episode_title, 1, 50)) = LOWER(SUBSTR(?, 1, 50))""",
            (podcast_name, episode_title)
        ).fetchone()
        conn.close()
        return row is not None

    except Exception as e:
        print(f"    ⚠ Failed to check database: {e}")
        return False


def process_transcript_file(transcript_path: Path, client_info, db) -> Optional[int]:
    """Process a single transcript file and add to database."""
    
    if is_transcript_processed(transcript_path):
        print(f"  ⏭ Skipping {transcript_path.name} (already processed)")
        return None
    
    print(f"  Processing {transcript_path.name}...")

    # Read transcript
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"    ✗ Failed to read: {e}")
        return None
    
    if len(content) < 500:
        print(f"    ⏭ Too short, skipping")
        return None

    # Parse podcast info (pass content for fallback content-based detection)
    podcast_name, episode_slug = parse_podcast_info(transcript_path.name, content)

    # Load sidecar metadata (rss_guid, published_date, etc.)
    meta_file = transcript_path.parent / f"{transcript_path.stem}.meta.json"
    sidecar = {}
    if meta_file.exists():
        try:
            with open(meta_file) as mf:
                sidecar = json.load(mf)
        except Exception:
            pass
    rss_guid = sidecar.get('rss_guid', '') or ''

    # Get a preview of the episode title from the first line
    first_line = content.strip().split('\n')[0][:100] if content else episode_slug
    
    # Check if this episode already exists in database (guid first, then title)
    if episode_exists_in_db(db, podcast_name, first_line, rss_guid):
        print(f"    ⏭ Episode already in database (duplicate), skipping")
        mark_transcript_processed(transcript_path, -1)  # Mark as processed to avoid re-checking
        return None
    
    # Analyze with AI
    analysis = analyze_transcript_with_ai(client_info, content, podcast_name)
    if not analysis:
        print(f"    ✗ AI analysis failed")
        return None
    
    # Parse date
    ep_date_str = analysis.get('episode_date', '')
    try:
        episode_date = datetime.strptime(ep_date_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        episode_date = extract_date_from_content(content) or date.today()
    
    # Extract episode title from AI analysis
    episode_title = analysis.get('episode_title', episode_slug.replace('_', ' ').title())
    
    # CRITICAL: Check database again with the AI-extracted title (more accurate)
    if episode_exists_in_db(db, podcast_name, episode_title, rss_guid):
        print(f"    ⏭ Episode '{episode_title[:60]}...' already in database, skipping")
        mark_transcript_processed(transcript_path, -1)
        return None
    
    # Use published_date from sidecar if available (more accurate than AI-extracted date)
    published_date = sidecar.get('published_date', '')
    if published_date:
        try:
            episode_date = datetime.strptime(published_date, '%Y-%m-%d').date()
        except Exception:
            pass  # keep AI-extracted date

    # Create PodcastEpisode
    episode = PodcastEpisode(
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date=episode_date,
        transcript_path=str(transcript_path),
        summary=analysis.get('summary', '')[:2000],
        key_takeaways=analysis.get('key_takeaways', []),
        key_tickers=analysis.get('key_tickers', []),
        investment_thesis=analysis.get('investment_thesis', '')[:500],
        relevance_score=analysis.get('relevance_score', 70)
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"    ✓ Added episode (ID: {episode_id})")

    # Store rss_guid and published_date from sidecar
    if episode_id and (rss_guid or sidecar.get('published_date')):
        try:
            import sqlite3 as _sqlite3
            _conn = _sqlite3.connect(str(Path.home() / ".openclaw/workspace/pipeline/dashboard.db"))
            _conn.execute(
                "UPDATE podcast_episodes SET rss_guid=?, published_date=? WHERE id=?",
                (rss_guid or None, sidecar.get('published_date') or None, episode_id)
            )
            _conn.commit()
            _conn.close()
        except Exception as e:
            print(f"    ⚠ Could not store rss_guid: {e}")
    
    # Add ticker mentions
    ticker_mentions = analysis.get('ticker_mentions', [])
    added_count = 0
    
    for tm in ticker_mentions:
        try:
            mention = TickerMention(
                ticker=tm.get('ticker', 'UNKNOWN'),
                source_type='podcast',
                source_name=podcast_name,
                episode_title=episode.episode_title,
                context=tm.get('context', '')[:300],
                conviction_score=tm.get('conviction_score', 50),
                sentiment=tm.get('sentiment', 'neutral'),
                timeframe=tm.get('timeframe', 'medium_term'),
                is_contrarian=tm.get('is_contrarian', False),
                is_disruption_focused=tm.get('is_disruption_focused', False)
            )
            db.add_ticker_mention(mention)
            added_count += 1
        except Exception as e:
            print(f"    ⚠ Failed to add mention for {tm.get('ticker')}: {e}")
    
    print(f"    ✓ Added {added_count} ticker mentions")
    
    # Mark as processed
    mark_transcript_processed(transcript_path, episode_id)
    
    return episode_id


def process_all_transcripts() -> Dict[str, any]:
    """Process all unprocessed transcripts in the transcripts directory."""

    print("\n" + "="*60)
    print("Processing Podcast Transcripts with AI")
    print("="*60)

    client_info = get_ai_client()
    if not client_info:
        print("✗ No AI client available. Check your API keys.")
        return {'processed': 0, 'errors': 1}
    
    db = get_db()
    
    # Find all transcript files
    transcript_files = list(TRANSCRIPT_DIR.glob('*.txt'))
    print(f"Found {len(transcript_files)} transcript files")
    
    processed = 0
    skipped = 0
    errors = 0
    
    for transcript_path in transcript_files:
        if is_transcript_processed(transcript_path):
            skipped += 1
            continue
        
        try:
            episode_id = process_transcript_file(transcript_path, client_info, db)
            if episode_id:
                processed += 1
        except Exception as e:
            print(f"  ✗ Error processing {transcript_path.name}: {e}")
            errors += 1
    
    print(f"\n✓ Transcript processing complete: {processed} new, {skipped} skipped, {errors} errors")
    return {
        'processed': processed,
        'skipped': skipped,
        'errors': errors
    }


if __name__ == "__main__":
    result = process_all_transcripts()
    print(f"\nResults: {result}")
