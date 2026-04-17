#!/usr/bin/env python3
"""
Purge existing Podcast Pundits data and re-run guest/host analysis
for a set of recent podcast episodes that are already in the database.

This is a one-off helper to rebuild the semantic-layer pundits list.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Tuple

from db_manager import DB_PATH
import analyze_transcript as at
from ingest_ai_analysis import upsert_entity, insert_appearance
from person_name_safety import is_placeholder_person_name
from pundit_exclusions import is_excluded_pundit_name


def purge_podcast_pundits() -> None:
    """Delete all podcast-based appearances and orphaned entities."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        # Remove all podcast appearances (this is what drives Pundits)
        cur.execute("DELETE FROM appearances WHERE source_type = 'podcast'")
        # Clean up entities that no longer have any appearances
        cur.execute(
            """
            DELETE FROM entities
            WHERE id NOT IN (SELECT DISTINCT entity_id FROM appearances)
            """
        )
        conn.commit()
        print("✓ Purged podcast appearances and cleaned up orphan entities.")
    finally:
        conn.close()


def get_recent_episodes(limit: int = 8) -> List[Tuple[int, str, str]]:
    """Return recent episodes with transcripts: (id, podcast_name, transcript_path)."""
    conn = sqlite3.connect(DB_PATH)
    try:
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, podcast_name, transcript_path
            FROM podcast_episodes
            WHERE transcript_path IS NOT NULL AND transcript_path != ''
            ORDER BY COALESCE(episode_date, '1970-01-01') DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [(r[0], r[1], r[2]) for r in rows]
    finally:
        conn.close()


def ingest_guests_and_hosts(episode_id: int, podcast_name: str, analysis: dict) -> None:
    """Ingest guests and hosts arrays from a single AI analysis payload."""
    guests = analysis.get("guests") or []
    hosts = analysis.get("hosts") or []

    if not guests and not hosts:
        print(f"    ⚠ No guests/hosts in AI payload for episode {episode_id} ({podcast_name})")
        return

    for g in guests:
        name = (g.get("name") or "").strip()
        if not name:
            continue
        if is_placeholder_person_name(name) or is_excluded_pundit_name(name):
            continue
        bio = g.get("bio") or None
        known_for = g.get("known_for") or None
        voice_tone = g.get("voice_tone") or None
        voice_style = g.get("voice_style") or None
        voice_delivery_notes = g.get("voice_delivery_notes") or None
        entity_id = upsert_entity(
            name=name,
            type_="person",
            bio=bio,
            known_for=known_for,
            voice_tone=voice_tone,
            voice_style=voice_style,
            voice_delivery_notes=voice_delivery_notes,
        )
        insert_appearance(
            entity_id=entity_id,
            source_type="podcast",
            source_id=episode_id,
            role="guest_primary",
            prominence=3,
        )

    for h in hosts:
        name = (h.get("name") or "").strip()
        if not name:
            continue
        if is_placeholder_person_name(name) or is_excluded_pundit_name(name):
            continue
        entity_id = upsert_entity(name=name, type_="person")
        insert_appearance(
            entity_id=entity_id,
            source_type="podcast",
            source_id=episode_id,
            role="host",
            prominence=1,
        )


def reanalyze_recent(limit: int = 8) -> None:
    """Re-run AI analysis for a handful of recent episodes to rebuild pundits."""
    episodes = get_recent_episodes(limit=limit)
    print(f"Found {len(episodes)} recent episodes to re-analyze (limit={limit}).")
    if not episodes:
        return

    client_info = at.get_ai_client()
    if not client_info:
        print("✗ No AI client available. Check your API keys.")
        return

    for episode_id, podcast_name, transcript_path in episodes:
        path = Path(transcript_path)
        if not path.exists():
            print(f"  ⚠ Transcript missing for episode {episode_id}: {transcript_path}")
            continue

        print(f"\n=== Re-analyzing episode {episode_id}: {podcast_name} ({path.name}) ===")
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            print(f"  ✗ Failed to read transcript {path}: {e}")
            continue

        analysis = at.analyze_transcript_with_ai(client_info, content, podcast_name)
        if not analysis:
            print("  ✗ AI analysis failed or returned no data.")
            continue

        ingest_guests_and_hosts(episode_id, podcast_name, analysis)
        print("  ✓ Guests/hosts ingested.")


def main() -> None:
    purge_podcast_pundits()
    # Rebuild from the most recent episodes; tweak limit if you want more/less.
    reanalyze_recent(limit=8)


if __name__ == "__main__":
    main()

