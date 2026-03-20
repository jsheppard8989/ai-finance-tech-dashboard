#!/usr/bin/env python3
"""
Helpers to ingest AI analysis (people + ideas) into the semantic layer tables:
entities, appearances, and ideas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Any

from db_manager import get_db
from person_name_safety import is_placeholder_person_name


def upsert_entity(name: str, type_: str = "person", bio: str | None = None,
                  known_for: str | None = None, source_url: str | None = None,
                  voice_tone: str | None = None, voice_style: str | None = None,
                  voice_delivery_notes: str | None = None) -> int:
    """
    Upsert an entity by name + type. Returns entity_id.
    """
    db = get_db()
    name_clean = (name or "").strip()
    if not name_clean:
        raise ValueError("Entity name cannot be empty")

    with db._get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, bio, known_for, source_url, voice_tone, voice_style, voice_delivery_notes
            FROM entities
            WHERE LOWER(name) = LOWER(?) AND type = ?
            """,
            (name_clean, type_),
        ).fetchone()
        if row:
            # Prefer to keep existing bio/known_for unless new values are provided
            new_bio = bio or row["bio"]
            new_known_for = known_for or row["known_for"]
            new_source_url = source_url or row["source_url"]
            new_voice_tone = voice_tone or row["voice_tone"]
            new_voice_style = voice_style or row["voice_style"]
            new_voice_delivery = voice_delivery_notes or row["voice_delivery_notes"]
            conn.execute(
                """
                UPDATE entities
                SET bio = ?, known_for = ?, source_url = ?,
                    voice_tone = ?, voice_style = ?, voice_delivery_notes = ?,
                    voice_profile_updated_at = CASE
                      WHEN ? IS NOT NULL OR ? IS NOT NULL OR ? IS NOT NULL THEN CURRENT_TIMESTAMP
                      ELSE voice_profile_updated_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    new_bio, new_known_for, new_source_url,
                    new_voice_tone, new_voice_style, new_voice_delivery,
                    voice_tone, voice_style, voice_delivery_notes,
                    row["id"],
                ),
            )
            return row["id"]

        # Insert new entity
        import re

        slug = re.sub(r"[^\w\s-]", "", name_clean).strip().lower().replace(" ", "-")[:80] or "entity"
        cursor = conn.execute(
            """
            INSERT INTO entities (
              name, type, slug, bio, known_for, source_url,
              voice_tone, voice_style, voice_delivery_notes, voice_profile_updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CASE
              WHEN ? IS NOT NULL OR ? IS NOT NULL OR ? IS NOT NULL THEN CURRENT_TIMESTAMP
              ELSE NULL
            END)
            """,
            (
                name_clean, type_, slug, bio, known_for, source_url,
                voice_tone, voice_style, voice_delivery_notes,
                voice_tone, voice_style, voice_delivery_notes,
            ),
        )
        return cursor.lastrowid


def insert_appearance(
    entity_id: int,
    source_type: str,
    source_id: int,
    role: str,
    prominence: int = 1,
) -> int:
    """
    Insert a single appearance row. Returns appearance_id.
    """
    db = get_db()
    with db._get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO appearances (entity_id, source_type, source_id, role, prominence)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entity_id, source_type, source_id, role, prominence),
        )
        return cursor.lastrowid


def insert_idea(
    source_type: str,
    source_id: int,
    speaker_name: str | None,
    summary: str,
    thesis: str | None,
    tickers: List[str] | None,
    sentiment: str | None,
) -> int:
    """
    Insert an idea row. Returns idea_id.
    """
    db = get_db()
    tickers_json = json.dumps(tickers or [])
    summary_clean = (summary or "").strip()
    if not summary_clean:
        raise ValueError("Idea summary cannot be empty")

    with db._get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO ideas (source_type, source_id, speaker_name, summary, thesis, tickers_json, sentiment)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (source_type, source_id, speaker_name, summary_clean, thesis, tickers_json, sentiment),
        )
        return cursor.lastrowid


def ingest_ai_result(
    source_type: str,
    source_id: int,
    ai_payload: Dict[str, Any],
) -> None:
    """
    Ingest a full AI result for one source (podcast episode or newsletter).

    ai_payload schema (expected):
    {
      "people": [
        {
          "name": "Michael Howell",
          "role": "guest",
          "bio": "...",
          "known_for": "...",
          "prominence": 3
        }
      ],
      "ideas": [
        {
          "speaker_name": "Michael Howell",
          "summary": "...",
          "thesis": "...",
          "tickers": ["SPY", "GLD"],
          "sentiment": "bearish"
        }
      ]
    }
    """
    people = ai_payload.get("people") or []
    ideas = ai_payload.get("ideas") or []

    # First upsert entities and appearances
    speaker_entity_ids: Dict[str, int] = {}

    for p in people:
        name = (p.get("name") or "").strip()
        if not name:
            continue
        # Skip clearly placeholder-ish extraction artifacts.
        if is_placeholder_person_name(name):
            continue
        role = (p.get("role") or "guest").strip().lower()
        bio = p.get("bio") or None
        known_for = p.get("known_for") or None
        prominence = int(p.get("prominence") or 1)
        voice_tone = p.get("voice_tone") or None
        voice_style = p.get("voice_style") or None
        voice_delivery_notes = p.get("voice_delivery_notes") or None

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
            source_type=source_type,
            source_id=source_id,
            role=role,
            prominence=prominence,
        )
        speaker_entity_ids[name] = entity_id

    # Then insert ideas
    for idea in ideas:
        speaker_name = idea.get("speaker_name")
        summary = idea.get("summary") or ""
        thesis = idea.get("thesis") or None
        tickers = idea.get("tickers") or []
        sentiment = idea.get("sentiment") or None

        insert_idea(
            source_type=source_type,
            source_id=source_id,
            speaker_name=speaker_name,
            summary=summary,
            thesis=thesis,
            tickers=tickers,
            sentiment=sentiment,
        )


if __name__ == "__main__":
    # Simple smoke test: create tables and ingest a tiny fake payload
    fake = {
        "people": [
            {
                "name": "Test Guest",
                "role": "guest",
                "bio": "Test bio.",
                "known_for": "Testing things.",
                "prominence": 2
            }
        ],
        "ideas": [
            {
                "speaker_name": "Test Guest",
                "summary": "This is a test idea.",
                "thesis": "More detail on the test idea.",
                "tickers": ["TEST"],
                "sentiment": "neutral"
            }
        ]
    }
    # Use source_type='podcast', source_id=0 just to exercise code paths
    ingest_ai_result("podcast", 0, fake)
    print("Ingest test complete.")

