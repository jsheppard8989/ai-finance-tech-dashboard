#!/usr/bin/env python3
"""
Fetch live Polymarket (Gamma API) market themes for debate contract generation.

Public read — no auth. See https://docs.polymarket.com — Gamma API is public.

Filters OUT sports, pop-culture memes, and similar noise; prefers economics,
policy, elections, crypto, macro, geopolitics, tech. Sorted by volume so
high-salience topics surface first.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    requests = None  # type: ignore

GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"

# Drop obvious sports / entertainment / meme markets
_EXCLUDE = re.compile(
    r"""
    stanley|nhl|nba|nfl|mlb|\bnhl\b|super\s*bowl|world\s*cup|premier\s*league|
    lakers|celtics|yankees|ufc\b|f1\b|qualifier|gta\s*vi|grand\s*theft|
    album\b|rihanna|carti|playboi|jesus\s*christ|return\s*before\s*gta|
    bitboy|convicted\?|oscars?\b|grammy|super\s*bowl
    """,
    re.I | re.VERBOSE,
)

# Boost relevance for investor / policy audience (count substring matches)
_INCLUDE = re.compile(
    r"""
    bitcoin|btc|ethereum|eth\b|microstrategy|fed\b|fomc|interest\s*rate|
    inflation|recession|gdp|unemployment|treasury|yield|bond|etf\b|
    election|president|senate|congress|trump|biden|putin|zelenskyy|
    china|taiwan|ukraine|nato|ceasefire|tariff|sanction|
    ai\b|semiconductor|nvidia|sec\b|ipo\b|macro|debt\s*ceiling
    """,
    re.I | re.VERBOSE,
)


def _volume(e: Dict[str, Any]) -> float:
    try:
        return float(e.get("volume") or e.get("volumeNum") or 0)
    except (TypeError, ValueError):
        return 0.0


def _relevance_score(text: str) -> int:
    if not text:
        return 0
    return len(_INCLUDE.findall(text))


def fetch_polymarket_debate_context(
    limit_events: int = 120,
    max_lines: int = 16,
    timeout_sec: float = 25.0,
) -> str:
    """
    Returns a multi-line string for injection into the contract LLM user prompt.
    On failure, returns a short fallback sentence (never raises).
    """
    if not requests:
        return "(Polymarket: install `requests` to enable live market context.)"

    params: Dict[str, Any] = {
        "active": "true",
        "closed": "false",
        "limit": str(limit_events),
    }
    try:
        r = requests.get(
            GAMMA_EVENTS,
            params=params,
            timeout=timeout_sec,
            headers={"User-Agent": "DebateContext/1.0 (scarcity-abundance-dashboard; +local)"},
        )
        r.raise_for_status()
        events = r.json()
    except Exception as e:
        return f"(Polymarket live data unavailable: {type(e).__name__}.)"

    if not isinstance(events, list):
        return "(Polymarket: unexpected API response.)"

    scored: List[tuple] = []
    for e in events:
        if not isinstance(e, dict):
            continue
        title = (e.get("title") or "").strip()
        desc = (e.get("description") or "")[:500]
        blob = f"{title} {desc}"
        if _EXCLUDE.search(blob):
            continue
        v = _volume(e)
        rel = _relevance_score(blob)
        if rel < 1:
            continue
        scored.append((rel, v, e))

    if not scored:
        for e in events:
            if not isinstance(e, dict):
                continue
            title = (e.get("title") or "").strip()
            desc = (e.get("description") or "")[:500]
            blob = f"{title} {desc}"
            if _EXCLUDE.search(blob):
                continue
            v = _volume(e)
            rel = _relevance_score(blob)
            scored.append((max(rel, 0), v, e))

    scored.sort(key=lambda x: (-x[0], -x[1]))

    lines: List[str] = [
        "Live Polymarket markets (Gamma API, volume-sorted — these are the VALID outcome themes for this week):",
        "Prefer paraphrasing ONE of these into a clear Yes/No contract whose resolution metric matches the kind of "
        "outcome Polymarket actually trades (policy, macro, elections, crypto, rates, etc.).",
        "Do NOT invent stale macro numbers from memory (e.g. old index levels). If you use a price level, it must "
        "match the separate LIVE reference block in the debate prompt — not training-data recollection.",
        "Do not copy Polymarket wording verbatim; specify independent resolution sources in resolution_clarity.",
    ]
    for rel, vol, e in scored[:max_lines]:
        title = (e.get("title") or "").strip().replace("\n", " ")
        if not title:
            continue
        vol_s = f"${vol:,.0f}" if vol >= 1000 else f"${vol:.0f}"
        extra = ""
        desc = (e.get("description") or "").strip()
        if desc:
            first = desc.split("\n")[0].strip()
            if len(first) > 220:
                first = first[:217] + "…"
            extra = f" | Resolution hint: {first}"
        lines.append(f"- [{vol_s} vol., relevance+{rel}] {title}{extra}")

    if len(lines) <= 2:
        return (
            "(Polymarket: no qualifying events after filters — "
            "proceed using Overton + insights only.)"
        )

    return "\n".join(lines)
