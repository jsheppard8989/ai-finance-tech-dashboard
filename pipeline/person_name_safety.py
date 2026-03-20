#!/usr/bin/env python3
"""
Utilities for filtering clearly non-real / placeholder person names.

Goal: prevent bogus entities like "Guest Expert" or "Dr. Cash" from being
created/enriched/exported as pundits.
"""

from __future__ import annotations

import re
from typing import List


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

