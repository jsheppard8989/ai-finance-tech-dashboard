#!/usr/bin/env python3
"""
One API call → JSON that maps directly into entities.bio, entities.known_for,
and entities.pundit_profile_json (same shape the site modal expects).

Uses the same AI client stack as the rest of the pipeline (Moonshot → Gemini → OpenAI).
"""

from __future__ import annotations

import json
import os
import re
import textwrap
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# --- Exact schema the model must follow (also embedded in the user prompt) ---

PUNDIT_LLM_OUTPUT_KEYS = """
The JSON object MUST include these keys (strings unless noted):

  "bio" — 2–4 sentences, neutral, for a dashboard card (under ~120 words).
  "known_for" — single punchy sentence, why investors / tech listeners care.

  "current_role" — primary job title + org today, or "" if unknown.
  "former_roles" — notable past roles; semicolon-separated, or "".
  "boards" — board seats / advisory roles; or "".
  "education" — degrees / institutions; or "".
  "books_and_publications" — books, major reports, or ""; not exhaustive.
  "teaching" — professorships, guest lectures, courses; or "".
  "political_affiliation" — party or "Independent" / "" if not applicable or unknown.
  "political_summary" — 1–3 sentences on public political involvement, or "".

  "cliff_notes_autobiography" — longer neutral narrative (roughly 200–500 words):
    career arc, why they matter in tech/finance/policy, no fluff.

  "topic_highlights" — array of 3–8 objects, each:
      { "heading": "short label", "summary": "2–5 sentences" }

  "infobox" — flat object of extra factual labels → short values, e.g.
      { "Born": "...", "Nationality": "..." } — omit keys you do not know.
"""


def _strip_json_fence(s: str) -> str:
    s = (s or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```\w*\n?", "", s)
        s = re.sub(r"\n?```\s*$", "", s)
    return s.strip()


def _openai_compatible_json(
    client: Any, model: str, system: str, user: str, temperature: float = 0.25
) -> Dict[str, Any]:
    """Chat Completions with JSON mode when supported (OpenAI + many OpenAI-compatible APIs)."""
    kwargs: Dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    try:
        r = client.chat.completions.create(
            **kwargs,
            response_format={"type": "json_object"},
        )
    except Exception:
        r = client.chat.completions.create(**kwargs)
    text = (r.choices[0].message.content or "").strip()
    return json.loads(_strip_json_fence(text))


def _gemini_json(api_key: str, model: str, system: str, user: str, temperature: float = 0.25) -> Dict[str, Any]:
    import google.generativeai as genai

    genai.configure(api_key=api_key)
    try:
        m = genai.GenerativeModel(model, system_instruction=system)
    except TypeError:
        m = genai.GenerativeModel(model)
        user = f"{system}\n\n---\n\n{user}"
    try:
        r = m.generate_content(
            user,
            generation_config={
                "temperature": temperature,
                "max_output_tokens": 4096,
                "response_mime_type": "application/json",
            },
        )
    except Exception:
        r = m.generate_content(
            user,
            generation_config={"temperature": temperature, "max_output_tokens": 4096},
        )
    text = (getattr(r, "text", None) or "").strip()
    return json.loads(_strip_json_fence(text))


def normalize_llm_row_to_stored_profile(
    name: str, raw: Dict[str, Any], source_model: str = ""
) -> Dict[str, Any]:
    """Map LLM keys → same structure as Grokipedia scraper / site export."""
    now = datetime.now(timezone.utc).isoformat()
    derived: Dict[str, str] = {}
    cr = (raw.get("current_role") or "").strip()
    if cr:
        derived["current_role"] = cr
    fr = (raw.get("former_roles") or raw.get("former_positions") or "").strip()
    if fr:
        derived["former_positions"] = fr
    for key, out_key in [
        ("boards", "boards"),
        ("education", "education"),
        ("political_affiliation", "political_affiliation"),
        ("political_summary", "political_summary"),
        ("books_and_publications", "books_or_works"),
        ("teaching", "teaching_summary"),
    ]:
        v = (raw.get(key) or "").strip()
        if v:
            derived[out_key] = v

    highlights = raw.get("topic_highlights") or []
    sections: List[Dict[str, str]] = []
    if isinstance(highlights, list):
        for item in highlights:
            if not isinstance(item, dict):
                continue
            h = (item.get("heading") or "").strip()
            body = (item.get("summary") or item.get("body") or "").strip()
            if h or body:
                sections.append({"heading": h, "body": body})

    cliff = (raw.get("cliff_notes_autobiography") or raw.get("cliff_notes") or "").strip()
    infobox = raw.get("infobox") if isinstance(raw.get("infobox"), dict) else {}
    infobox_clean = {str(k).strip(): str(v).strip() for k, v in infobox.items() if str(k).strip()}

    # Lead = first ~3 sentences of cliff for optional UI chips
    lead_paragraphs: List[str] = []
    if cliff:
        parts = re.split(r"(?<=[.!?])\s+", cliff)
        buf = ""
        for p in parts:
            if not p:
                continue
            buf = (buf + " " + p).strip()
            if len(buf) > 320:
                lead_paragraphs.append(buf)
                buf = ""
        if buf:
            lead_paragraphs.append(buf)
        if not lead_paragraphs:
            lead_paragraphs = [cliff[:500]]

    meta = source_model.strip() or "pipeline-llm"
    return {
        "source": "llm",
        "source_model": meta,
        "source_url": "",
        "page_slug": "",
        "page_title": name,
        "fetched_at": now,
        "infobox": infobox_clean,
        "lead_paragraphs": lead_paragraphs[:8],
        "cliff_notes": cliff,
        "sections": sections[:24],
        "derived": derived,
    }


def fetch_pundit_profile_via_llm(
    name: str,
    known_for: str = "",
    bio: str = "",
    episode_context: str = "",
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    Returns (stored_profile_dict, flat_updates) where flat_updates has bio, known_for
    from the model for direct DB columns; or None on failure.
    """
    from analyze_transcript import get_ai_client  # type: ignore

    client_info = get_ai_client()
    if not client_info:
        return None

    kind, client = client_info
    system = textwrap.dedent(
        """
        You are a careful researcher assembling factual public-career summaries for an
        investor-facing podcast dashboard. Return ONLY valid JSON — one object, no markdown fences.

        Rules:
        - Neutral tone; no insults or partisan rants.
        - If a fact is uncertain, leave that field empty rather than guessing.
        - Do NOT include net worth or salary numbers (filled by other pipelines).
        """
    ).strip()

    ctx_bits = []
    if known_for.strip():
        ctx_bits.append(f"Context from our index (known_for): {known_for.strip()}")
    if bio.strip():
        ctx_bits.append(f"Existing short bio (may be incomplete): {bio.strip()}")
    if episode_context.strip():
        ctx_bits.append(f"Recent appearance / episode hint: {episode_context.strip()[:1200]}")
    ctx = "\n".join(ctx_bits) if ctx_bits else "(no extra context)"

    user = textwrap.dedent(
        f"""
        Produce structured data for this person (disambiguate using context if the name is common):

        Name: {name}

        {ctx}

        {PUNDIT_LLM_OUTPUT_KEYS}

        Respond with a single JSON object containing exactly those top-level keys.
        """
    ).strip()

    model_used = ""
    try:
        if kind in ("moonshot", "openai"):
            model_used = os.getenv("PUNDIT_LLM_MODEL") or os.getenv("DEBATE_LLM_MODEL", "moonshot-v1-8k")
            if kind == "openai" and "moonshot" in model_used:
                model_used = os.getenv("OPENAI_PUNDIT_MODEL") or os.getenv("OPENAI_DEBATE_MODEL", "gpt-4o-mini")
            raw = _openai_compatible_json(client, model_used, system, user)
        elif kind == "gemini":
            model_used = os.getenv("GEMINI_PUNDIT_MODEL") or os.getenv("GEMINI_DEBATE_MODEL", "gemini-1.5-flash")
            raw = _gemini_json(client, model_used, system, user)
        else:
            return None
    except Exception:
        return None

    if not isinstance(raw, dict):
        return None

    bio_out = (raw.get("bio") or "").strip()
    kf = (raw.get("known_for") or "").strip()
    if len(bio_out) < 20 or len(kf) < 10:
        return None

    model_tag = f"{kind}:{model_used}" if model_used else kind
    stored = normalize_llm_row_to_stored_profile(name, raw, source_model=model_tag)
    flat = {"bio": bio_out[:2000], "known_for": kf[:500]}
    return stored, flat
