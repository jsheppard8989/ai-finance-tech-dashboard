"""
Names that must never appear as Pundits on the site (co-hosts, ASR manglings, handles).

Single source of truth — import from db_manager, enrich_pundits, debate_weekly, etc.
Keep site/debait.html EXCLUDE in sync (see comment there).
"""

from __future__ import annotations

from typing import FrozenSet


EXCLUDED_PUNDIT_NAMES: FrozenSet[str] = frozenset(
    {
        # Moonshots / recurring co-hosts & variants
        "Dylan",
        "Moonshots",
        "Salim Ismail",
        "Dave Blund",
        "Dave Blundin",
        "David Sacks",
        "David Friedberg",
        # Alex Wissner-Gross (co-host; ASR sometimes says "Alex Wey"; on-air "AWG")
        "Alexander Wissner-Gross",
        "Alex Wissner-Gross",
        "Alex Wissne-Gross",  # common ASR typo
        "Alex Wey",
        "AWG",
        # Bad extractions
        "E-Modemustock",
    }
)

_EXCLUDED_LOWER: FrozenSet[str] = frozenset(x.lower() for x in EXCLUDED_PUNDIT_NAMES)


def is_excluded_pundit_name(name: str) -> bool:
    """True if this display name is a blocked co-host / non-pundit (case-insensitive)."""
    n = (name or "").strip()
    return bool(n) and n.lower() in _EXCLUDED_LOWER
