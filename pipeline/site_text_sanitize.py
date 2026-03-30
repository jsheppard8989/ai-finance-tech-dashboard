"""
Strip CJK / fullwidth punctuation from content exported to the public site.

LLM or ASR glitches occasionally inject characters that read as "hacked" to visitors.
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
