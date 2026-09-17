#!/usr/bin/env python3
"""
Utilities for filtering clearly non-real / placeholder person names.

Goal: prevent bogus entities like "Guest Expert" or "Dr. Cash" from being
created/enriched/exported as pundits.
"""

from __future__ import annotations

import re
from typing import List


# Known ASR / extraction errors: map mistaken name -> canonical display name.
# Keep this list small and high-confidence only (wrong merges are worse than duplicates).
# These aliases are used by:
#   1. Entity upsert (prevent duplicate entities)
#   2. Pundit exclusion checks (block ASR variants of excluded names)
#   3. Net worth lookups (use canonical name for accurate data)
_TRANSCRIPTION_CANONICAL_NAMES: dict[str, str] = {
    # Same person (Commodity Context); "Roy Johnson" is a recurring transcript mistake.
    "roy johnson": "Rory Johnston",
    # Dave Blundin (Moonshots co-host) — common ASR mishearings
    "dave blenden": "Dave Blundin",
    "david blenden": "Dave Blundin",
    "dave blundon": "Dave Blundin",
    "david blundon": "Dave Blundin",
    "dave blundan": "Dave Blundin",
    "david blundin": "Dave Blundin",
    # Alex Wissner-Gross (co-host AWG) — common ASR mishearings
    "alex weesner": "Alex Wissner-Gross",
    "alex wiesner": "Alex Wissner-Gross",
    "alex wisner": "Alex Wissner-Gross",
    "alex wessner": "Alex Wissner-Gross",
    "alex weissner": "Alex Wissner-Gross",
    "alex wissner gross": "Alex Wissner-Gross",
    "alexander weesner": "Alex Wissner-Gross",
    "alexander wiesner": "Alex Wissner-Gross",
    "alexander wisner": "Alex Wissner-Gross",
    # David Sacks (All-In host) — ASR variants
    "david sachs": "David Sacks",
    "dave sacks": "David Sacks",
    "dave sachs": "David Sacks",
}


def canonicalize_person_name(name: str) -> str:
    """
    Normalize known mistaken person names to a single canonical entity name.

    Used at entity upsert time so future pipeline runs don't recreate the bad alias.
    """
    s = _normalize_name(name)
    if not s:
        return s
    key = s.lower()
    return _TRANSCRIPTION_CANONICAL_NAMES.get(key, s)


def _normalize_name(name: str) -> str:
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def _token_count(name: str) -> int:
    s = _normalize_name(name)
    # Remove nicknames in quotes/parentheses to avoid token inflation.
    s = re.sub(r"['\"][^'\"]*['\"]", " ", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^A-Za-z0-9]+", " ", s)
    parts = [p for p in s.split() if p]
    return len(parts)


def is_placeholder_person_name(name: str) -> bool:
    """
    Conservative placeholder detection.

    We intentionally err on the side of skipping when the name looks like a
    placeholder rather than a real person (common in LLM extraction outputs).
    """
    s = _normalize_name(name)
    if not s:
        return True

    lower = s.lower()

    # Explicit placeholder phrases produced by LLM extraction.
    explicit = {
        "guest expert",
        "guest",
        "expert",
        "unknown",
        "unknown person",
        "tbd",
        "to be determined",
        "placeholder",
        "dr cash",
        "dr. cash",
        "dr. cash.",
        "dr cash.",
    }
    if lower in explicit:
        return True

    # Title + single token is often "Dr. X" placeholder style.
    # Example: "Dr Cash", "Dr. Smith" (without a full name). In our context we
    # want full names so single-token identities shouldn't become DB entities.
    if re.match(r"^(dr|mr|ms|prof)\\.?\\s+[a-zA-Z]+$", s.strip(), re.I):
        return True

    # Single-token names are hard to disambiguate and frequently appear as
    # placeholders in LLM outputs. Skip them for pundit reliability.
    if _token_count(s) < 2:
        return True

    return False


def filter_real_person_names(names: List[str]) -> List[str]:
    return [n for n in names if not is_placeholder_person_name(n)]


# Known legitimate name particles that can appear mid-name (e.g., "Ludwig van Beethoven")
_KNOWN_NAME_PARTICLES: frozenset[str] = frozenset({
    "van", "von", "de", "del", "della", "di", "da", "dos", "das", "du",
    "la", "le", "el", "al", "bin", "ibn", "ben", "mac", "mc", "o'",
    "st", "st.", "san", "santa", "jr", "jr.", "sr", "sr.", "ii", "iii", "iv",
})

# Known ASR garbage patterns - these fail immediately
_KNOWN_ASR_GARBAGE: frozenset[str] = frozenset({
    # Specific examples from the live site
    "ruby j. to low",
    "ng zdn",
    "sly miss mail",
    "e-modemoo",
    "e modemoo",
    "batuan tashkaya",
    "alex wees",
    "e-modemustock",
    "e modemustock",
    # Common ASR garbage patterns
    "ai assistant",
    "the host",
    "the guest",
    "moderator",
})


def fails_stranger_name_check(name: str) -> bool:
    """
    Conservative heuristic to detect ASR-garbage speaker names.

    This function flags names that appear to be ASR transcription errors
    while being conservative to avoid false positives on real names.

    **Fail examples (ASR garbage):**
    - "Ruby J. To Low" (ASR for Ruby Justice Thelot)
    - "NG ZDN" (all-caps letter salad)
    - "Sly Miss Mail" (ASR garbage)
    - "E-Modemoo" (nonsense compound)
    - "Batuan Tashkaya" (known ASR error)
    - "Alex Wees" (ASR variant of co-host)

    **Pass examples (real names):**
    - "Joseph Wang"
    - "Alfonso Peccatiello"
    - "Ruby Justice Thelot"
    - "Ludwig van Beethoven"

    **Design principle:** Prefer false negatives over false positives.
    If unsure, let the name through (return False).

    Returns:
        True if the name fails the check (likely ASR garbage)
        False if the name passes (looks like a real name or uncertain)
    """
    s = _normalize_name(name)
    if not s:
        return True

    lower = s.lower()

    # 1. Check against known ASR garbage list
    if lower in _KNOWN_ASR_GARBAGE:
        return True

    # 2. Empty or single-token names fail (already covered by is_placeholder_person_name
    #    but we duplicate here for completeness in this stranger check)
    if _token_count(s) < 2:
        return True

    # 3. All-caps letter salad detection
    #    e.g., "NG ZDN", "ABC XYZ" - but allow things like "JFK" as part of a name
    tokens = _get_name_tokens(s)
    if not tokens:
        return True

    # Count how many tokens are all-caps and short (≤3 chars)
    all_caps_short_tokens = sum(
        1 for t in tokens
        if t.isupper() and len(t) <= 3 and not _is_known_initial_or_suffix(t)
    )
    # If more than half the tokens are all-caps short tokens, likely garbage
    if len(tokens) >= 2 and all_caps_short_tokens > len(tokens) / 2:
        return True

    # 4. Mid-name glue word detection
    #    e.g., "Ruby J. To Low" - "To" is a weird mid-name word
    #    But allow known particles like "van", "de", "von"
    if len(tokens) >= 3:
        middle_tokens = tokens[1:-1]  # Exclude first and last
        for mt in middle_tokens:
            mt_lower = mt.lower().rstrip(".")
            # Skip known particles and initials
            if mt_lower in _KNOWN_NAME_PARTICLES:
                continue
            if _is_initial(mt):
                continue
            # Flag common English glue words that shouldn't appear mid-name
            if mt_lower in {"to", "vs", "or", "and", "the", "a", "an", "of", "for", "by", "at", "on", "in", "is", "it"}:
                return True

    # 5. Hyphenated nonsense detection
    #    e.g., "E-Modemoo" - single letter followed by gibberish
    for token in tokens:
        if "-" in token:
            parts = token.split("-")
            # Single letter followed by something weird
            if len(parts) >= 2:
                first_part = parts[0]
                # Single letter hyphen prefix is suspicious unless it's a known pattern
                if len(first_part) == 1 and first_part.isalpha():
                    rest = "-".join(parts[1:])
                    # If the rest doesn't look like a real surname part, flag it
                    # Also flag if it's unusually long (suggests concatenated garbage)
                    if not _looks_like_surname_part(rest):
                        return True
                    # Even if it passes the basic surname check, flag very long ones
                    # Real hyphenated surnames with single-letter prefix are rare
                    if len(rest) > 6:
                        return True

    # 6. Token-level nonsense detection
    #    e.g., "Modemoo", "Tashkaya" - but be conservative (could be foreign names)
    #    Only flag if the token has very unusual patterns
    for token in tokens:
        t_clean = token.lower().replace("-", "").replace("'", "")
        # Skip short tokens and known patterns
        if len(t_clean) <= 3:
            continue
        # Flag tokens that have triple+ repeated letters (very rare in names)
        if re.search(r"(.)\1{2,}", t_clean):
            return True
        # Flag tokens that end in unusual combos suggesting ASR errors
        # e.g., "modemoo" ends in "emoo" which is very unusual
        if re.search(r"(moo|zoo|boo|doo|goo|woo|yoo)$", t_clean) and len(t_clean) > 5:
            # Exception: common surname endings
            if not t_clean.endswith(("wood", "hood", "good")):
                return True

    # If we got here, the name passes the stranger check
    return False


def _get_name_tokens(name: str) -> List[str]:
    """Extract alphabetic tokens from a name string."""
    s = _normalize_name(name)
    # Keep hyphens and apostrophes as part of tokens
    s = re.sub(r"[^\w\s'\-]", " ", s)
    parts = [p.strip() for p in s.split() if p.strip()]
    return parts


def _is_initial(token: str) -> bool:
    """Check if a token looks like an initial (e.g., 'J', 'J.', 'Jr.')."""
    t = token.rstrip(".")
    return len(t) == 1 and t.isalpha()


def _is_known_initial_or_suffix(token: str) -> bool:
    """Check if an all-caps token is a known initial or suffix."""
    t = token.lower().rstrip(".")
    return (
        len(t) == 1  # Single initial like "J"
        or t in {"jr", "sr", "ii", "iii", "iv", "md", "phd", "esq", "cpa"}
    )


def _looks_like_surname_part(s: str) -> bool:
    """
    Heuristic check if a string looks like it could be part of a hyphenated surname.
    e.g., "Gross" in "Wissner-Gross" looks valid, "Modemoo" does not.
    """
    s = (s or "").lower()
    if not s or len(s) < 2:
        return False
    # Common surname patterns
    if len(s) >= 3 and s.isalpha():
        # Check for reasonable vowel/consonant distribution
        vowels = sum(1 for c in s if c in "aeiou")
        consonants = len(s) - vowels
        # Names typically have at least 1 vowel per 4-5 consonants
        if vowels == 0 and consonants >= 3:
            return False
        # Looks reasonably name-like
        return True
    return False


def sanitize_speaker_name_for_display(name: str) -> str:
    """
    Return the name if it passes the stranger check, otherwise return empty string.
    Used for Overton term speaker attribution display.
    """
    if not name or fails_stranger_name_check(name):
        return ""
    return _normalize_name(name)

