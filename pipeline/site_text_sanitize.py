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
    3. Drop generic reader-advice sentences ("Investors should…") from card claim fields

    Use this function for all text destined for public display.
    """
    return _sanitize_strings(clean_reader_advice(obj))


def _sanitize_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        text = _CJK_RE.sub("", obj)
        text = correct_asr_errors(text)
        return text
    if isinstance(obj, dict):
        return {k: _sanitize_strings(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_strings(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(_sanitize_strings(x) for x in obj)
    return obj


# ---------------------------------------------------------------------------
# Reader-advice backstop (Sep 2026). Card-level fields must state a claim, not
# tell the reader what to do. The prompts ask for this; this is the safety net
# so a generic "Investors should…" sentence never reaches the public site.
# ---------------------------------------------------------------------------

_READER_ADVICE_RE = re.compile(
    r"^\s*(?:"
    # "Investors should…", "Healthcare investors need to…", "Policymakers and investors must…"
    r"(?:[\w-]+\s+){0,3}(?:investors?|listeners|viewers|traders|allocators|readers)\s+"
    r"(?:should|must|need\s+to|needs\s+to|are\s+advised|may\s+want\s+to|might\s+want\s+to|"
    r"would\s+do\s+well|ought\s+to|are\s+encouraged|can\s+consider|could\s+consider)"
    r"|(?:it\s+is|it's)\s+(?:crucial|important|essential|critical|wise|advisable)\s+for\s+investors"
    # Bare imperatives aimed at the reader
    r"|(?:consider|invest\s+in|focus\s+on|prioritize|monitor|watch\s+for|keep\s+an\s+eye)\b"
    r")",
    re.IGNORECASE,
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")

# Fields that render as a one-line claim on cards, pop-ups, and pundit rows.
READER_ADVICE_FIELDS = frozenset(
    {"key_takeaway", "investment_thesis", "last_main_idea", "main_idea", "supporting_takeaway"}
)
# Fields that are lists of short claim bullets.
READER_ADVICE_LIST_FIELDS = frozenset({"key_takeaways"})


_ADVICE_VERB = (
    r"(?:investors?|listeners|traders|allocators)\s+"
    r"(?:should|must|need\s+to|needs\s+to|are\s+advised|may\s+want\s+to|might\s+want\s+to|ought\s+to)\b"
)
# "<claim>; investors should…" or "<claim>, and investors should…": keep the claim, cut the advice.
_ADVICE_TAIL_RE = re.compile(r"\s*(?:;|,\s*and|,\s*so|—|--)\s+" + _ADVICE_VERB + r".*$", re.IGNORECASE)
# Advice anywhere else in the sentence ("If X holds, investors should…"): drop the sentence.
_ADVICE_ANYWHERE_RE = re.compile(r"\b" + _ADVICE_VERB, re.IGNORECASE)


def is_reader_advice(sentence: str) -> bool:
    return bool(sentence and (_READER_ADVICE_RE.match(sentence) or _ADVICE_ANYWHERE_RE.search(sentence)))


def _clean_sentence(sentence: str) -> str:
    if _READER_ADVICE_RE.match(sentence):
        return ""
    cut = _ADVICE_TAIL_RE.sub("", sentence).rstrip(" ,;")
    if cut != sentence.rstrip(" ,;"):
        cut = cut if cut.endswith((".", "!", "?")) else cut + "."
        return "" if _ADVICE_ANYWHERE_RE.search(cut) else cut
    return "" if _ADVICE_ANYWHERE_RE.search(sentence) else sentence


def strip_reader_advice(text: str) -> str:
    """Drop sentences (or trailing clauses) that address the reader with generic advice. Returns '' if nothing is left."""
    if not isinstance(text, str) or not text.strip():
        return text if isinstance(text, str) else ""
    parts = _SENTENCE_SPLIT_RE.split(text.strip())
    kept = [c for c in (_clean_sentence(p) for p in parts) if c]
    return " ".join(kept).strip()


def clean_reader_advice(obj: Any) -> Any:
    """Recursively apply strip_reader_advice to card-level claim fields only."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in READER_ADVICE_FIELDS and isinstance(v, str):
                out[k] = strip_reader_advice(v)
            elif k in READER_ADVICE_LIST_FIELDS and isinstance(v, list):
                cleaned = [strip_reader_advice(x) if isinstance(x, str) else clean_reader_advice(x) for x in v]
                out[k] = [x for x in cleaned if not (isinstance(x, str) and not x)]
            else:
                out[k] = clean_reader_advice(v)
        return out
    if isinstance(obj, list):
        return [clean_reader_advice(x) for x in obj]
    if isinstance(obj, tuple):
        return tuple(clean_reader_advice(x) for x in obj)
    return obj
