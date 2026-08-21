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
from workspace_paths import DB_PATH, PROCESSING_MARKER_DIR as PROCESSED_MARKER_DIR, STATE_DIR, TRANSCRIPT_DIR
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

PROCESSED_MARKER_DIR.mkdir(parents=True, exist_ok=True)


def _emerging_term_attributed_speaker(analysis: Dict) -> Optional[str]:
    """Label for 'who' surfaced an emerging term: primary guests, else hosts."""
    guests = analysis.get("guests") or []
    names = [(g.get("name") or "").strip() for g in guests if (g.get("name") or "").strip()]
    if names:
        return ", ".join(names[:3])
    hosts = analysis.get("hosts") or []
    hnames = [(h.get("name") or "").strip() for h in hosts if (h.get("name") or "").strip()]
    if hnames:
        return ", ".join(hnames[:2]) + " (hosts)"
    return None


# Podcast name mappings from filename patterns
PODCAST_PATTERNS = {
    'EWWMN': ('Monetary Matters with Jack Farley', r'EWWMN(\d+)'),
    'IMP': ('The Moonshot Podcast', r'IMP(\d+)'),
    'jack_mallers': ('The Jack Mallers Show', r'jack_mallers'),
    'dario_amodei': ('a16z Live', r'dario_amodei'),
    'elon_musk': ('The Moonshot Podcast', r'elon_musk'),
    'peter_diamandis': ('Moonshots with Peter Diamandis', r'peter_diamandis_(\d+)'),
    'dwarkesh_podcast': ('Dwarkesh Podcast', r'dwarkesh_podcast'),
    'default': ('a16z Live', r'default'),
}

# Content-based podcast detection: scan transcript text for show identity clues
CONTENT_PODCAST_HINTS = [
    (r'welcome to moonshots|moonshot mates|ladies and gentlemen.*moonshots|this is moonshots', 'Moonshots with Peter Diamandis'),
    (r'monetary matters|jack farley', 'Monetary Matters with Jack Farley'),
    (r'network state podcast|balaji srinivasan', 'Network State Podcast'),
    (r'jack mallers show|strike.*bitcoin', 'The Jack Mallers Show'),
    (r'dwarkesh.*patel|patel.*dwarkesh', 'Dwarkesh Podcast'),
    (r'all-in podcast|all in with chamath|bestie', 'All-In Podcast'),
    (r'lex fridman podcast|lex fridman', 'Lex Fridman Podcast'),
    (r'acquired\.fm|acquired podcast|ben gilbert.*david rosenthal', 'Acquired'),
    (r'invest like the best|patrick o\'shaughnessy', 'Invest Like the Best'),
    (r'we study billionaires|the investor\'s podcast', 'We Study Billionaires'),
    (r'bg2pod|bg2 pod|bill gurley|brad gerstner', 'BG2 Pod'),
    (r'latent space|latent\.space|ai engineer podcast', 'Latent Space: The AI Engineer Podcast'),
    (r'macro voices|macrovoices', 'Macro Voices'),
]


def get_ai_client() -> Optional[any]:
    """Get AI client.
    
    Normal priority:
      1. Moonshot/Kimi (primary)
      2. Gemini (fallback)
      3. OpenAI (fallback)
    
    For one-off/manual runs you can override this with ANALYZE_BACKEND:
      ANALYZE_BACKEND=openai   -> force OpenAI
      ANALYZE_BACKEND=gemini   -> force Gemini
      ANALYZE_BACKEND=moonshot -> force Moonshot/Kimi
    """

    backend_override = os.environ.get("ANALYZE_BACKEND", "").strip().lower()

    # Helper lambdas so we can reuse the same init logic in both normal and override paths.
    def _init_moonshot():
        from workspace_paths import agent_auth_profiles_path

        auth_profiles_path = agent_auth_profiles_path()
        if not (auth_profiles_path and auth_profiles_path.exists() and OPENAI_AVAILABLE):
            return None
        try:
            with open(auth_profiles_path) as f:
                auth_data = json.load(f)
            profiles = auth_data.get("profiles", {})
            if "moonshot:default" in profiles:
                profile = profiles["moonshot:default"]
                if profile.get("type") == "api_key":
                    kimi_key = profile.get("key", "")
                    if kimi_key:
                        client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
                        print("  Using Moonshot/Kimi API")
                        return ("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot init failed: {e}")
        return None

    def _init_moonshot_env():
        """Moonshot from MOONSHOT_API_KEY in environment (.env)."""
        kimi_key = os.environ.get("MOONSHOT_API_KEY", "").strip()
        if not (kimi_key and OPENAI_AVAILABLE):
            return None
        try:
            client = OpenAI(api_key=kimi_key, base_url="https://api.moonshot.ai/v1")
            print("  Using Moonshot/Kimi API (MOONSHOT_API_KEY)")
            return ("moonshot", client)
        except Exception as e:
            print(f"  ⚠ Moonshot env init failed: {e}")
        return None

    def _init_gemini():
        gemini_key = os.environ.get("GEMINI_API_KEY")
        if not (gemini_key and GEMINI_AVAILABLE):
            return None
        try:
            genai.configure(api_key=gemini_key)
            print("  Using Gemini API")
            return ("gemini", gemini_key)
        except Exception as e:
            print(f"  ⚠ Gemini init failed: {e}")
        return None

    def _init_openai():
        openai_key = os.environ.get("OPENAI_API_KEY")
        if not (openai_key and OPENAI_AVAILABLE):
            return None
        try:
            client = OpenAI(api_key=openai_key)
            print("  Using OpenAI API")
            return ("openai", client)
        except Exception as e:
            print(f"  ⚠ OpenAI init failed: {e}")
        return None

    # If an override is requested, try that backend first (and only fall back to the
    # normal priority order if the override is misconfigured).
    if backend_override == "moonshot":
        client = _init_moonshot()
        if client:
            return client
        client = _init_moonshot_env()
        if client:
            return client
    elif backend_override == "gemini":
        client = _init_gemini()
        if client:
            return client
    elif backend_override == "openai":
        client = _init_openai()
        if client:
            return client

    # Normal priority order when no override is set or the override failed.
    client = _init_moonshot()
    if client:
        return client

    client = _init_moonshot_env()
    if client:
        return client

    client = _init_gemini()
    if client:
        return client

    client = _init_openai()
    if client:
        return client

    print("  ⚠ No AI client: set MOONSHOT_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY (or Moonshot in Cursor auth profiles).")
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


def is_hostile_transcript_stem(stem: str) -> bool:
    """True when the transcript basename is a raw URL or URL-encoding, not a stable human slug.

    Anchor/Simplecast sometimes write audio under encoded CDN paths; those stems must never
    become insight titles or 'episode_title' without proper RSS sidecar metadata.
    """
    s = (stem or "").strip()
    if not s:
        return True
    low = s.lower()
    if low.startswith("http"):
        return True
    if "%2f" in low or "%3a" in low or s.count("%") >= 3:
        return True
    if "cloudfront.net" in low or "d3ctxlq" in low:
        return True
    return False


def sidecar_identity_trustworthy(sidecar: dict) -> bool:
    """Enough sidecar metadata to publish (podcast + title, or rss_guid)."""
    if not sidecar:
        return False
    if (sidecar.get("rss_guid") or "").strip():
        return True
    pn = (sidecar.get("podcast_name") or "").strip()
    et = (sidecar.get("episode_title") or "").strip()
    if not et:
        return False
    if pn and pn not in ("Unknown", "Unknown Podcast"):
        return True
    return False


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
        conn = _sqlite3.connect(str(DB_PATH))
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
            _conn = _sqlite3.connect(str(DB_PATH))
            _conn.execute("UPDATE podcast_episodes SET is_processed = 1 WHERE id = ?", (episode_id,))
            _conn.commit()
            _conn.close()
        except Exception as e:
            print(f"    ⚠ Could not set is_processed in DB for episode {episode_id}: {e}")


def analyze_transcript_with_ai(
    client_info,
    transcript_content: str,
    podcast_name: str,
    *,
    content_from_digest: bool = False,
    tracked_terms_glossary: str = "",
) -> Dict:
    """Use AI to extract structured data from transcript.

    If ``content_from_digest`` is True, the text is already an evidence-preserving
    Stage A markdown digest — do not apply lossy sampling.
    """
    
    if client_info is None:
        return None
    
    client_type, client = client_info
    
    # Smart sampling: send beginning + middle + end rather than just truncating top
    # This gives the AI context from across the full episode, not just the intro
    # Skip when using Stage A digest (already compressed, evidence-preserving).
    max_chars = 12000
    if not content_from_digest and len(transcript_content) > max_chars:
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
    
    digest_note = ""
    if content_from_digest:
        digest_note = (
            "NOTE: The following is an evidence-preserving markdown DIGEST (ads/filler removed; "
            "quotes, tickers, and facts retained). Extract insights from this digest.\n\n"
        )

    glossary = (tracked_terms_glossary or "").strip()
    if not glossary:
        glossary = "- (none yet — use Title Case for new coined phrases)"

    prompt = (
        "You are an expert financial analyst and podcast curator. "
        f"Analyze this podcast transcript from \"{podcast_name}\" and extract structured investment insights.\n\n"
        f"{digest_note}"
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
        "      \"term\": \"Canonical phrase exactly as spoken or glossary spelling (see rules below)\",\n"
        "      \"definition\": \"1-2 sentence definition in plain English\",\n"
        "      \"investment_angle\": \"One line: why this matters for capital allocation, risk, or sector positioning\",\n"
        "      \"speaker_quote\": \"Short verbatim line from the transcript (max 200 chars, ASCII only)\"\n"
        "    }\n"
        "  ]\n"
        "}\n\n"
        "EMERGING TERMS — investment concepts for the Overton Window (read carefully):\n\n"
        "Purpose: Capture named frameworks, theses, or coined phrases that change how an investor thinks — NOT every topic mentioned.\n\n"
        "INCLUDE (priority order):\n"
        "- Coined or repeated phrases treated as a unit (e.g. SaaS Apocalypse, Compute Arbitrage, K-shaped recovery)\n"
        "- Established frameworks discussed with a clear argument or trade implication (e.g. Jevon's Paradox applied to AI power, AGI timeline/deployment debate)\n"
        "- Terms where a speaker defines, contrasts, or stakes an investment view on the concept\n\n"
        "EXCLUDE (do not put in emerging_terms):\n"
        "- Bare generic labels with no specific framing: AI, inflation, the Fed, tech stocks, Bitcoin (unless part of a named thesis)\n"
        "- Person names, company names, product names, tickers, podcast names\n"
        "- Restating the episode title or a guest's job title\n"
        "- Vague abstractions with no investable angle (the future, disruption, innovation)\n\n"
        "NORMALIZE (critical — one row per concept):\n"
        "- Use the CANONICAL term spelling below when the concept matches (even if the transcript uses a variant)\n"
        "- Prefer the short form speakers actually use: AGI not artificial general intelligence as a new separate term\n"
        "- Do not emit multiple JSON entries for the same concept under different wordings\n"
        "- Title Case for multi-word concepts; keep standard acronyms uppercase (AGI, ASI, ETF)\n\n"
        "CANONICAL GLOSSARY (reuse exact \"term\" string when the concept matches):\n"
        f"{glossary}\n\n"
        "If nothing qualifies after these rules, return \"emerging_terms\": [].\n\n"
        "Per episode: at most ONE emerging_terms entry per distinct concept. Do not list synonyms or repeats of the same idea.\n"
        "Return at most 5 emerging_terms entries total (prefer 2-4 strong ones over a long list).\n\n"
        "speaker_quote: Required for each entry — the best single line that shows WHY this term matters in this episode "
        "(paraphrase only if verbatim is unavailable; still ASCII).\n\n"
        "Scoring guidelines:\n"
        "- conviction_score: 0-100 per ticker based on strength of argument (90+ for \"deep dive/thesis\", 70-89 for strong preference, 50-69 for positive mention, <50 for tracking/watching)\n"
        "- sentiment: Use explicit statements from speakers, not your inference\n"
        "- is_contrarian: true if speaker explicitly mentions going against consensus, \"unloved\", \"underowned\"\n"
        "- is_disruption_focused: true if discussing paradigm shifts, game changers, industry transformation\n\n"
        "FINAL CHECK (STRICT): Output must be English AND ASCII-only.\n"
        "- Do not output any non-ASCII characters anywhere (no emojis, no smart quotes, no em dashes, no accented letters).\n"
        "- If you would normally write characters like “ ” ’ — … or any non-English symbols, replace them with plain ASCII equivalents.\n\n"
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

        parsed = json.loads(content)

        def _has_non_ascii(obj) -> bool:
            if obj is None:
                return False
            if isinstance(obj, str):
                return any(ord(ch) > 127 for ch in obj)
            if isinstance(obj, list):
                return any(_has_non_ascii(x) for x in obj)
            if isinstance(obj, dict):
                # Keys should also be ASCII in our contract
                return any(_has_non_ascii(k) or _has_non_ascii(v) for k, v in obj.items())
            return False

        if _has_non_ascii(parsed):
            raise ValueError("AI output contains non-ASCII characters (rejecting).")

        return parsed
        
    except Exception as e:
        print(f"    ⚠ AI analysis failed: {e}")
        return None


def episode_exists_in_db(
    db,
    podcast_name: str,
    episode_title: str,
    rss_guid: str = None,
    transcript_stem: str = None,
) -> bool:
    """Check if an episode already exists in database.

    Priority:
    1. rss_guid match (canonical, bulletproof)
    2. Exact podcast_name + episode_title match
    3. Fuzzy title match (first 50 chars, case-insensitive)

    When rss_guid is missing, steps 2–3 require the same transcript file (stem match on
    ``transcript_path``) so generic AI-inferred titles cannot collide across different episodes.
    """
    import sqlite3 as _sqlite3
    try:
        conn = _sqlite3.connect(str(DB_PATH))

        # 1. GUID match — most reliable
        if rss_guid:
            row = conn.execute(
                "SELECT id FROM podcast_episodes WHERE rss_guid = ?", (rss_guid,)
            ).fetchone()
            if row:
                conn.close()
                return True

        stem_clause = ""
        stem_param: tuple = ()
        if transcript_stem and not (rss_guid or "").strip():
            stem_clause = " AND transcript_path IS NOT NULL AND transcript_path LIKE ?"
            stem_param = (f"%{transcript_stem}%",)

        # 2. Exact title match
        row = conn.execute(
            "SELECT id FROM podcast_episodes WHERE podcast_name = ? AND episode_title = ?"
            + stem_clause,
            (podcast_name, episode_title) + stem_param,
        ).fetchone()
        if row:
            conn.close()
            return True

        # 3. Fuzzy title match (first 50 chars)
        row = conn.execute(
            """SELECT id FROM podcast_episodes
               WHERE podcast_name = ?
               AND LOWER(SUBSTR(episode_title, 1, 50)) = LOWER(SUBSTR(?, 1, 50))"""
            + stem_clause,
            (podcast_name, episode_title) + stem_param,
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

    # Load sidecar before podcast inference so we can require trustworthy RSS metadata
    # for URL-encoded / CDN transcript filenames (prevents "Unknown Podcast" + URL titles).
    meta_file = transcript_path.parent / f"{transcript_path.stem}.meta.json"
    sidecar = {}
    if meta_file.exists():
        try:
            with open(meta_file) as mf:
                sidecar = json.load(mf)
        except Exception:
            pass

    podcast_name, episode_slug = parse_podcast_info(transcript_path.name, content)
    sc_pod = (sidecar.get("podcast_name") or "").strip()
    if sc_pod and sc_pod not in ("Unknown", "Unknown Podcast"):
        podcast_name = sc_pod

    stem = transcript_path.stem
    if is_hostile_transcript_stem(stem) and not sidecar_identity_trustworthy(sidecar):
        print(
            "    ⏭ Skipping: filename is URL-encoded/CDN; add rss_guid or "
            "(podcast_name + episode_title) to sidecar .meta.json before analysis."
        )
        mark_transcript_processed(transcript_path, -1)
        return None

    if podcast_name in ("Unknown Podcast", "Unknown") and not sidecar_identity_trustworthy(sidecar):
        print(
            "    ⏭ Skipping: podcast unknown and sidecar lacks rss_guid or "
            "podcast_name + episode_title (cannot attribute episode safely)."
        )
        mark_transcript_processed(transcript_path, -1)
        return None

    rss_guid = sidecar.get("rss_guid", "") or ""

    published_raw = sidecar.get("published_date") or sidecar.get("published") or ""
    sidecar_has_date = bool(published_raw)

    # Get a preview of the episode title from the first line
    first_line = content.strip().split('\n')[0][:100] if content else episode_slug
    # If we don't have a stable rss_guid from the sidecar, the first transcript line
    # may be generic (and can trigger false duplicate matches). In that case, prefer
    # the filename-derived slug as the dedupe key so we don't accidentally skip.
    lookup_title_for_dedupe = first_line if rss_guid else episode_slug
    
    transcript_stem = transcript_path.stem
    # Check if this episode already exists in database (guid first, then title)
    if episode_exists_in_db(
        db, podcast_name, lookup_title_for_dedupe, rss_guid, transcript_stem=transcript_stem
    ):
        print(f"    ⏭ Episode already in database (duplicate), skipping")
        mark_transcript_processed(transcript_path, -1)  # Mark as processed to avoid re-checking
        return None
    
    # Optional Stage A: evidence-preserving markdown digest (cheap LLM) for long episodes
    analysis_source = content
    used_digest = False
    try:
        from transcript_digest import ensure_digest_file

        dp = ensure_digest_file(transcript_path, podcast_name, content, force=False)
        if dp is not None and dp.exists():
            analysis_source = dp.read_text(encoding="utf-8")
            used_digest = True
    except Exception as exc:
        print(f"    ⚠ transcript_digest skipped: {exc}")

    # Analyze with AI (full transcript or Stage A digest)
    from term_alias_util import build_tracked_terms_glossary

    db_for_glossary = get_db()
    db_for_glossary.seed_term_aliases_from_json()
    glossary = build_tracked_terms_glossary(db_for_glossary)
    analysis = analyze_transcript_with_ai(
        client_info,
        analysis_source,
        podcast_name,
        content_from_digest=used_digest,
        tracked_terms_glossary=glossary,
    )
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

    # RSS/curation sidecar wins over LLM-inferred titles (single source of truth for display).
    sidecar_episode_title = (sidecar.get("episode_title") or "").strip()
    if sidecar_episode_title:
        episode_title = sidecar_episode_title

    title_s = (episode_title or "").strip()
    if re.search(r"%[0-9a-fA-F]{2}", title_s) or title_s.lower().startswith("http") or "cloudfront.net" in title_s.lower():
        print("    ⏭ Skipping: episode title still looks like a URL/encoding artifact after sidecar/AI merge.")
        mark_transcript_processed(transcript_path, -1)
        return None
    
    # CRITICAL: Check database again with the final title (sidecar or AI/derived)
    if episode_exists_in_db(
        db, podcast_name, episode_title, rss_guid, transcript_stem=transcript_stem
    ):
        print(f"    ⏭ Episode '{episode_title[:60]}...' already in database, skipping")
        mark_transcript_processed(transcript_path, -1)
        return None
    
    # Use published date from sidecar if available (more accurate than AI-extracted date).
    # We support both \"published_date\" (YYYY-MM-DD) and \"published\" (full timestamp) keys.
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

    # Ingest emerging terms from AI into suggested_terms (Overton candidate pipeline)
    from term_alias_util import dedupe_emerging_terms

    source_context = f"{podcast_name} • {episode_title[:80]}"
    detected_by = _emerging_term_attributed_speaker(analysis)
    for et in dedupe_emerging_terms(analysis.get("emerging_terms") or [], db):
        term = (et.get("term") or "").strip()
        if not term:
            continue
        definition = (et.get("definition") or "").strip() or None
        investment_angle = (et.get("investment_angle") or "").strip() or None
        speaker_quote = (et.get("speaker_quote") or "").strip() or None
        if db.upsert_suggested_term_from_ai(
            term,
            definition,
            investment_angle,
            source_context,
            episode_id=episode_id,
            detected_by=detected_by,
            speaker_quote=speaker_quote,
        ):
            print(f"    + Emerging term: {term[:50]}")

    # Recurring vocabulary: scan transcript for known Overton/suggested terms (per episode)
    try:
        from term_mention_scan import record_episode_mentions

        transcript_text = transcript_path.read_text(encoding="utf-8", errors="ignore")
        n_scan, scanned = record_episode_mentions(
            db,
            transcript=transcript_text,
            episode_id=episode_id,
            detected_by=detected_by,
        )
        if n_scan:
            print(f"    + Tracked term mentions ({n_scan}): {', '.join(scanned[:5])}" +
                  (f" +{n_scan - 5} more" if n_scan > 5 else ""))
    except Exception as exc:
        print(f"    ⚠ Term mention scan skipped: {exc}")

    # Store rss_guid and published_date from sidecar
    if episode_id and (rss_guid or sidecar.get('published_date')):
        try:
            import sqlite3 as _sqlite3
            _conn = _sqlite3.connect(str(DB_PATH))
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
    failures_path = STATE_DIR / "analysis_failures.json"
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
