#!/usr/bin/env python3
"""
Saturated / Established Terms Management

Terms that have become so widely discussed they no longer represent "new ideas"
for the Overton Window. These are demoted to an "Established" tier so they
don't crowd out emerging concepts.

Criteria for inclusion:
- High mention counts over extended periods
- Dictionary-level generality (everyone knows what AGI means)
- Recurring but no longer novel in discourse
"""

from typing import Set, Dict, Optional
from dataclasses import dataclass


@dataclass
class EstablishedTerm:
    """A term that has graduated to the Established tier."""
    term: str
    reason: str
    min_mentions_before_established: int = 10


# Core saturated terms that should be demoted to Established tier.
# These dominate raw mention counts but no longer represent "new ideas."
ESTABLISHED_TERMS: Dict[str, EstablishedTerm] = {
    "AGI": EstablishedTerm(
        term="AGI",
        reason="Foundational concept discussed in virtually every AI podcast; saturated discourse",
        min_mentions_before_established=5,
    ),
    "Autonomy": EstablishedTerm(
        term="Autonomy",
        reason="Generic capability term; too broad to represent a specific emerging idea",
        min_mentions_before_established=5,
    ),
    "Authenticity": EstablishedTerm(
        term="Authenticity",
        reason="Generic philosophical term; not specific to tech/finance discourse",
        min_mentions_before_established=5,
    ),
    "AI Boom": EstablishedTerm(
        term="AI Boom",
        reason="Market-level macro term; describes the entire sector, not a specific concept",
        min_mentions_before_established=5,
    ),
    "Artificial General Intelligence": EstablishedTerm(
        term="Artificial General Intelligence",
        reason="Alias of AGI; same saturation issue",
        min_mentions_before_established=5,
    ),
    "ASI": EstablishedTerm(
        term="ASI",
        reason="Foundational superintelligence concept; widely discussed baseline",
        min_mentions_before_established=8,
    ),
    "Artificial Super Intelligence": EstablishedTerm(
        term="Artificial Super Intelligence",
        reason="Alias of ASI",
        min_mentions_before_established=8,
    ),
    "Machine Learning": EstablishedTerm(
        term="Machine Learning",
        reason="Foundational ML term; dictionary-level generality",
        min_mentions_before_established=5,
    ),
    "Deep Learning": EstablishedTerm(
        term="Deep Learning",
        reason="Foundational neural network term; too generic",
        min_mentions_before_established=5,
    ),
    "Neural Networks": EstablishedTerm(
        term="Neural Networks",
        reason="Foundational AI architecture term; dictionary-level",
        min_mentions_before_established=5,
    ),
}

# Case-insensitive lookup set for quick checks
_ESTABLISHED_TERMS_LOWER: Set[str] = {t.lower() for t in ESTABLISHED_TERMS.keys()}


def is_established_term(term: str) -> bool:
    """Check if a term is in the Established tier (case-insensitive)."""
    if not term:
        return False
    return term.strip().lower() in _ESTABLISHED_TERMS_LOWER


def get_established_term_info(term: str) -> Optional[EstablishedTerm]:
    """Get the EstablishedTerm metadata if the term is established."""
    if not term:
        return None
    term_clean = term.strip()
    # Try exact match first
    if term_clean in ESTABLISHED_TERMS:
        return ESTABLISHED_TERMS[term_clean]
    # Try case-insensitive
    for key, val in ESTABLISHED_TERMS.items():
        if key.lower() == term_clean.lower():
            return val
    return None


def get_all_established_terms() -> Set[str]:
    """Return all established term strings (original casing)."""
    return set(ESTABLISHED_TERMS.keys())


def get_established_terms_for_export() -> list:
    """
    Return established terms data for site export.
    These can be displayed in an "Established Concepts" section.
    """
    results = []
    seen_lower = set()
    for term, info in ESTABLISHED_TERMS.items():
        # Dedupe aliases (AGI vs Artificial General Intelligence)
        if term.lower() in seen_lower:
            continue
        # Skip aliases that reference a canonical
        if "alias" in info.reason.lower():
            continue
        seen_lower.add(term.lower())
        results.append({
            "term": term,
            "reason": info.reason,
            "tier": "established",
        })
    return results


# Specificity penalty for ranking: established terms get a multiplier < 1.0
# so they rank lower even with high mention counts.
ESTABLISHED_TERM_RANKING_MULTIPLIER = 0.15  # 85% penalty to novelty score


def get_specificity_multiplier(term: str) -> float:
    """
    Return a multiplier for the term's specificity in novelty scoring.
    
    - Established/saturated terms: 0.15 (heavy penalty)
    - Normal terms: 1.0 (no penalty)
    """
    if is_established_term(term):
        return ESTABLISHED_TERM_RANKING_MULTIPLIER
    return 1.0
