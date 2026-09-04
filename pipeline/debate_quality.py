#!/usr/bin/env python3
"""
Editorial quality gates for The Long and Short of It debate contracts.

Used by debate_weekly.py (generation) and export_data.py (publish stamp).
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from pundit_exclusions import is_excluded_debater_name

_PROMPT_SIMILARITY_REJECT = 0.72
_MIN_EDITORIAL_CHARS = 80

_HEADLINE_STOPWORDS = frozenset(
    {
        "the",
        "will",
        "navigating",
        "building",
        "investing",
        "stock",
        "market",
        "ground",
        "infrastructure",
        "from",
        "models",
        "mobility",
        "inventing",
        "renaissance",
        "special",
        "episode",
        "this",
        "also",
        "touches",
        "inside",
        "when",
        "music",
        "stops",
        "openclaw",
        "macro",
        "voices",
        "technology",
        "culture",
        "next",
        "interface",
        "reality",
        "software",
        "hard",
        "asset",
    }
)

_PLACEHOLDER_DEBATER = re.compile(
    r"^(pundit\s*[ab]|debater\s*[ab]|john\s+doe|jane\s+doe|guest\s+\d+|unknown)$",
    re.I,
)

_VALID_SIDE_LABELS = frozenset({"affirmative", "negative"})


def _norm_prompt(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def prompt_similarity(a: str, b: str) -> float:
    na, nb = _norm_prompt(a), _norm_prompt(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def validate_prompt_not_repetitive(
    prompt: str,
    prior_prompts: List[str],
    *,
    threshold: float = _PROMPT_SIMILARITY_REJECT,
) -> Tuple[bool, str]:
    for prior in prior_prompts:
        if not prior:
            continue
        sim = prompt_similarity(prompt, prior)
        if sim >= threshold:
            return False, f"Prompt too similar to a recent contract ({sim:.0%} overlap)."
    return True, ""


def validate_resolution_clarity(contract: Dict[str, Any]) -> Tuple[bool, str]:
    rc = contract.get("resolution_clarity")
    if not isinstance(rc, dict):
        return False, "resolution_clarity missing or not an object."
    source = (rc.get("source_of_truth") or "").strip()
    criteria = rc.get("resolution_criteria") or []
    if not source:
        return False, "resolution_clarity.source_of_truth is empty."
    if not isinstance(criteria, list) or not any(str(c).strip() for c in criteria):
        return False, "resolution_clarity.resolution_criteria is empty."
    return True, ""


def validate_editorial_note(note: str) -> Tuple[bool, str]:
    text = (note or "").strip()
    if len(text) < _MIN_EDITORIAL_CHARS:
        return False, f"editorial_note too short ({len(text)} chars; need {_MIN_EDITORIAL_CHARS}+)."
    if not re.search(r"\bwe\b", text, re.I):
        return False, "editorial_note should explain why we picked this topic (first-person plural)."
    return True, ""


def validate_debaters(name_a: str, name_b: str) -> Tuple[bool, str]:
    a = (name_a or "").strip()
    b = (name_b or "").strip()
    if not a or not b:
        return False, "Both debater names are required."
    if a.lower() == b.lower():
        return False, "Debaters must be distinct people."
    for name in (a, b):
        if _PLACEHOLDER_DEBATER.match(name):
            return False, f"Placeholder debater name: {name!r}."
        if is_excluded_debater_name(name):
            return False, f"Blocked debater name: {name!r}."
        if name.lower() in _VALID_SIDE_LABELS:
            continue
        parts = [p for p in re.split(r"\s+", name) if p]
        if len(parts) < 2:
            return False, f"Debater name looks incomplete: {name!r}."
    return True, ""


def validate_spx_strike_plausible(prompt: str, spx_ref: Optional[float]) -> Tuple[bool, str]:
    if not spx_ref or spx_ref <= 1000:
        return True, ""
    pl = (prompt or "").lower()
    if not re.search(r"s&p|s\s*&\s*p\s*500|\bspx\b|\bsp\s*500\b", pl):
        return True, ""
    nums: List[float] = []
    for m in re.finditer(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{4,6}(?:\.\d+)?\b", prompt):
        try:
            nums.append(float(m.group(0).replace(",", "")))
        except ValueError:
            continue
    bullish = bool(re.search(r"\b(close\s+above|exceed|above|break\s+above|surpass)\b", pl))
    for n in nums:
        if bullish:
            if n <= spx_ref * 1.005:
                return (
                    False,
                    f"S&P threshold {n:,.0f} is at/below spot ~{spx_ref:,.0f}; question is already true or trivial.",
                )
            if n > spx_ref * 1.18:
                return (
                    False,
                    f"S&P threshold {n:,.0f} implies >18% rally from ~{spx_ref:,.0f} in 42 days — pick a sharper policy/macro theme instead.",
                )
    return True, ""


def validate_contract_publishable(
    contract: Dict[str, Any],
    prior_prompts: Optional[List[str]] = None,
    *,
    spx_ref: Optional[float] = None,
    btc_ref: Optional[float] = None,
) -> Tuple[bool, str, List[str]]:
    """
    Returns (ok, first_error, all_errors).
    btc_ref reserved for future BTC strike checks (macro sanity lives in debate_weekly).
    """
    del btc_ref  # unused for now; kept for call-site symmetry
    errors: List[str] = []
    prompt = (contract.get("prompt") or "").strip()
    if not prompt:
        errors.append("empty prompt")
    elif not prompt.endswith("?"):
        errors.append("prompt must be a Yes/No question ending with '?'.")
    elif len(prompt) < 24:
        errors.append("prompt too short to be a falsifiable contract.")

    for check in (
        lambda: validate_prompt_not_repetitive(prompt, prior_prompts or []),
        lambda: validate_resolution_clarity(contract),
        lambda: validate_editorial_note(str(contract.get("editorial_note") or "")),
        lambda: validate_debaters(
            str(contract.get("debater_a") or ""),
            str(contract.get("debater_b") or ""),
        ),
        lambda: validate_spx_strike_plausible(prompt, spx_ref),
    ):
        ok, err = check()
        if not ok and err:
            errors.append(err)

    if errors:
        return False, errors[0], errors
    return True, "", []


def stamp_contract_publishable(
    contract: Dict[str, Any],
    prior_prompts: Optional[List[str]] = None,
    *,
    spx_ref: Optional[float] = None,
    btc_ref: Optional[float] = None,
) -> Dict[str, Any]:
    """Return a copy of contract with publishable + publish_block_reason set."""
    out = dict(contract)
    ok, reason, all_errs = validate_contract_publishable(
        contract,
        prior_prompts,
        spx_ref=spx_ref,
        btc_ref=btc_ref,
    )
    out["publishable"] = ok
    out["publish_block_reason"] = "" if ok else reason
    if all_errs and not ok:
        out["publish_block_reasons"] = all_errs
    return out
