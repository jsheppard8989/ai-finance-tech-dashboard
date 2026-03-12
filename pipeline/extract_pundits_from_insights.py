#!/usr/bin/env python3
"""
Extract primary podcast guests ("pundits") from Insight summaries.

We treat the opening sentence of latest_insights.summary as the source of truth
for primary guests, using patterns like:
- "This episode features A and B ..."
- "In this episode, host X interviews Y ..."

For each detected guest name, we:
- upsert into entities (type='person')
- insert an appearance with role='guest_primary' for that episode

Podcast Pundits on the site will then be driven from these guest_primary
appearances, not from raw transcript-based entity extraction.
"""

from __future__ import annotations

import re
from pathlib import Path

from db_manager import get_db
from ingest_ai_analysis import upsert_entity, insert_appearance


# Known hosts or show names to exclude from Pundits, case-insensitive
HOST_BLOCKLIST = {
    "chamath", "jason", "sacks", "friedberg",
    "jack farley",
    "peter diamandis",
    "ben horowitz",  # often host on some shows
    "andrew bosworth", "bosworth",
}


def extract_names_from_intro(sentence: str) -> list[str]:
    """
    Given the first sentence of an insight summary, try to extract primary guest names.
    Heuristics:
    - Look for "features ...", "episode features ...", "interviews ...", "with ...".
    - Split trailing portion on "and" / commas.
    """
    s = sentence.strip()
    if not s:
        return []

    lowered = s.lower()
    tail = ""

    # Preferred patterns
    for kw in ["features", "feature", "episode features", "show features"]:
        idx = lowered.find(kw + " ")
        if idx != -1:
            tail = s[idx + len(kw) + 1 :]
            break

    # Fallbacks if no "features"
    if not tail:
        for kw in ["interviews", "interviewing"]:
            idx = lowered.find(kw + " ")
            if idx != -1:
                tail = s[idx + len(kw) + 1 :]
                break

    if not tail:
        for kw in ["conversation with", "talks to", "talks with", "speaks with"]:
            idx = lowered.find(kw + " ")
            if idx != -1:
                tail = s[idx + len(kw) + 1 :]
                break

    if not tail:
        return []

    # Stop at typical end markers
    for marker in [" about ", " on ", " discussing ", " who ", " that "]:
        m_idx = tail.lower().find(marker)
        if m_idx != -1:
            tail = tail[:m_idx]
            break

    # Normalize separators: "A and B" -> "A, B"
    tail = tail.replace(" and ", ", ")
    parts = [p.strip() for p in tail.split(",") if p.strip()]

    names: list[str] = []
    for p in parts:
        # Require at least one space (First Last) and some capital letters
        if len(p) < 4 or " " not in p:
            continue
        # Drop trailing words like "Jr.", "PhD", etc. lightly
        p_clean = re.sub(r"\b(Jr\.?|Sr\.?|PhD|MD|Dr\.)\b", "", p).strip()
        if not p_clean:
            continue
        # Filter hosts/show names
        if any(block in p_clean.lower() for block in HOST_BLOCKLIST):
            continue
        names.append(p_clean)

    return names


def main() -> None:
    db = get_db()
    with db._get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, title, summary, podcast_episode_id
            FROM latest_insights
            WHERE source_type = 'podcast'
              AND podcast_episode_id IS NOT NULL
            ORDER BY source_date DESC, id DESC
            """
        ).fetchall()

    total_names = 0
    for row in rows:
        row = dict(row)
        summary = row.get("summary") or ""
        ep_id = row.get("podcast_episode_id")
        if not summary or ep_id is None:
            continue
        first_sentence = summary.split(".")[0]
        names = extract_names_from_intro(first_sentence)
        if not names:
            continue

        print(f"Insight {row['id']} ({row['title'][:60]}...): extracted guests -> {names}")

        for name in names:
            entity_id = upsert_entity(name=name, type_="person")
            insert_appearance(
                entity_id=entity_id,
                source_type="podcast",
                source_id=ep_id,
                role="guest_primary",
                prominence=3,
            )
            total_names += 1

    print(f"\n✓ Extracted and recorded {total_names} guest_primary appearance(s) from insights.")


if __name__ == "__main__":
    main()

