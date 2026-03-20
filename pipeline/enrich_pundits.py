#!/usr/bin/env python3
"""
enrich_pundits.py

Enrich person entities (pundits) with:
- **LLM JSON profile (default)** — one API call → strict JSON for `bio`, `known_for`, and
  `pundit_profile_json` (site modal). Uses Moonshot / Gemini / OpenAI via `get_ai_client()`.
- **Grokipedia scrape (optional)** — `--grokipedia-profile`, or LLM failure + `PUNDIT_FALLBACK_GROKIPEDIA=1`.
- **Wikidata (+ optional Brave)** — net worth.
- **Optional Grok API** — voice profile; bio fallback if no LLM client.

Env: `PUNDIT_LLM_MODEL`, `PUNDIT_PROFILE_STALE_DAYS`, `GROKIPEDIA_STALE_DAYS`, `PUNDIT_FALLBACK_GROKIPEDIA`,
`GROK_API_*`, `BRAVE_API_KEY`.
"""

import os
import re
import sys
import textwrap
import json
from datetime import datetime
from typing import List, Optional, Tuple

try:
    import requests  # type: ignore
except ImportError:
    requests = None  # We'll degrade gracefully if requests is missing

from pathlib import Path

sys.path.append(str(Path(__file__).parent))
from db_manager import get_db  # type: ignore
from person_name_safety import is_placeholder_person_name

try:
    from grokipedia_client import fetch_pundit_profile_from_grokipedia  # type: ignore
except ImportError:
    fetch_pundit_profile_from_grokipedia = None  # type: ignore

try:
    from pundit_profile_llm import fetch_pundit_profile_via_llm  # type: ignore
except ImportError:
    fetch_pundit_profile_via_llm = None  # type: ignore

WORKSPACE = Path.home() / ".openclaw/workspace"
PIPELINE = WORKSPACE / "pipeline"

from pundit_exclusions import is_excluded_pundit_name


def fetch_top_pundit_entity_ids(conn, limit: int = 10) -> List[int]:
    """
    Same ordering as site pundits.json: guest_primary podcast appearances,
    most recent appearance first. Excludes recurring co-host names.
    """
    cur = conn.execute(
        """
        SELECT
            e.id,
            e.name,
            a.created_at AS last_seen
        FROM entities e
        JOIN appearances a ON a.entity_id = e.id AND LOWER(a.role) = 'guest_primary' AND a.source_type = 'podcast'
        JOIN (
            SELECT entity_id, MAX(id) AS mid
            FROM appearances
            WHERE LOWER(role) = 'guest_primary' AND source_type = 'podcast'
            GROUP BY entity_id
        ) latest ON latest.entity_id = a.entity_id AND a.id = latest.mid
        WHERE e.type = 'person'
        ORDER BY a.created_at DESC
        LIMIT 80
        """
    )
    ids: List[int] = []
    for row in cur.fetchall():
        name = (row["name"] or "").strip()
        if is_excluded_pundit_name(name):
            continue
        if is_placeholder_person_name(name):
            continue
        ids.append(int(row["id"]))
        if len(ids) >= limit:
            break
    return ids


def load_env() -> None:
    for p in (WORKSPACE / ".env", PIPELINE / ".env"):
        if not p.exists():
            continue
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v


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
            headers={"User-Agent": "OpenClaw/1.0 (ai-finance-tech-dashboard; no-reply)"},  # Wikidata requires UA
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
            headers={"User-Agent": "OpenClaw/1.0 (ai-finance-tech-dashboard; no-reply)"},  # Wikidata requires UA
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


def _parse_money_estimate_to_usd(text: str) -> Optional[float]:
    """
    Parse rough money estimates from text, e.g. "$12.4 billion", "US$850 million".
    Returns USD float if found.
    """
    if not text:
        return None
    s = " ".join(text.split()).lower()
    m = re.search(r"(?:us\$|\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(billion|million|bn|m)?", s, re.I)
    if not m:
        return None
    try:
        val = float(m.group(1).replace(",", ""))
    except Exception:
        return None
    unit = (m.group(2) or "").lower()
    if unit in ("billion", "bn"):
        val *= 1_000_000_000
    elif unit in ("million", "m"):
        val *= 1_000_000
    return val if val > 0 else None


def fetch_net_worth_from_search(name: str, known_for: str = "") -> Tuple[Optional[float], Optional[str]]:
    """
    Rough estimate fallback via Brave web search.
    Strategy: query "estimated net worth", then take the first parseable estimate from top results.
    """
    if not requests:
        return None, None
    brave_key = os.getenv("BRAVE_API_KEY") or os.getenv("BRAVE_SUBSCRIPTION_TOKEN")
    if not brave_key:
        return None, None
    query = f'What is the estimated net worth of {name} who is known for {known_for or "technology investing"}?'
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "X-Subscription-Token": brave_key.strip(),
                "Accept": "application/json",
                "User-Agent": "OpenClaw/1.0 (ai-finance-tech-dashboard; no-reply)",
            },
            params={"q": query, "count": 10},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        results = (((data or {}).get("web") or {}).get("results") or [])
        for r in results:
            title = (r.get("title") or "").strip()
            desc = (r.get("description") or "").strip()
            url = (r.get("url") or "").strip()
            combined = f"{title}. {desc}"
            amt = _parse_money_estimate_to_usd(combined)
            if isinstance(amt, (int, float)) and amt > 0:
                return float(amt), (url or "brave:web-search")
        return None, None
    except Exception:
        return None, None


def _load_latest_transcript_excerpt(conn, entity_id: int, max_chars: int = 5000) -> str:
    """Load a short excerpt from the pundit's most recent interview transcript."""
    row = conn.execute(
        """
        SELECT pe.transcript_path
        FROM appearances a
        JOIN podcast_episodes pe ON pe.id = a.source_id
        WHERE a.entity_id = ?
          AND a.source_type = 'podcast'
          AND LOWER(a.role) = 'guest_primary'
          AND pe.transcript_path IS NOT NULL
        ORDER BY a.id DESC
        LIMIT 1
        """,
        (entity_id,),
    ).fetchone()
    if not row:
        return ""
    p = (row["transcript_path"] or "").strip()
    if not p:
        return ""
    tpath = Path(p)
    if not tpath.is_absolute():
        tpath = (Path.home() / ".openclaw/workspace" / p).resolve()
    if not tpath.exists():
        return ""
    try:
        txt = tpath.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""
    txt = " ".join(txt.split())
    return txt[:max_chars]


def _profile_stale_days() -> int:
    for key in ("PUNDIT_PROFILE_STALE_DAYS", "GROKIPEDIA_STALE_DAYS"):
        raw = os.getenv(key)
        if raw:
            try:
                return max(1, int(raw))
            except ValueError:
                pass
    return 30


def _profile_json_stale(fetched_at: Optional[str], profile_json: Optional[str]) -> bool:
    if not profile_json or not str(profile_json).strip():
        return True
    if not fetched_at:
        return True
    try:
        raw = str(fetched_at).replace("Z", "+00:00")
        if "T" not in raw and len(raw) <= 12:
            from datetime import date as _date

            dt = datetime.fromisoformat(raw.split(" ")[0])
        else:
            dt = datetime.fromisoformat(raw[:19])
        age = datetime.now() - dt.replace(tzinfo=None)
        return age.days >= _profile_stale_days()
    except Exception:
        return True


def call_grok_for_voice_profile(name: str, transcript_excerpt: str) -> Optional[dict]:
    """
    Derive voice profile from interview transcript.
    Returns: {"voice_tone": "...", "voice_style": "...", "voice_delivery_notes": "..."}
    """
    api_url = os.getenv("GROK_API_URL")
    api_key = os.getenv("GROK_API_KEY")
    if not api_url or not api_key or not requests or not transcript_excerpt:
        return None

    prompt = textwrap.dedent(f"""
    You are creating TTS direction notes for a weekly debate host.
    Analyze this interview excerpt from "{name}" and return concise speaking guidance.

    Transcript excerpt:
    {transcript_excerpt}

    Rules:
    - Be factual and grounded in this excerpt only.
    - Keep each field concise and practical for writing scripted audio.
    - Avoid personality judgments.
    - JSON only.

    Respond in strict JSON with keys:
    - "voice_tone": short phrase (e.g., "calm analytical")
    - "voice_style": one sentence describing argument structure/word choice
    - "voice_delivery_notes": one sentence with pacing/emphasis guidance for TTS script writing
    """).strip()

    try:
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": os.getenv("GROK_MODEL", "grok-1"),
            "messages": [
                {"role": "system", "content": "You are a speech style analyst for podcast speakers."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=45)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        tone = (parsed.get("voice_tone") or "").strip()
        style = (parsed.get("voice_style") or "").strip()
        notes = (parsed.get("voice_delivery_notes") or "").strip()
        if not (tone or style or notes):
            return None
        return {
            "voice_tone": tone,
            "voice_style": style,
            "voice_delivery_notes": notes,
        }
    except Exception:
        return None


def enrich_pundits(
    max_pundits: int = 20,
    skip_profile: bool = False,
    force_profile: bool = False,
    grokipedia_profile: bool = False,
    grokipedia_only: bool = False,
    force_grokipedia: bool = False,
    top_pundits_only: bool = False,
) -> int:
    """
    Enrich person rows: LLM JSON profile (default), optional Grokipedia, net worth, voice.
    If top_pundits_only=True, targets the same people as site pundits (guest_primary, recent first).
    Returns the number of rows updated.
    """
    load_env()
    # Legacy CLI flags
    if force_grokipedia:
        force_profile = True
        grokipedia_profile = True
    db = get_db()
    updated = 0

    with db._get_connection() as conn:  # type: ignore[attr-defined]
        if top_pundits_only:
            ids = fetch_top_pundit_entity_ids(conn, limit=max_pundits)
            if not ids:
                print("✗ No top pundits found (guest_primary appearances).")
                return 0
            placeholders = ",".join("?" * len(ids))
            cursor = conn.execute(
                f"""
                SELECT id, name, bio, known_for, net_worth_usd, net_worth_source,
                       voice_tone, voice_style, voice_delivery_notes,
                       grokipedia_url, grokipedia_fetched_at, pundit_profile_json
                FROM entities
                WHERE id IN ({placeholders})
                """,
                ids,
            )
            by_id = {int(r["id"]): r for r in cursor.fetchall()}
            rows = [by_id[i] for i in ids if i in by_id]
            print(f"→ Top {len(rows)} pundit(s) by site export order: {[r['name'] for r in rows]}")
        else:
            cursor = conn.execute(
                """
                SELECT id, name, bio, known_for, net_worth_usd, net_worth_source,
                       voice_tone, voice_style, voice_delivery_notes,
                       grokipedia_url, grokipedia_fetched_at, pundit_profile_json
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
            # Never enrich placeholders; keep them out of DB-derived pundit UI.
            if is_placeholder_person_name(name):
                continue
            bio = (row["bio"] or "").strip()
            known_for = (row["known_for"] or "").strip()
            net_worth_usd = row["net_worth_usd"]
            net_worth_source = (row["net_worth_source"] or "").strip()
            voice_tone = (row["voice_tone"] or "").strip()
            voice_style = (row["voice_style"] or "").strip()
            voice_notes = (row["voice_delivery_notes"] or "").strip()
            g_url = (row["grokipedia_url"] or "").strip()
            g_fetched = row["grokipedia_fetched_at"]
            prof_json = row["pundit_profile_json"]

            need_profile_blob = not skip_profile and (
                force_profile
                or _profile_json_stale(str(g_fetched) if g_fetched else None, prof_json)
            )
            need_profile = not (len(bio) >= 40 and len(known_for) >= 20)
            need_net_worth = not (isinstance(net_worth_usd, (int, float)) and net_worth_usd > 0 and net_worth_source)
            need_voice = not (voice_tone and voice_style and voice_notes)

            if grokipedia_only:
                # Profile refresh only; skip net worth / voice / extra Grok bio pass
                need_net_worth = False
                need_voice = False

            new_bio = bio
            new_known_for = known_for
            new_g_url = g_url
            new_g_fetched = g_fetched
            new_prof_json = prof_json
            new_net_worth = net_worth_usd
            new_net_source = net_worth_source
            new_net_updated = None
            new_voice_tone = voice_tone
            new_voice_style = voice_style
            new_voice_notes = voice_notes
            new_voice_updated = None

            g_profile = None
            llm_pair = None

            if need_profile_blob and grokipedia_profile and fetch_pundit_profile_from_grokipedia:
                try:
                    g_profile = fetch_pundit_profile_from_grokipedia(name, known_for=known_for, bio=bio)
                except Exception:
                    g_profile = None
                if g_profile:
                    new_g_url = g_profile.get("source_url") or new_g_url
                    new_g_fetched = datetime.now().isoformat()
                    new_prof_json = json.dumps(g_profile, ensure_ascii=False)
                    derived = g_profile.get("derived") or {}
                    infobox = g_profile.get("infobox") or {}
                    cliff = (g_profile.get("cliff_notes") or "").strip()
                    if need_profile and cliff:
                        if len(new_bio) < 40:
                            new_bio = cliff[:480].rsplit(" ", 1)[0] + ("…" if len(cliff) > 480 else "")
                        if len(new_known_for) < 20:
                            cand = (
                                derived.get("current_role")
                                or infobox.get("Occupation")
                                or infobox.get("Title")
                                or ""
                            )
                            if isinstance(cand, str) and len(cand.strip()) >= 12:
                                new_known_for = cand.strip()[:240]
            elif need_profile_blob and not grokipedia_profile and fetch_pundit_profile_via_llm:
                episode_hint = ""
                try:
                    episode_hint = _load_latest_transcript_excerpt(conn, ent_id, max_chars=1800)
                except Exception:
                    episode_hint = ""
                try:
                    llm_pair = fetch_pundit_profile_via_llm(
                        name, known_for=known_for, bio=bio, episode_context=episode_hint
                    )
                except Exception:
                    llm_pair = None
                if llm_pair:
                    stored, flat = llm_pair
                    new_prof_json = json.dumps(stored, ensure_ascii=False)
                    new_g_fetched = datetime.now().isoformat()
                    new_g_url = None  # not a Grokipedia URL
                    new_bio = (flat.get("bio") or new_bio).strip()[:2000]
                    new_known_for = (flat.get("known_for") or new_known_for).strip()[:500]
                elif (
                    os.getenv("PUNDIT_FALLBACK_GROKIPEDIA", "").strip() in ("1", "true", "yes")
                    and fetch_pundit_profile_from_grokipedia
                ):
                    try:
                        g_profile = fetch_pundit_profile_from_grokipedia(
                            name, known_for=known_for, bio=bio
                        )
                    except Exception:
                        g_profile = None
                    if g_profile:
                        new_g_url = g_profile.get("source_url") or new_g_url
                        new_g_fetched = datetime.now().isoformat()
                        new_prof_json = json.dumps(g_profile, ensure_ascii=False)
                        derived = g_profile.get("derived") or {}
                        infobox = g_profile.get("infobox") or {}
                        cliff = (g_profile.get("cliff_notes") or "").strip()
                        if need_profile and cliff and len(new_bio) < 40:
                            new_bio = cliff[:480].rsplit(" ", 1)[0] + (
                                "…" if len(cliff) > 480 else ""
                            )
                        if need_profile and len(new_known_for) < 20:
                            cand = (
                                derived.get("current_role")
                                or infobox.get("Occupation")
                                or infobox.get("Title")
                                or ""
                            )
                            if isinstance(cand, str) and len(cand.strip()) >= 12:
                                new_known_for = cand.strip()[:240]

            info = None
            if (
                need_profile
                and not grokipedia_only
                and (len(new_bio) < 40 or len(new_known_for) < 20)
            ):
                info = call_grok_for_bio(name)
            if info:
                new_bio = (info.get("bio") or "").strip() or new_bio
                new_known_for = (info.get("known_for") or "").strip() or new_known_for

            if need_net_worth and not grokipedia_only:
                nw, src = fetch_net_worth_from_web(name)
                if not (isinstance(nw, (int, float)) and nw > 0):
                    nw, src = fetch_net_worth_from_search(name, known_for or new_known_for)
                if isinstance(nw, (int, float)) and nw > 0:
                    new_net_worth = float(nw)
                    new_net_source = src or "wikidata"
                    new_net_updated = datetime.now().isoformat()

            if need_voice and not grokipedia_only:
                excerpt = _load_latest_transcript_excerpt(conn, ent_id)
                v = call_grok_for_voice_profile(name, excerpt)
                if v:
                    new_voice_tone = (v.get("voice_tone") or "").strip() or voice_tone
                    new_voice_style = (v.get("voice_style") or "").strip() or voice_style
                    new_voice_notes = (v.get("voice_delivery_notes") or "").strip() or voice_notes
                    if new_voice_tone or new_voice_style or new_voice_notes:
                        new_voice_updated = datetime.now().isoformat()

            prof_same = (new_prof_json == prof_json) or (
                (new_prof_json in (None, "")) and (prof_json in (None, ""))
            )
            # Skip if nothing changed.
            if (
                new_bio == bio
                and new_known_for == known_for
                and (new_net_worth == net_worth_usd or (new_net_worth is None and net_worth_usd is None))
                and new_net_source == net_worth_source
                and new_voice_tone == voice_tone
                and new_voice_style == voice_style
                and new_voice_notes == voice_notes
                and new_g_url == g_url
                and str(new_g_fetched or "") == str(g_fetched or "")
                and prof_same
            ):
                continue

            conn.execute(
                """
                UPDATE entities
                SET bio = ?, known_for = ?, net_worth_usd = ?, net_worth_source = ?,
                    net_worth_updated_at = COALESCE(?, net_worth_updated_at),
                    voice_tone = ?, voice_style = ?, voice_delivery_notes = ?,
                    voice_profile_updated_at = COALESCE(?, voice_profile_updated_at),
                    grokipedia_url = ?, grokipedia_fetched_at = ?, pundit_profile_json = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_bio,
                    new_known_for,
                    new_net_worth,
                    new_net_source,
                    new_net_updated,
                    new_voice_tone,
                    new_voice_style,
                    new_voice_notes,
                    new_voice_updated,
                    new_g_url or None,
                    new_g_fetched,
                    new_prof_json,
                    datetime.now().isoformat(),
                    ent_id,
                ),
            )
            updated += 1

    print(f"✓ Enriched {updated} pundit(s) (LLM/Grokipedia profile + net worth + optional Grok)")
    return updated


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Enrich pundits: LLM JSON profile (default), Grokipedia, Wikidata, Grok.")
    ap.add_argument(
        "--top-pundits",
        action="store_true",
        help="Target top pundits (same order as site export: guest_primary, recent first), not generic updated_at",
    )
    ap.add_argument("--max", type=int, default=20, dest="max_pundits", help="Max rows (default 10 with --top-pundits if unset)")
    ap.add_argument("--skip-profile", action="store_true", help="Do not update pundit_profile_json (no LLM/Grokipedia)")
    ap.add_argument("--force-profile", action="store_true", help="Re-fetch profile even if cache is fresh")
    ap.add_argument(
        "--grokipedia-profile",
        action="store_true",
        help="Use grokipedia.com scrape instead of LLM for structured profile",
    )
    ap.add_argument(
        "--skip-grokipedia",
        action="store_true",
        help="Legacy: skip profile enrichment entirely (same as --skip-profile)",
    )
    ap.add_argument("--grokipedia-only", action="store_true", help="Only profile + URL; skip net worth & voice")
    ap.add_argument("--force-grokipedia", action="store_true", help="Same as --force-profile --grokipedia-profile")
    args = ap.parse_args()
    max_n = args.max_pundits
    if args.top_pundits and args.max_pundits == 20:
        max_n = 10
    enrich_pundits(
        max_pundits=max_n,
        skip_profile=args.skip_profile or args.skip_grokipedia,
        force_profile=args.force_profile,
        grokipedia_profile=args.grokipedia_profile,
        grokipedia_only=args.grokipedia_only,
        force_grokipedia=args.force_grokipedia,
        top_pundits_only=args.top_pundits,
    )

