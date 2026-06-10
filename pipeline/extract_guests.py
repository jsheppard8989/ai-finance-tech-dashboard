#!/usr/bin/env python3
"""
Extract podcast interviewees from processed episodes and optionally enrich with Wikipedia.
Populates podcast_guests for the site's "Voices" / interviewees section.
Run after analyze_transcript (e.g. in pipeline or manually).
"""

import re
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent))
from workspace_paths import PIPELINE_DIR
from db_manager import get_db

# Grokipedia-style overrides: curated bios, known-for, fixes, and blocklist
OVERRIDES_PATH = PIPELINE_DIR / "guest_overrides.json"
_OVERRIDES_CACHE = None


def load_overrides():
    global _OVERRIDES_CACHE
    if _OVERRIDES_CACHE is not None:
        return _OVERRIDES_CACHE
    data = {"blocklist": [], "fixes": {}, "overrides": {}}
    if OVERRIDES_PATH.exists():
        try:
            with open(OVERRIDES_PATH, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                data["blocklist"] = raw.get("blocklist", []) or []
                data["fixes"] = raw.get("fixes", {}) or {}
                data["overrides"] = raw.get("overrides", {}) or {}
        except Exception:
            pass
    _OVERRIDES_CACHE = data
    return data


def grokipedia_lookup(name: str) -> tuple:
    """
    Grokipedia-style lookup: use local overrides for bios/known_for and name fixes.
    Returns (fixed_name, bio, known_for, blocked: bool).
    """
    ov = load_overrides()
    raw = name.strip()
    # Blocklist
    if raw in ov["blocklist"]:
        return raw, None, None, True
    # Fixes (None = drop)
    fixed = ov["fixes"].get(raw, raw)
    if fixed is None:
        return raw, None, None, True
    # Curated overrides
    entry = ov["overrides"].get(fixed) or ov["overrides"].get(raw)
    bio = (entry or {}).get("bio")
    known_for = (entry or {}).get("known_for")
    return fixed, bio, known_for, False


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
        if any(x in lower for x in ("the panel", "podcast", " episode ", " part 2", " part 1", "monetary matters")):
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
        guest_clean, bio, known_for, blocked = grokipedia_lookup(guest_clean)
        if blocked:
            continue

        last_main_idea = (investment_thesis or "").strip()
        if not last_main_idea and key_takeaways:
            try:
                takeaways = json.loads(key_takeaways) if isinstance(key_takeaways, str) else key_takeaways
                last_main_idea = takeaways[0][:400] if takeaways else ""
            except Exception:
                last_main_idea = ""
        last_main_idea = (last_main_idea or "—")[:400]
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
