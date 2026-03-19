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
from typing import Optional, Tuple

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


def _wikidata_search_entity_id(name: str) -> Optional[str]:
    """Find likely Wikidata entity id for a person name."""
    if not requests:
        return None
    try:
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbsearchentities",
                "format": "json",
                "language": "en",
                "type": "item",
                "search": name,
                "limit": 5,
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        results = data.get("search", []) or []
        if not results:
            return None
        # Prefer obvious human profiles first.
        for r in results:
            desc = (r.get("description") or "").lower()
            if any(k in desc for k in ["entrepreneur", "investor", "business", "american", "ceo", "founder"]):
                return r.get("id")
        return results[0].get("id")
    except Exception:
        return None


def _wikidata_net_worth_usd(entity_id: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Read net worth from Wikidata property P2218.
    Returns (usd_value, source_url).
    """
    if not requests or not entity_id:
        return None, None
    try:
        resp = requests.get(
            "https://www.wikidata.org/w/api.php",
            params={
                "action": "wbgetentities",
                "format": "json",
                "ids": entity_id,
                "languages": "en",
            },
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        ent = ((data.get("entities") or {}).get(entity_id) or {})
        claims = ent.get("claims") or {}
        networth_claims = claims.get("P2218") or []
        if not networth_claims:
            return None, f"https://www.wikidata.org/wiki/{entity_id}"

        best_amount = None
        for c in networth_claims:
            dv = (((c.get("mainsnak") or {}).get("datavalue") or {}).get("value") or {})
            amount_raw = dv.get("amount")
            unit = dv.get("unit") or ""
            if not amount_raw:
                continue
            try:
                amount = abs(float(str(amount_raw)))
            except Exception:
                continue
            # P2218 is often in USD; unit Q4917 means US dollar.
            if unit and "Q4917" in unit:
                if best_amount is None or amount > best_amount:
                    best_amount = amount
        return best_amount, f"https://www.wikidata.org/wiki/{entity_id}"
    except Exception:
        return None, None


def fetch_net_worth_from_web(name: str) -> Tuple[Optional[float], Optional[str]]:
    """Best-effort structured net worth lookup from public web data (Wikidata)."""
    entity_id = _wikidata_search_entity_id(name)
    if not entity_id:
        return None, None
    return _wikidata_net_worth_usd(entity_id)


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
            SELECT id, name, bio, known_for, net_worth_usd, net_worth_source
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
            net_worth_usd = row["net_worth_usd"]
            net_worth_source = (row["net_worth_source"] or "").strip()

            need_profile = not (len(bio) >= 40 and len(known_for) >= 20)
            need_net_worth = not (isinstance(net_worth_usd, (int, float)) and net_worth_usd > 0 and net_worth_source)

            info = None
            if need_profile:
                info = call_grok_for_bio(name)

            new_bio = (info or {}).get("bio") or bio
            new_known_for = (info or {}).get("known_for") or known_for
            new_net_worth = net_worth_usd
            new_net_source = net_worth_source
            new_net_updated = None

            if need_net_worth:
                nw, src = fetch_net_worth_from_web(name)
                if isinstance(nw, (int, float)) and nw > 0:
                    new_net_worth = float(nw)
                    new_net_source = src or "wikidata"
                    new_net_updated = datetime.now().isoformat()

            # Skip if nothing changed.
            if (
                new_bio == bio
                and new_known_for == known_for
                and (new_net_worth == net_worth_usd or (new_net_worth is None and net_worth_usd is None))
                and new_net_source == net_worth_source
            ):
                continue

            conn.execute(
                """
                UPDATE entities
                SET bio = ?, known_for = ?, net_worth_usd = ?, net_worth_source = ?,
                    net_worth_updated_at = COALESCE(?, net_worth_updated_at), updated_at = ?
                WHERE id = ?
                """,
                (
                    new_bio,
                    new_known_for,
                    new_net_worth,
                    new_net_source,
                    new_net_updated,
                    datetime.now().isoformat(),
                    ent_id,
                ),
            )
            updated += 1

    print(f"✓ Enriched {updated} pundit(s) with profile/net-worth data")
    return updated


if __name__ == "__main__":
    enrich_pundits()

