#!/usr/bin/env python3
"""
enrich_pundits.py

Goal: Enrich semantic-layer Pundits (entities of type 'person' with guest_primary podcast
appearances) with neutral, factual biographical information from an external source
such as Grok/Grokopedia, and write it back into the database for website export.

This script is deliberately conservative:
- It only fills in missing/very short bios/known_for fields
- It is idempotent and safe to run as a cron step

NOTE: To actually call Grok/Grokopedia, set the following environment variables:
- GROK_API_URL  (e.g. https://api.x.ai/v1/chat/completions or Grokopedia endpoint)
- GROK_API_KEY  (your API key/token)

The concrete HTTP contract may differ depending on your Grok setup; adjust the
`call_grok_for_bio` function accordingly.
"""

import os
import sys
import textwrap
from datetime import datetime
from typing import Optional

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # We'll degrade gracefully if requests is missing

from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from db_manager import get_db  # type: ignore


def call_grok_for_bio(name: str) -> Optional[dict]:
    """
    Call Grok / Grokopedia (or any external LLM) to obtain a short factual bio and
    "known_for" summary for a person.

    Returns a dict:
      { "bio": "...", "known_for": "..." }

    If configuration is missing or the call fails, returns None.
    """
    api_url = os.getenv("GROK_API_URL")
    api_key = os.getenv("GROK_API_KEY")
    if not api_url or not api_key or not requests:
        return None

    prompt = textwrap.dedent(f"""
    You are generating a neutral, factual mini-bio for an investment/technology
    pundit named "{name}".

    - Focus on their role in AI, finance, technology, or macro commentary.
    - Avoid political snark or editorializing.
    - Keep it under 80 words.

    Also provide a 1-sentence "known_for" summary suitable for a dashboard card.

    Respond in strict JSON with keys "bio" and "known_for".
    """).strip()

    try:
        # This payload and headers are intentionally generic; adjust to your Grok API.
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": os.getenv("GROK_MODEL", "grok-1"),
            "messages": [
                {"role": "system", "content": "You are a neutral financial/technology biographer."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        # This part is API-specific; adjust extraction as needed.
        # Expecting the model to return JSON in the message content.
        content = ""
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception:
            return None

        import json

        parsed = json.loads(content)
        bio = (parsed.get("bio") or "").strip()
        known_for = (parsed.get("known_for") or "").strip()
        if not bio and not known_for:
            return None
        return {"bio": bio, "known_for": known_for}
    except Exception:
        return None


def enrich_pundits(max_pundits: int = 20) -> int:
    """
    Fetch Pundits from the semantic layer and enrich missing/short bios/known_for fields.
    Returns the number of rows updated.
    """
    db = get_db()
    updated = 0

    with db._get_connection() as conn:  # type: ignore[attr-defined]
        cursor = conn.execute(
            """
            SELECT id, name, bio, known_for
            FROM entities
            WHERE type = 'person'
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (max_pundits,),
        )
        rows = cursor.fetchall()

        for row in rows:
            ent_id = row["id"]
            name = (row["name"] or "").strip()
            bio = (row["bio"] or "").strip()
            known_for = (row["known_for"] or "").strip()

            # Only enrich if both are missing or extremely short
            if len(bio) >= 40 and len(known_for) >= 20:
                continue

            info = call_grok_for_bio(name)
            if not info:
                continue

            new_bio = info.get("bio") or bio
            new_known_for = info.get("known_for") or known_for

            conn.execute(
                """
                UPDATE entities
                SET bio = ?, known_for = ?, updated_at = ?
                WHERE id = ?
                """,
                (new_bio, new_known_for, datetime.now().isoformat(), ent_id),
            )
            updated += 1

    print(f"✓ Enriched {updated} pundit(s) with Grok/Grokopedia bios")
    return updated


if __name__ == "__main__":
    enrich_pundits()

