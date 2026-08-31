"""
Strip CJK / fullwidth punctuation from content exported to the public site.
Also apply conservative ASR/transcription corrections for well-known proper nouns.

LLM or ASR glitches occasionally inject characters that read as "hacked" to visitors,
or mangle well-known company/person names (e.g., "OpenEye" instead of "OpenAI").

Applied recursively to JSON structures before writing site/data/*.json and data.js.
"""

from __future__ import annotations

import re
from typing import Any

# Han, Hiragana/Katakana, Hangul, CJK symbols / fullwidth forms
_CJK_RE = re.compile(
    "["
    "\u4e00-\u9fff"  # CJK Unified
    "\u3400-\u4dbf"  # Extension A
    "\uf900-\ufaff"  # Compatibility
    "\u3000-\u303f"  # CJK punctuation
    "\u3040-\u309f"  # Hiragana
    "\u30a0-\u30ff"  # Katakana
    "\uac00-\ud7af"  # Hangul
    "\uff00-\uffef"  # Fullwidth ASCII
    "]"
)

# Conservative ASR correction glossary: only high-confidence, well-known substitutions.
# Format: (pattern, replacement, case_sensitive)
# Patterns are compiled as word-boundary-aware regexes to avoid false positives.
ASR_CORRECTIONS: list[tuple[str, str, bool]] = [
    # AI Companies
    ("OpenEye", "OpenAI", True),
    
    # Well-known people (AI/Tech/Finance)
    ("Sam Alman", "Sam Altman", True),
    ("Alman's", "Altman's", True),
    
    # Autonomous vehicles
    ("Weimo", "Waymo", True),
    ("Weimo's", "Waymo's", True),
    
    # AI products - careful with "Grockbot" vs "Grok"
    # The episode title uses "Grokbots" (correct). "Grockbot" in summary text is the error.
    ("Grockbot", "Grok", True),
    ("Grockbots", "Grok instances", True),
    
    # Finance personalities
    ("Warren Pi([^a-zA-Z])", r"Warren Pies\1", False),  # Warren Pi followed by non-letter
    ("Warren Pi$", "Warren Pies", False),  # Warren Pi at end of string
    ("Warren Pious", "Warren Pies", True),
    
    # Research firms
    ("Simming Analysis", "SemiAnalysis", True),
    
    # AI researchers/professors
    ("Anamah Anankumar", "Anima Anandkumar", True),
    ("Anamah Anandkumar", "Anima Anandkumar", True),
    ("Anamah([^a-zA-Z])", r"Anima\1", True),  # Anamah alone followed by non-letter
    ("Anamah$", "Anima", True),  # Anamah at end of string
    ("Anamah's", "Anima's", True),
    
    # Podcast host names (a16z)
    ("Jen Cos", "Jen Costa", True),
    ("An Eshicharya", "Anish Acharya", True),
    ("an Eshicharya", "Anish Acharya", True),
]

# Pre-compile the correction patterns for efficiency
_ASR_COMPILED: list[tuple[re.Pattern, str]] = []


def _compile_asr_patterns() -> None:
    """Compile ASR correction patterns on first use."""
    global _ASR_COMPILED
    if _ASR_COMPILED:
        return
    for pattern, replacement, case_sensitive in ASR_CORRECTIONS:
        flags = 0 if case_sensitive else re.IGNORECASE
        # Use word boundaries for simple patterns, raw regex for complex ones
        # Complex patterns contain regex metacharacters: ( [ $ ^ * + ? { |
        if any(c in pattern for c in "([{}$^*+?|\\."):
            # Complex pattern - use as-is
            compiled = re.compile(pattern, flags)
        else:
            # Simple word/phrase - add word boundaries
            compiled = re.compile(r"\b" + re.escape(pattern) + r"\b", flags)
        _ASR_COMPILED.append((compiled, replacement))


def correct_asr_errors(text: str) -> str:
    """Apply conservative ASR corrections to a string."""
    if not text:
        return text
    _compile_asr_patterns()
    result = text
    for pattern, replacement in _ASR_COMPILED:
        result = pattern.sub(replacement, result)
    return result


def strip_cjk_public_text(obj: Any) -> Any:
    """Recursively remove CJK-range characters from strings; pass through other types."""
    if isinstance(obj, str):
        return _CJK_RE.sub("", obj)
    if isinstance(obj, dict):
        return {k: strip_cjk_public_text(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [strip_cjk_public_text(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(strip_cjk_public_text(x) for x in obj)
    return obj


def sanitize_public_text(obj: Any) -> Any:
    """
    Full sanitization pipeline for public site text:
    1. Strip CJK/fullwidth characters
    2. Apply conservative ASR corrections for proper nouns
    
    Use this function for all text destined for public display.
    """
    if isinstance(obj, str):
        text = _CJK_RE.sub("", obj)
        text = correct_asr_errors(text)
        return text
    if isinstance(obj, dict):
        return {k: sanitize_public_text(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_public_text(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(sanitize_public_text(x) for x in obj)
    return obj
