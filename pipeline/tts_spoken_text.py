#!/usr/bin/env python3
"""Expand finance figures into spoken English before ElevenLabs TTS.

Models often misread 5.00% as "five hundred zero percent". Editorial scripts keep
numerals; this transform is applied only on the TTS path.
"""

from __future__ import annotations

import re

_ONES = "zero one two three four five six seven eight nine".split()
_TEENS = (
    "ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen"
).split()
_TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
_SCALE = {"k": "thousand", "m": "million", "b": "billion", "t": "trillion"}


def _small_int(n: int) -> str:
    if n < 0:
        return "minus " + _small_int(-n)
    if n < 10:
        return _ONES[n]
    if n < 20:
        return _TEENS[n - 10]
    if n < 100:
        tens, ones = divmod(n, 10)
        return _TENS[tens] if ones == 0 else f"{_TENS[tens]}-{_ONES[ones]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        if rest == 0:
            return f"{_ONES[hundreds]} hundred"
        return f"{_ONES[hundreds]} hundred {_small_int(rest)}"
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        if rest == 0:
            return f"{_small_int(thousands)} thousand"
        return f"{_small_int(thousands)} thousand {_small_int(rest)}"
    return str(n)


def _number_words(int_part: str, frac: str = "") -> str:
    words = _small_int(int(int_part))
    frac = (frac or "").rstrip("0")
    if not frac:
        return words
    digits = " ".join(_ONES[int(ch)] for ch in frac)
    return f"{words} point {digits}"


def _split_decimal(num: str) -> tuple[str, str]:
    if "." in num:
        whole, frac = num.split(".", 1)
        return whole, frac
    return num, ""


def spoken_for_tts(text: str) -> str:
    """Return a copy of text with percents, dollars, and basis points spoken out."""
    if not text:
        return text
    out = text

    def money_scale(m: re.Match) -> str:
        words = _number_words(*_split_decimal(m.group(1)))
        scale = _SCALE[m.group(2).lower()]
        return f"{words} {scale} dollars"

    def money_word_scale(m: re.Match) -> str:
        words = _number_words(*_split_decimal(m.group(1)))
        scale = m.group(2).lower().rstrip("s")
        return f"{words} {scale} dollars"

    def money_plain(m: re.Match) -> str:
        words = _number_words(*_split_decimal(m.group(1)))
        return f"{words} dollars"

    def percent(m: re.Match) -> str:
        return _number_words(*_split_decimal(m.group(1))) + " percent"

    def basis_points(m: re.Match) -> str:
        return _number_words(*_split_decimal(m.group(1))) + " basis points"

    out = re.sub(
        r"\$(\d+(?:\.\d+)?)([kKmMbBtT])\b",
        money_scale,
        out,
    )
    out = re.sub(
        r"\$(\d+(?:\.\d+)?)\s+(million|billion|trillion|thousand)s?\b",
        money_word_scale,
        out,
        flags=re.IGNORECASE,
    )
    out = re.sub(r"\$(\d+(?:\.\d+)?)\b", money_plain, out)
    out = re.sub(r"(\d+(?:\.\d+)?)%", percent, out)
    out = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)\s*bps?\b", basis_points, out, flags=re.IGNORECASE)
    return out
