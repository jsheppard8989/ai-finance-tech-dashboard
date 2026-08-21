#!/usr/bin/env python3
"""
Scan podcast transcripts for known Overton / suggested terms and record per-episode mentions.

Resolves aliases to canonical terms. At most one mention increment per canonical term per episode.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Set, Tuple

from term_alias_util import expand_terms_for_scan


def _term_pattern(term: str) -> Optional[re.Pattern]:
    """Build a case-insensitive pattern with word boundaries for short tokens."""
    t = (term or "").strip()
    if len(t) < 3:
        return None
    parts = [re.escape(p) for p in t.split()]
    if len(parts) == 1:
        core = parts[0]
        return re.compile(rf"\b{core}\b", re.IGNORECASE)
    inner = r"\s+".join(parts)
    return re.compile(rf"(?<!\w){inner}(?!\w)", re.IGNORECASE)


def find_canonical_terms_in_text(
    text: str,
    scan_pairs: Iterable[Tuple[str, str]],
) -> List[str]:
    """Return canonical terms matched at least once (one hit per canonical)."""
    if not text:
        return []
    found: List[str] = []
    seen_canonical: Set[str] = set()
    for match_phrase, canonical in scan_pairs:
        key = canonical.lower()
        if key in seen_canonical:
            continue
        pat = _term_pattern(match_phrase)
        if pat and pat.search(text):
            found.append(canonical)
            seen_canonical.add(key)
    return found


def record_episode_mentions(
    db,
    *,
    transcript: str,
    episode_id: int,
    detected_by: Optional[str] = None,
) -> Tuple[int, List[str]]:
    """
    For each tracked term found in transcript, bump counts if this episode is new for that term.
    Returns (terms_updated_count, canonical_term_names).
    """
    if not episode_id or not transcript:
        return 0, []

    updated: List[str] = []
    with db._get_connection() as conn:
        scan_pairs = expand_terms_for_scan(conn)
        hits = find_canonical_terms_in_text(transcript, scan_pairs)
        for term in hits:
            if db.record_tracked_term_episode_mention(
                conn,
                term,
                episode_id=episode_id,
                detected_by=detected_by,
            ):
                updated.append(term)
    return len(updated), updated
