#!/usr/bin/env python3
"""
Extract podcast interviewees from processed episodes and optionally enrich with Wikipedia.
Populates podcast_guests for the site's "Voices" / interviewees section.
Run after analyze_transcript (e.g. in pipeline or manually).
"""

import re
import sys
import json
import urllib.request
import urllib.parse
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db

# Cache file for Wikipedia responses to avoid repeated requests
WIKI_CACHE_DIR = Path.home() / ".openclaw/workspace/pipeline/state"
WIKI_CACHE_DIR.mkdir(parents=True, exist_ok=True)
WIKI_CACHE_FILE = WIKI_CACHE_DIR / "wiki_guest_cache.json"


def _load_wiki_cache():
    if WIKI_CACHE_FILE.exists():
        try:
            with open(WIKI_CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_wiki_cache(cache):
    try:
        with open(WIKI_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=0)
    except Exception:
        pass


def fetch_wikipedia_summary(name: str) -> tuple:
    """Fetch short bio and 'known for' from Wikipedia API. Returns (bio, known_for). Uses cache."""
    cache = _load_wiki_cache()
    key = name.strip().lower()
    if key in cache:
        return cache[key].get("bio"), cache[key].get("known_for")

    bio = None
    known_for = None
    try:
        # Wikipedia API: get page extract (first paragraph) and optional description
        url = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode({
            "action": "query",
            "titles": name,
            "prop": "extract|pageprops",
            "exintro": "1",
            "explaintext": "1",
            "exsentences": "3",
            "redirects": "1",
            "format": "json",
        })
        req = urllib.request.Request(url, headers={"User-Agent": "OpenClaw/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        pages = data.get("query", {}).get("pages", {})
        page = next((p for p in pages.values() if p.get("extract")), None)
        if page:
            bio = (page.get("extract") or "").strip()[:500]
            # "Known for" often in first sentence or from description
            if bio and "." in bio:
                known_for = bio.split(".")[0].strip() + "."
    except Exception:
        pass

    cache[key] = {"bio": bio, "known_for": known_for}
    _save_wiki_cache(cache)
    return bio, known_for


def extract_guest_name(episode_title: str, summary: str, podcast_name: str = "") -> Optional[str]:
    """
    Heuristic extraction of guest/interviewee name from title and summary.
    Returns None if we can't identify a clear guest (e.g. host-only episode).
    """
    title = (episode_title or "").strip()
    summary = (summary or "").strip()

    def ok(name):
        if not name or len(name) < 4 or len(name) > 80:
            return False
        p = (podcast_name or "").lower()
        if p and (name.lower() in p or p in name.lower()):
            return False
        lower = name.lower()
        if any(x in lower for x in ("the panel", "podcast", " episode ", " part 2", " part 1", "openclaw", "monetary matters")):
            return False
        if name.count(",") >= 1 or (len(name) > 45 and not re.match(r"^[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+$", name)):
            return False
        if re.search(r"#\d|^\s*The\s+|\s+and\s+", name, re.I):
            return False
        return True

    # Pattern: "Guest Name: Topic" or "Guest Name | Topic"
    m = re.match(r"^([^:|]+?)\s*[:\|]\s*", title)
    if m:
        name = m.group(1).strip()
        if not name.startswith("The ") and ok(name):
            return name

    # "Topic with Guest Name"
    m = re.search(r"\bwith\s+([A-Z][a-zA-Z\s\.\-]+?)(?:\s*[:\|,]|$|\.)", title)
    if m:
        name = m.group(1).strip()
        if ok(name):
            return name

    # Summary: "X interviews Y" or "Y joins X"
    for pattern in [
        r"(?:interviews?|talks? to|speaks? with)\s+([A-Z][a-zA-Z\s\.\-]+?)(?:\s+about|\.|$)",
        r"([A-Z][a-zA-Z\s\.\-]+?)\s+joins?\s+",
        r"([A-Z][a-zA-Z\s\.\-]+?)\s+discusses?\s+",
        r"(?:guest|interview(?:ee)?)\s+([A-Z][a-zA-Z\s\.\-]+?)(?:\s+on|\.|$)",
    ]:
        m = re.search(pattern, summary, re.I)
        if m:
            name = m.group(1).strip()
            if ok(name):
                return name

    # Title: "First Last" at start
    m = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)?)\s*[:\|\-]", title)
    if m:
        name = m.group(1).strip()
        if ok(name):
            return name

    return None


def main():
    db = get_db()
    # Full refresh: clear and re-extract so heuristics stay current
    with db._get_connection() as conn:
        conn.execute("DELETE FROM podcast_guests")
    with db._get_connection() as conn:
        conn.row_factory = None
        rows = conn.execute("""
            SELECT id, podcast_name, episode_title, episode_date, summary, investment_thesis, key_takeaways
            FROM podcast_episodes
            WHERE is_processed = 1
            ORDER BY episode_date DESC
        """).fetchall()

    print("=" * 60)
    print("Extract Podcast Guests")
    print("=" * 60)
    print(f"Processing {len(rows)} processed episodes")

    for row in rows:
        ep_id, podcast_name, episode_title, episode_date, summary, investment_thesis, key_takeaways = row
        guest = extract_guest_name(episode_title or "", summary or "", podcast_name or "")
        if not guest:
            continue
        guest_clean = guest.strip()

        last_main_idea = (investment_thesis or "").strip()
        if not last_main_idea and key_takeaways:
            try:
                takeaways = json.loads(key_takeaways) if isinstance(key_takeaways, str) else key_takeaways
                last_main_idea = takeaways[0][:400] if takeaways else ""
            except Exception:
                last_main_idea = ""
        last_main_idea = (last_main_idea or "—")[:400]

        bio, known_for = fetch_wikipedia_summary(guest_clean)
        db.upsert_podcast_guest(
            name=guest_clean,
            last_episode_id=ep_id,
            last_episode_title=(episode_title or "")[:200],
            last_podcast_name=(podcast_name or "")[:100],
            last_episode_date=episode_date,
            last_main_idea=last_main_idea,
            bio=bio,
            known_for=known_for,
        )
        with db._get_connection() as conn:
            conn.execute("UPDATE podcast_episodes SET guest_name = ? WHERE id = ?", (guest_clean, ep_id))
        print(f"  ✓ {guest_clean} ← {podcast_name} ({episode_date})")

    count = len(db.get_podcast_guests_for_site(limit=500))
    print(f"\n✓ Done. {count} guest(s) in database.")


if __name__ == "__main__":
    main()
