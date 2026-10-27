"""
Names that must never appear as Pundits on the site (co-hosts, ASR manglings, handles).

Single source of truth — import from db_manager, enrich_pundits, debate_weekly, etc.
Keep site/debait.html EXCLUDE in sync (see comment there).

NOTE: ASR variants are handled via canonicalization in person_name_safety.py.
      is_excluded_pundit_name() canonicalizes first, so "Dave Blenden" → "Dave Blundin" → excluded.

Culture one-off episode gating:
  a16z and other podcasts occasionally produce culture/entertainment episodes that aren't
  AI/finance relevant. These are HARD SKIP — do not ingest, do not ask. Only AI/finance
  episodes go through. Use is_culture_oneoff_episode() to gate ingest.

  Scrubbed 2026-09-20: Nas, Grandmaster Caz, Steve Stoute hip-hop pioneers episode (Jared via Ditka).
"""

from __future__ import annotations

from typing import FrozenSet

from person_name_safety import canonicalize_person_name


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
        # Culture one-off guests (scrubbed 2026-09-20 — hip-hop pioneers episode)
        "Grandmaster Caz",
        "Steve Stoute",
        "Steve Stout",  # ASR variant
        # Oct 23 2026 sweep follow-ups (c23): unverifiable garbled names; removed, not guessed
        "Dino Mavruchus",
        "Honorable Duffy",
    }
)


# Guest appearances that were really mentions (person named/clipped, not a guest).
# (name, episode_title) pairs; matched case-insensitively. The export skips that
# appearance and uses the person's next real guest appearance, if any.
EXCLUDED_GUEST_APPEARANCES: FrozenSet[tuple] = frozenset(
    {
        # Dwarkesh Oct 22 2026 Intel fab episode: Elon is quoted (Terafab clip), not a guest.
        ("Elon Musk", "What will computer chips look like in 2045?"),
        # Moonshots #303 (Oct 17 2026): Dawn Mussallem (Fountain Life CMO) is a sponsor read,
        # not a guest; G, Oct 22 2026. DB name is ASR-garbled; corrected forms listed too.
        ("Dr. Don Musalam", "Flying Tesla Car, Robot Brains Halving in Cost Every 3 Weeks, and Why Incentives Decide AI Alignment | #303"),
        ("Don Musalam", "Flying Tesla Car, Robot Brains Halving in Cost Every 3 Weeks, and Why Incentives Decide AI Alignment | #303"),
        ("Dr. Dawn Mussallem", "Flying Tesla Car, Robot Brains Halving in Cost Every 3 Weeks, and Why Incentives Decide AI Alignment | #303"),
        ("Dawn Mussallem", "Flying Tesla Car, Robot Brains Halving in Cost Every 3 Weeks, and Why Incentives Decide AI Alignment | #303"),
    }
)
_EXCLUDED_APPEARANCES_LOWER = frozenset((n.lower(), t.lower()) for n, t in EXCLUDED_GUEST_APPEARANCES)


def is_excluded_guest_appearance(name: str, episode_title: str) -> bool:
    """True if this (person, episode) guest appearance is a known mention-only row."""
    return ((name or "").strip().lower(), (episode_title or "").strip().lower()) in _EXCLUDED_APPEARANCES_LOWER


# Confirmed guests the guest check can't verify from title/show notes/labels (ASR-garbled
# names, sparse notes). (DB name, episode_title) pairs; corrected names come from
# summary_overrides.json global_name_replacements. Oct 22 2026, checked by G.
CONFIRMED_GUEST_APPEARANCES: FrozenSet[tuple] = frozenset(
    {
        ("Adam Pervene", "Adam Foroughi, Applovin CEO: Surviving a 92% Drawdown, Ads as ML 1.0 & the $50B Game Ad Market"),
        ("Eden Ha", "Why Video Agent models are next — Ethan He, xAI Grok Imagine"),
        ("Andrew Wang", "How Valon Rebuilt a $13 Trillion Industry From Scratch"),
        ("Richard Socher", "Recursive's $670M Bet on Self-Improving AI, Sonnet 5.5 Hits 70%, Elon Co-Leads Pentagon Push | EP #299"),
        ("DJ Smith", "The Reality of AI-Powered Cyberattacks | Truffle Security & Socket"),
        ("Dylan Araps", "The Reality of AI-Powered Cyberattacks | Truffle Security & Socket"),
        ("Joel Deligarza", "The Reality of AI-Powered Cyberattacks | Truffle Security & Socket"),
        ("Peter Ludwig", "Why Physical AI Is the Next Frontier | Applied Intuition"),
        ("Jeff Wu", "Jake Paul & Anti Fund: From Creator to Investor"),
        # Oct 27 2026: ASR "Joel Amond" = Joe Liemandt (entity 582); display name fixed by pundit_overrides id 582.
        ("Joel Amond", "Reinventing School for the AI Era | Joe Liemandt, Gagan Biyani & Erik Torenberg"),
    }
)


def _norm_title(t: str) -> str:
    return " ".join((t or "").lower().split())


_CONFIRMED_LOWER = frozenset((n.lower(), _norm_title(t)) for n, t in CONFIRMED_GUEST_APPEARANCES)


def is_confirmed_guest_appearance(name: str, episode_title: str) -> bool:
    """True if this (person, episode) is a pinned, human-confirmed guest appearance."""
    return ((name or "").strip().lower(), _norm_title(episode_title)) in _CONFIRMED_LOWER


# Title keywords that indicate a culture one-off episode (non-AI/finance)
# These episodes are HARD SKIP — do not ingest, do not ask. Only AI/finance episodes go through.
CULTURE_ONEOFF_KEYWORDS: FrozenSet[str] = frozenset(
    {
        "hip-hop",
        "hip hop",
        "hiphop",
        "paid in full",
        "pioneers their due",
        "grandmaster caz",
        "music pioneers",
        "culture one-off",
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
_CULTURE_KEYWORDS_LOWER: FrozenSet[str] = frozenset(x.lower() for x in CULTURE_ONEOFF_KEYWORDS)


def is_excluded_pundit_name(name: str) -> bool:
    """
    True if this display name is a blocked co-host / non-pundit (case-insensitive).
    
    First canonicalizes the name to handle ASR variants:
      - "Dave Blenden" → "Dave Blundin" → excluded
      - "Alex Weesner" → "Alex Wissner-Gross" → excluded
    """
    n = (name or "").strip()
    if not n:
        return False
    # Canonicalize to catch ASR variants (e.g. "Blenden" → "Blundin")
    canonical = canonicalize_person_name(n)
    return canonical.lower() in _EXCLUDED_LOWER


# Oct 20 2026 (G(ai)ndolf): host rows hidden by DB entity id, so a misspelled or later-renamed
# name can't slip a host onto the public pundit list. Keep in sync with summary_overrides.json
# 'pundit_excludes' (export_data applies both).
EXCLUDED_PUNDIT_IDS: FrozenSet[int] = frozenset(
    {
        132,  # David Friedberg (ASR "David Freiberg")
        36,  # David Friedberg (ASR "Jason Friedberg")
        193,  # Alex Wissner-Gross (ASR "Alex Weiser Gross")
        584,  # Erik Torenberg (The a16z Show host; Oct 27 2026 sweep_1027 #10)
    }
)


def is_excluded_pundit(pundit_id=None, name: str = "") -> bool:
    """True if a pundit row must never be public: blocked by id, or its (corrected) name is a
    blocked co-host. Call with the name AFTER export name overrides so any spelling is caught."""
    try:
        if pundit_id is not None and int(pundit_id) in EXCLUDED_PUNDIT_IDS:
            return True
    except (TypeError, ValueError):
        pass
    return is_excluded_pundit_name(name)


def is_excluded_debater_name(name: str) -> bool:
    """
    True if this name must not appear as a weekly debate cast member.
    
    Canonicalizes to handle ASR variants before checking exclusion lists.
    """
    n = (name or "").strip()
    if not n:
        return True
    # Canonicalize to catch ASR variants
    canonical = canonicalize_person_name(n)
    low = canonical.lower()
    return low in _EXCLUDED_LOWER or low in _EXCLUDED_DEBATER_LOWER


def is_culture_oneoff_episode(title: str) -> bool:
    """
    True if episode title contains culture one-off keywords (hip-hop, etc.).
    
    These episodes are NOT AI/finance relevant — HARD SKIP, do not ingest.
    Only AI/finance-relevant episodes should go through the pipeline.
    
    Returns:
        True if episode should be skipped (culture one-off detected)
        False if episode appears to be AI/finance relevant
    """
    t = (title or "").lower()
    if not t:
        return False
    return any(kw in t for kw in _CULTURE_KEYWORDS_LOWER)
