#!/usr/bin/env python3
"""
Source weights for ranking engine.

Loads weights from site/data/source_weights.json to de-emphasize VC cluster
podcasts (a16z, All-In, Moonshots, Dwarkesh) and boost plumbing/niche sources
(Macro Voices, Monetary Matters, Fed Guy, etc.) in Overton and ticker rankings.

Usage:
    from source_weights import get_podcast_weight, get_source_weight_multiplier
    
    weight = get_podcast_weight("The a16z Show")  # Returns 0.3 (relegated)
    weight = get_podcast_weight("Macro Voices")   # Returns 1.8 (boosted)
"""

import json
from pathlib import Path
from typing import Dict, Optional

# Path to weights config
WEIGHTS_PATH = Path(__file__).parent.parent / "site" / "data" / "source_weights.json"

_weights_cache: Optional[Dict] = None


def _load_weights() -> Dict:
    """Load source weights from JSON config, with caching."""
    global _weights_cache
    if _weights_cache is not None:
        return _weights_cache

    if not WEIGHTS_PATH.exists():
        _weights_cache = {}
        return _weights_cache

    try:
        with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
            _weights_cache = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: Could not load source_weights.json: {e}")
        _weights_cache = {}

    return _weights_cache


def get_podcast_weight(podcast_name: str) -> float:
    """
    Get weight multiplier for a podcast source.
    
    Returns:
        Weight < 1.0 for relegated VC cluster podcasts
        Weight > 1.0 for prioritized plumbing/niche podcasts
        Weight = 1.0 for default/unknown podcasts
    """
    weights = _load_weights()
    podcast_weights = weights.get("podcast_weights", {})
    default_weight = podcast_weights.get("_default", 1.0)

    # Check relegated VC cluster
    relegated = podcast_weights.get("relegated_vc_cluster", {})
    if podcast_name in relegated:
        return relegated[podcast_name]

    # Check plumbing/niche sources
    plumbing = podcast_weights.get("plumbing_niche", {})
    if podcast_name in plumbing:
        return plumbing[podcast_name]

    return default_weight


def is_vc_cluster_source(podcast_name: str) -> bool:
    """Check if a podcast is in the relegated VC cluster."""
    weights = _load_weights()
    podcast_weights = weights.get("podcast_weights", {})
    relegated = podcast_weights.get("relegated_vc_cluster", {})
    return podcast_name in relegated


def is_plumbing_source(podcast_name: str) -> bool:
    """Check if a podcast is a prioritized plumbing/niche source."""
    weights = _load_weights()
    podcast_weights = weights.get("podcast_weights", {})
    plumbing = podcast_weights.get("plumbing_niche", {})
    return podcast_name in plumbing


def get_ranking_rules() -> Dict:
    """Get ranking rules from config."""
    weights = _load_weights()
    return weights.get("ranking_rules", {})


def apply_source_weight_to_score(
    base_score: float,
    podcast_name: str,
    score_type: str = "overton"
) -> float:
    """
    Apply source weight multiplier to a base score.
    
    Args:
        base_score: Original score before weighting
        podcast_name: Source podcast name
        score_type: "overton" or "ticker" for different weight rules
        
    Returns:
        Weighted score
    """
    weight = get_podcast_weight(podcast_name)
    
    # For ticker scores, apply additional rules
    if score_type == "ticker":
        rules = get_ranking_rules().get("ticker", {})
        if is_vc_cluster_source(podcast_name):
            weight *= rules.get("vc_cluster_weight_multiplier", 0.4)
        elif is_plumbing_source(podcast_name):
            weight *= rules.get("plumbing_source_weight_multiplier", 1.8)
    
    return base_score * weight


def get_vc_cluster_mention_cap() -> int:
    """Get max mentions from VC cluster to count in Overton ranking."""
    rules = get_ranking_rules().get("overton", {})
    return rules.get("vc_cluster_mention_cap", 3)


# Convenience lists for filtering
VC_CLUSTER_PODCASTS = [
    "The a16z Show",
    "All-In with Chamath, Jason, Sacks & Friedberg",
    "Dwarkesh Podcast",
    "Moonshots with Peter Diamandis",
    "BG2 with Brad Gerstner and Bill Gurley",
    "Latent Space: The AI Engineer Podcast",
]

PLUMBING_NICHE_PODCASTS = [
    "Monetary Matters with Jack Farley",
    "Macro Voices",
]


if __name__ == "__main__":
    # Test the weights
    print("Source Weight Tests:")
    print("-" * 40)
    
    test_sources = [
        "The a16z Show",
        "All-In with Chamath, Jason, Sacks & Friedberg",
        "Macro Voices",
        "Monetary Matters with Jack Farley",
        "Unknown Podcast",
    ]
    
    for src in test_sources:
        w = get_podcast_weight(src)
        vc = is_vc_cluster_source(src)
        plumb = is_plumbing_source(src)
        print(f"  {src}: weight={w}, vc_cluster={vc}, plumbing={plumb}")
