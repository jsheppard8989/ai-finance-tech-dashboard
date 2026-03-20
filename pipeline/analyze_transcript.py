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
from person_name_safety import is_placeholder_person_name
from pundit_exclusions import is_excluded_pundit_name

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
    """Get AI client - tries Moonshot/Kimi FIRST, then Gemini, then OpenAI."""

    # Try Moonshot/Kimi (primary - what the pipeline uses)
    auth_profiles_path = Path.home() / ".openclaw/agents/main/agent/auth-profiles.json"
    if auth_profiles_path.exists() and OPENAI_AVAILABLE:
        try:
            with open(auth_profiles_path) as f:
                auth_data = json.load(f)
            profiles = auth_data.get('profiles', {})
            if 'moonshot:default' in profiles:
                profile = profiles['moonshot:default']
                if profile.get('type') == 'api_key':
                    kimi_key = profile.get('key', '')
                    if kimi_key:
                        client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
                        print("  Using Moonshot/Kimi API (primary)")
                        return ('moonshot', client)
        except Exception as e:
            print(f"  ⚠ Moonshot init failed: {e}")

    # Try Gemini API from environment
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if gemini_key and GEMINI_AVAILABLE:
        try:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API (fallback)")
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
    """Check if transcript has already been processed.
    
    A transcript is considered processed ONLY if:
    - A .processed marker exists AND
    - The referenced podcast_episodes row still exists in the DB (episode_id > 0).
    
    This reconciles marker files with the database so we don't skip episodes
    that never actually made it into podcast_episodes.
    """
    marker_file = PROCESSED_MARKER_DIR / f"{transcript_path.stem}.processed"
    if not marker_file.exists():
        return False

    try:
        with open(marker_file, "r") as f:
            meta = json.load(f)
        episode_id = meta.get("episode_id") or 0
        if not episode_id or episode_id <= 0:
            return False
        import sqlite3 as _sqlite3
        db_path = Path.home() / ".openclaw/workspace/pipeline/dashboard.db"
        conn = _sqlite3.connect(str(db_path))
        cur = conn.execute("SELECT 1 FROM podcast_episodes WHERE id = ?", (episode_id,))
        exists = cur.fetchone() is not None
        conn.close()
        return exists
    except Exception:
        # On any issue validating the marker/DB, treat as unprocessed so we retry.
        return False


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
    
    prompt = (
        "You are an expert financial analyst and podcast curator. "
        f"Analyze this podcast transcript from \"{podcast_name}\" and extract structured investment insights.\n\n"
        "IMPORTANT: Write all of the following in English only (summary, key_takeaways, investment_thesis, guest bios, emerging_terms). "
        "Do not use other languages even if the transcript or topic is in another language.\n\n"
        "TRANSCRIPT:\n"
        f"{transcript_content}\n\n"
        "Please provide your analysis in this exact JSON format:\n"
        "{\n"
        "  \"episode_title\": \"Full episode title (infer from content or use descriptive title)\",\n"
        "  \"episode_date\": \"YYYY-MM-DD (infer from content, or use today's date if unclear)\",\n"
        "  \"summary\": \"2-3 paragraph summary of key investment themes and market insights discussed\",\n"
        "  \"key_takeaways\": [\n"
        "    \"5-7 bullet points of specific investment insights, market calls, or key arguments made\"\n"
        "  ],\n"
        "  \"key_tickers\": [\"LIST\", \"OF\", \"TICKERS\", \"MENTIONED\"],\n"
        "  \"investment_thesis\": \"1-2 sentence summary of the core investment opportunity or thesis presented\",\n"
        "  \"guests\": [\n"
        "    {\n"
        "      \"name\": \"Full name of a main guest/interviewee (must be confidently extractable from the intro; at least 2 tokens like First Last). If you are NOT confident, omit this guest entirely (do not use placeholders like 'Guest Expert' or single-token names).\",\n"
        "      \"role\": \"guest\",\n"
        "      \"bio\": \"1-2 sentence bio (optional, only for important guests)\",\n"
        "      \"known_for\": \"Short 'known for' line for investors (optional)\",\n"
        "      \"voice_tone\": \"Short phrase about speaking tone from this transcript only (optional)\",\n"
        "      \"voice_style\": \"One sentence on argument/rhetorical style from this transcript only (optional)\",\n"
        "      \"voice_delivery_notes\": \"One sentence with pacing/emphasis guidance for TTS scripts (optional)\"\n"
        "    }\n"
        "  ],\n"
        "  \"hosts\": [\n"
        "    {\n"
        "      \"name\": \"Full name of a recurring show host\",\n"
        "      \"role\": \"host\"\n"
        "    }\n"
        "  ],\n"
        "  \"ticker_mentions\": [\n"
        "    {\n"
        "      \"ticker\": \"TICKER\",\n"
        "      \"context\": \"Specific context from transcript about this ticker (1-2 sentences)\",\n"
        "      \"sentiment\": \"bullish|bearish|neutral\",\n"
        "      \"conviction_score\": 75,\n"
        "      \"timeframe\": \"short_term|medium_term|long_term\",\n"
        "      \"is_contrarian\": false,\n"
        "      \"is_disruption_focused\": false\n"
        "    }\n"
        "  ],\n"
        "  \"emerging_terms\": [\n"
        "    {\n"
        "      \"term\": \"Concept or phrase (e.g. Compute Arbitrage, Regulatory Moat)\",\n"
        "      \"definition\": \"1-2 sentence definition\",\n"
        "      \"investment_angle\": \"One line for investors\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "Scoring guidelines:\n"
        "- conviction_score: 0-100 per ticker based on strength of argument (90+ for \"deep dive/thesis\", 70-89 for strong preference, 50-69 for positive mention, <50 for tracking/watching)\n"
        "- sentiment: Use explicit statements from speakers, not your inference\n"
        "- is_contrarian: true if speaker explicitly mentions going against consensus, \"unloved\", \"underowned\"\n"
        "- is_disruption_focused: true if discussing paradigm shifts, game changers, industry transformation\n\n"
        "Return ONLY valid JSON. No markdown, no explanations."
    )

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
        elif client_type == 'moonshot':
            # Moonshot/Kimi API (OpenAI-compatible)
            response = client.chat.completions.create(
                model="moonshot-v1-8k",
                messages=[
                    {"role": "system", "content": "You are a precise financial analyst. Return only valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            content = response.choices[0].message.content.strip()
        elif client_type == 'gemini':
            # Gemini API
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
    # If we don't have a stable rss_guid from the sidecar, the first transcript line
    # may be generic (and can trigger false duplicate matches). In that case, prefer
    # the filename-derived slug as the dedupe key so we don't accidentally skip.
    lookup_title_for_dedupe = first_line if rss_guid else episode_slug
    
    # Check if this episode already exists in database (guid first, then title)
    if episode_exists_in_db(db, podcast_name, lookup_title_for_dedupe, rss_guid):
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
    
    # Extract episode title from AI analysis.
    # If we are missing RSS sidecar meta entirely, the AI sometimes infers a
    # generic title; in that case we derive a title from the transcript
    # filename slug (much closer to the curated title we show in pipeline).
    episode_title_ai = analysis.get('episode_title', episode_slug.replace('_', ' ').title())
    episode_title = episode_title_ai
    if not rss_guid and not sidecar_has_date:
        # Derive from filename stem: strip "podcast name" slug prefix if present.
        podcast_slug = re.sub(r'[^a-z0-9]+', '_', (podcast_name or '').lower()).strip('_')
        derived = episode_slug
        if podcast_slug and derived.lower().startswith(podcast_slug):
            derived = derived[len(podcast_slug):].lstrip('_')

        derived = derived.replace('_', ' ')
        # File stems often include an audio hash like "...___moo_609f0b8d" which we drop.
        derived = re.sub(r'\bmoo[\s_]*[a-z0-9]+\b', '', derived, flags=re.IGNORECASE)
        derived = re.sub(r'\s+', ' ', derived).strip()
        # Common token fix: "gpt 5 4" => "GPT 5.4"
        derived = re.sub(r'\bgpt\s+(\d+)\s+(\d+)\b', r'GPT \\1.\\2', derived, flags=re.IGNORECASE)
        episode_title = derived if derived else episode_title_ai
    
    # CRITICAL: Check database again with the AI-extracted title (more accurate)
    if episode_exists_in_db(db, podcast_name, episode_title, rss_guid):
        print(f"    ⏭ Episode '{episode_title[:60]}...' already in database, skipping")
        mark_transcript_processed(transcript_path, -1)
        return None
    
    # Use published date from sidecar if available (more accurate than AI-extracted date).
    # We support both \"published_date\" (YYYY-MM-DD) and \"published\" (full timestamp) keys.
    published_raw = sidecar.get('published_date') or sidecar.get('published') or ''
    sidecar_has_date = bool(published_raw)
    if published_raw:
        try:
            # Normalise to YYYY-MM-DD first when possible
            s = str(published_raw).strip()
            if len(s) >= 10:
                s = s[:10]
            episode_date = datetime.strptime(s, '%Y-%m-%d').date()
        except Exception:
            # If parsing fails, keep the previously derived episode_date
            pass

    # Hard stop: do not analyze or add to DB anything before Feb 2026.
    # If we don't have a sidecar published date, the AI-derived date can be wrong
    # (we'd otherwise skip legitimate recent episodes and then pipeline-health
    # will forever show "Not in DB yet" for that RSS item).
    try:
        from cutoff_date import CUTOFF_DATE_ISO
        from datetime import date as _date
        cutoff = _date.fromisoformat(CUTOFF_DATE_ISO)
        if episode_date < cutoff:
            if sidecar_has_date:
                print(
                    f"    ⏭ Skipping (published {episode_date} is before Feb 2026 cutoff; sidecar date present)"
                )
                mark_transcript_processed(transcript_path, -1)
                return None
            # Clamp: trust "recentness" more than AI date when we have no sidecar.
            episode_date = date.today()
            print(
                f"    ⚠ Clamping episode_date to {episode_date} (AI inferred {analysis.get('episode_date','')} < cutoff; no sidecar date)"
            )
    except Exception:
        pass

    # Derive key tickers directly from structured ticker_mentions.
    # If none are present, we intentionally leave key_tickers empty
    # so that no tickers are shown on the Insight card.
    raw_ticker_mentions = analysis.get('ticker_mentions', []) or []
    key_tickers_structured: list[str] = []
    seen_tickers = set()
    for tm in raw_ticker_mentions:
        ticker = (tm.get('ticker') or '').strip().upper()
        if not ticker:
            continue
        if ticker in seen_tickers:
            continue
        seen_tickers.add(ticker)
        key_tickers_structured.append(ticker)
        if len(key_tickers_structured) >= 6:
            break

    # Create PodcastEpisode
    episode = PodcastEpisode(
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date=episode_date,
        transcript_path=str(transcript_path),
        summary=analysis.get('summary', '')[:2000],
        key_takeaways=analysis.get('key_takeaways', []),
        key_tickers=key_tickers_structured,
        investment_thesis=analysis.get('investment_thesis', '')[:500],
        relevance_score=80  # Fixed baseline; no AI-calculated relevance
    )
    
    episode_id = db.add_podcast_episode(episode)
    print(f"    ✓ Added episode (ID: {episode_id})")

    # Ingest guests/hosts into semantic layer (entities + appearances)
    from ingest_ai_analysis import upsert_entity, insert_appearance  # local import to avoid cycles

    guests = analysis.get('guests') or []
    hosts = analysis.get('hosts') or []

    for g in guests:
        name = (g.get('name') or '').strip()
        if not name:
            continue
        # Skip clearly placeholder-ish names (LLM extraction artifacts).
        if is_placeholder_person_name(name):
            continue
        if is_excluded_pundit_name(name):
            continue
        bio = g.get('bio') or None
        known_for = g.get('known_for') or None
        voice_tone = g.get('voice_tone') or None
        voice_style = g.get('voice_style') or None
        voice_delivery_notes = g.get('voice_delivery_notes') or None
        entity_id = upsert_entity(
            name=name,
            type_='person',
            bio=bio,
            known_for=known_for,
            voice_tone=voice_tone,
            voice_style=voice_style,
            voice_delivery_notes=voice_delivery_notes,
        )
        insert_appearance(
            entity_id=entity_id,
            source_type='podcast',
            source_id=episode_id,
            role='guest_primary',
            prominence=3,
        )

    for h in hosts:
        name = (h.get('name') or '').strip()
        if not name:
            continue
        # Skip placeholders for hosts too (prevents bogus pundits).
        if is_placeholder_person_name(name):
            continue
        if is_excluded_pundit_name(name):
            continue
        entity_id = upsert_entity(name=name, type_='person')
        insert_appearance(
            entity_id=entity_id,
            source_type='podcast',
            source_id=episode_id,
            role='host',
            prominence=1,
        )

    # Ingest emerging terms from AI into suggested_terms (Emerging Terms box)
    source_context = f"{podcast_name} • {episode_title[:80]}"
    for et in analysis.get('emerging_terms') or []:
        term = (et.get('term') or '').strip()
        if not term:
            continue
        definition = (et.get('definition') or '').strip() or None
        investment_angle = (et.get('investment_angle') or '').strip() or None
        if db.upsert_suggested_term_from_ai(term, definition, investment_angle, source_context):
            print(f"    + Emerging term: {term[:50]}")

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
    
    # Load existing analysis failures (if any)
    failures_path = Path.home() / ".openclaw/workspace/pipeline/state/analysis_failures.json"
    try:
        if failures_path.exists():
            with open(failures_path, "r") as f:
                analysis_failures = json.load(f)
        else:
            analysis_failures = {}
    except Exception:
        analysis_failures = {}
    
    def record_failure(stem: str, code: str, detail: str):
        analysis_failures[stem] = {
            "last_failed_at": datetime.now().isoformat(),
            "reason_code": code,
            "reason_detail": detail,
        }
    
    for transcript_path in transcript_files:
        if is_transcript_processed(transcript_path):
            skipped += 1
            continue
        
        try:
            episode_id = process_transcript_file(transcript_path, client_info, db)
            if episode_id:
                processed += 1
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            print(f"  ✗ Error processing {transcript_path.name}: {msg}")
            errors += 1
            stem = transcript_path.stem
            # Rough classification for now
            code = "analysis_error"
            record_failure(stem, code, msg[:300])
    
    # Persist failures, if any
    try:
        failures_path.parent.mkdir(parents=True, exist_ok=True)
        with open(failures_path, "w") as f:
            json.dump(analysis_failures, f, indent=2)
    except Exception as e:
        print(f"  ⚠ Could not write analysis_failures.json: {e}")

    print(f"\n✓ Transcript processing complete: {processed} new, {skipped} skipped, {errors} errors")
    return {
        'processed': processed,
        'skipped': skipped,
        'errors': errors
    }


if __name__ == "__main__":
    result = process_all_transcripts()
    print(f"\nResults: {result}")
