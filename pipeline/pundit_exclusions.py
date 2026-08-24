"""
Names that must never appear as Pundits on the site (co-hosts, ASR manglings, handles).

Single source of truth — import from db_manager, enrich_pundits, debate_weekly, etc.
Keep site/debait.html EXCLUDE in sync (see comment there).
"""

from __future__ import annotations

from typing import FrozenSet


EXCLUDED_PUNDIT_NAMES: FrozenSet[str] = frozenset(
    {
        # a16z — firm GPs / hosts (appear on many episodes as "guests"; not third-party pundits)
        "Ben Horowitz",
        "Marc Andreessen",
        "Mark Andreessen",  # common spelling slip / ASR
        # Moonshots / recurring co-hosts & variants
        "Peter Diamandis",
        "Dylan",
        "Moonshots",
        "Salim Ismail",
        "Dave Blund",
        "Dave Blundin",
        "David Sacks",
        "David Sachs",  # ASR typo for David Sacks (All-In host)
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

# Celebrities / placeholders that must never be debate cast (even if in pundits export)
EXCLUDED_DEBATER_NAMES: FrozenSet[str] = frozenset(
    {
        "Mark Zuckerberg",
        "Priscilla Chan",
        "Elon Musk",
        "John Doe",
        "Jane Doe",
        "Pundit A",
        "Pundit B",
        "Debater A",
        "Debater B",
    }
)

_EXCLUDED_LOWER: FrozenSet[str] = frozenset(x.lower() for x in EXCLUDED_PUNDIT_NAMES)
_EXCLUDED_DEBATER_LOWER: FrozenSet[str] = frozenset(x.lower() for x in EXCLUDED_DEBATER_NAMES)


def is_excluded_pundit_name(name: str) -> bool:
    """True if this display name is a blocked co-host / non-pundit (case-insensitive)."""
    n = (name or "").strip()
    return bool(n) and n.lower() in _EXCLUDED_LOWER


def is_excluded_debater_name(name: str) -> bool:
    """True if this name must not appear as a weekly debate cast member."""
    n = (name or "").strip()
    if not n:
        return True
    low = n.lower()
    return low in _EXCLUDED_LOWER or low in _EXCLUDED_DEBATER_LOWER
