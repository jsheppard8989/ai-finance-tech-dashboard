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

_NAME_PART = re.compile(r"^(?:Dr\.|Mr\.|Ms\.|Mrs\.|Sen\.|Gov\.|[A-Z][a-z]+(?:[-'][A-Z][a-z]+)?|[A-Z]\.)$")
_ROLE_PREFIX = re.compile(
    r"^(?:banking\s+specialist|host|guest|professor|senator|governor|ceo|chief|nobel\s+prize-winning\s+economist|meta\s+cto)\s+",
    re.I,
)
_QUOTED = re.compile(r'^["\'“”‘’].+["\'“”‘’]$')

_HEADLINE_STOPWORDS = frozenset(
    {
        "the",
        "will",
        "navigating",
        "building",
        "investing",
        "stock",
        "market",
        "ground",
        "infrastructure",
        "from",
        "models",
        "mobility",
        "inventing",
        "renaissance",
        "special",
        "episode",
        "this",
        "also",
        "touches",
        "inside",
        "when",
        "music",
        "stops",
        "openclaw",
        "macro",
        "voices",
        "technology",
        "culture",
        "next",
        "interface",
        "reality",
        "software",
        "hard",
        "asset",
        "banking",
        "specialist",
        "private",
        "boom",
        "apocalypse",
        "capitalism",
        "foundations",
        "shaky",
        "agents",
        "home",
    }
)


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


def _name_parts(name: str) -> list:
    return [p for p in re.split(r"\s+", (name or "").strip()) if p]


def normalize_guest_name(name: str) -> str:
    raw = (name or "").strip()
    m = _ROLE_PREFIX.match(raw)
    if m:
        raw = raw[m.end() :].strip()
    return raw


def is_plausible_person_name(name: str, podcast_name: str = "") -> bool:
    """
    Reject title fragments, quoted headlines, role-prefixed phrases, and non-person strings.
    """
    raw = normalize_guest_name(name)
    if not raw or len(raw) < 4 or len(raw) > 80:
        return False
    if _QUOTED.match(raw):
        return False
    if raw.startswith('"') or raw.startswith("'"):
        return False
    lower = raw.lower()
    if " episode" in lower or lower.startswith("this ") or lower.startswith("also "):
        return False
    p = (podcast_name or "").lower()
    if p and (lower in p or p in lower):
        return False
    if any(x in lower for x in ("the panel", "podcast", " part 2", " part 1", "monetary matters")):
        return False
    if raw.count(",") >= 1:
        return False
    if re.search(r"#\d|^\s*The\s+|\s+and\s+the\s+", raw, re.I):
        return False

    parts = _name_parts(raw)
    if not parts:
        return False
    if len(parts) > 5:
        return False

    name_like = [p for p in parts if _NAME_PART.match(p)]
    if len(name_like) < 2:
        return False

    stop_hits = sum(1 for p in parts if p.lower() in _HEADLINE_STOPWORDS)
    if stop_hits >= 2 and stop_hits >= len(parts) - 1:
        return False
    if len(parts) >= 3 and stop_hits >= len(parts) // 2:
        return False

    # Title-case phrase without enough person tokens (e.g. "Ground Infrastructure")
    if len(parts) == 2 and all(p[0].isupper() for p in parts):
        if parts[0].lower() in _HEADLINE_STOPWORDS or parts[1].lower() in _HEADLINE_STOPWORDS:
            return False

    ov = load_overrides()
    if raw in ov.get("overrides", {}):
        return True
    if len(name_like) >= 2 and len(raw) <= 45:
        return True
    if len(name_like) >= 3:
        return True
    return False


def extract_guest_name(episode_title: str, summary: str, podcast_name: str = "") -> Optional[str]:
    """
    Heuristic extraction of guest/interviewee name from title and summary.
    Returns None if we can't identify a clear guest (e.g. host-only episode).
    """
    title = (episode_title or "").strip()
    summary = (summary or "").strip()

    def ok(name):
        cleaned = normalize_guest_name(name)
        return is_plausible_person_name(cleaned, podcast_name)

    def pick(name):
        cleaned = normalize_guest_name(name)
        return cleaned if ok(name) else None

    # "Topic with Guest Name" (prefer before naive "Title: fragment" capture)
    m = re.search(r"\bwith\s+([A-Za-z][a-zA-Z\s\.\-']+?)(?:\s*[:\|,]|$|\.)", title)
    if m:
        name = pick(m.group(1).strip())
        if name:
            return name

    # Pattern: "Guest Name: Topic" or "Guest Name | Topic"
    m = re.match(r"^([^:|]+?)\s*[:\|]\s*", title)
    if m:
        name = pick(m.group(1).strip())
        if name and not name.startswith("The "):
            return name

    # "Topic with Guest Name" in summary
    for pattern in [
        r"(?:interviews?|talks? to|speaks? with)\s+([A-Z][a-zA-Z\s\.\-']+?)(?:\s+about|\.|$)",
        r"([A-Z][a-zA-Z\s\.\-']+?)\s+joins?\s+",
        r"([A-Z][a-zA-Z\s\.\-']+?)\s+discusses?\s+",
        r"(?:guest|interview(?:ee)?)\s+([A-Z][a-zA-Z\s\.\-']+?)(?:\s+on|\.|$)",
    ]:
        m = re.search(pattern, summary, re.I)
        if m:
            name = pick(m.group(1).strip())
            if name:
                return name

    # Title: "First Last" at start
    m = re.match(r"^([A-Z][a-z]+(?:\s+[A-Z][a-z]+)(?:\s+[A-Z][a-z]+)?)\s*[:\|\-]", title)
    if m:
        name = pick(m.group(1).strip())
        if name:
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
