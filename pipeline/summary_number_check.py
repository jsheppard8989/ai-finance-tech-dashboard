#!/usr/bin/env python3
"""Drop generated summary numbers that are not in the episode transcript.

This runs in the summarizer / Deep Dive step (not export). Export-time
overrides may add sourced figures such as "about 13%", so this check must
not run on already-exported text.

Our-voice numbers in summaries, takeaways, investment theses, and Deep Dive
narrative prose must appear in the transcript (digits, number words, ranges,
%, $, and million/billion/trillion scales are normalized). Attributed
verbatim quotes are checked only for being present in the transcript as-is.
If there is no transcript, the check skips with a warning and does not block.
Unsupported numbers: drop the sentence or bullet (or a cleanly separable
clause / parenthetical) and log a WARN naming what was removed.

Falsification tracks and watch items are skipped: those lines are constructed
test conditions and are required to carry a threshold the speaker may not
have stated.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from site_text_sanitize import _SENTENCE_SPLIT_RE, _attributed_spans

# Insight-card and Deep Dive narrative fields in our own voice.
ANALYSIS_TEXT_FIELDS = ("summary", "investment_thesis")
ANALYSIS_LIST_FIELDS = ("key_takeaways",)
DEEP_DIVE_TEXT_FIELDS = ("overview", "whats_new", "investment_thesis")
SKIP_KEYS = frozenset({
    "falsification_tracks", "watch_items", "episode_evidence", "source_quotes",
    "notable_quotes", "speaker_quote", "quote", "quotes", "high_value_quotes",
    "speaker", "cue", "intro_cue", "title", "episode_title", "insight_title",
})

# Generic person-count wording that is not a claimed figure.
_PERSON_COUNT_RE = re.compile(
    r"\b(?:one|two|three)\s+(?:co-)?hosts?\b|\bone\s+guest\b|\bone\s+of\b|\bthe\s+one\b",
    re.I,
)
# Catalog / form / product tokens: do not treat their digits as figures.
_IDENTIFIER_RE = re.compile(
    r"(?i)\b(?:10-[kqa]|8-k|6-k|20-f|13[fdg]|13-[fdg]|s-[13])\b"
    r"|\bQ[1-4]\b"
    r"|\b(?:GPT|Claude|Gemini|Grok|Llama|Opus|Sonnet)-?\s?\d+(?:\.\d+)?\b"
    r"|\b(?:GB|H|B|A|L|RTX|GTX|RX)\d{2,4}[A-Z]{0,3}\b"
    r"|\b(?:S&P|S\s+and\s+P)\s*500\b|\bNasdaq(?:-|\s*)?100\b|\bRussell\s*2000\b"
    r"|\b(?:iPhone|iOS|Android)\s+\d+\b"
    r"|\bep(?:isode)?\s+\d+\b|\b#\d+\b"
    r"|\b\d{1,2}:\d{2}(?::\d{2})?\b"
    r"|https?://\S+"
)
_SCALE_WORDS = {
    "hundred": Decimal(100),
    "hundreds": Decimal(100),
    "thousand": Decimal(1000),
    "thousands": Decimal(1000),
    "million": Decimal(10) ** 6,
    "millions": Decimal(10) ** 6,
    "billion": Decimal(10) ** 9,
    "billions": Decimal(10) ** 9,
    "trillion": Decimal(10) ** 12,
    "trillions": Decimal(10) ** 12,
}
_COMPACT_SCALE = {"k": Decimal(1000), "m": Decimal(10) ** 6, "b": Decimal(10) ** 9, "t": Decimal(10) ** 12}
_ONES = {
    "zero": 0, "oh": 0,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}
_TENS = {
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
}
_WORD_RE = re.compile(
    r"\b(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|"
    r"hundred|thousand|million|billion|trillion)s?\b",
    re.I,
)
# 1-3, 1–3, 1 to 3, 1- to 3-year, 2-3 years
_RANGE_RE = re.compile(
    r"(?P<a>\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\d+(?:\.\d+)?)\s*"
    r"(?:[-–—]\s*to|to|[-–—]|or)\s*"
    r"(?P<b>\$?\d{1,3}(?:,\d{3})+(?:\.\d+)?|\$?\d+(?:\.\d+)?)",
    re.I,
)
# $1.4T, 13%, 1,000, 2.5 million, 100B
_DIGIT_RE = re.compile(
    r"(?P<cur>\$)?\s*(?P<num>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?P<comp>[kKmMbBtT])?(?P<pct>\s*%|\s*percent(?:age)?s?|\s*pct|\s*bps|\s*basis\s+points)?"
    r"(?:\s+(?P<scale>hundreds?|thousands?|millions?|billions?|trillions?))?",
    re.I,
)
_CLAUSE_SPLIT_RE = re.compile(r"\s*;\s*")
# "a million", "a billion-dollar market"
_A_SCALE_RE = re.compile(
    r"\ban?\s+(?P<scale>hundred|thousand|million|billion|trillion)s?(?:[-\s]dollar)?\b",
    re.I,
)
_FRAC = {"half": Decimal("0.5"), "quarter": Decimal("0.25"), "third": Decimal(1) / 3}
_WORD_OR_DIGIT = (
    r"(?:(?:zero|oh|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    r"twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety)"
    r"(?:[\s-]+(?:one|two|three|four|five|six|seven|eight|nine))?|"
    r"\d+(?:\.\d+)?)"
)
# "five and a quarter", "one and a half billion", "5 and a half"
_AND_A_FRAC_RE = re.compile(
    r"(?P<n>" + _WORD_OR_DIGIT + r")\s+and\s+a\s+(?P<frac>half|quarter|third)"
    r"(?:\s+(?P<scale>hundred|thousand|million|billion|trillion)s?)?",
    re.I,
)
# 1990s / 90s / '90s; two-digit years after a year cue ("late 99", "in '01")
_DECADE_RE = re.compile(
    r"\b(?:(?P<cent>19|20)(?P<dec>\d0)s|(?P<apos>')?(?P<short>\d0)s)\b",
    re.I,
)
# Only unambiguous year cues. "in 16 days", "by 51%", "of 70,000" are not years.
_YY_YEAR_RE = re.compile(
    r"(?:\b(?:late|early|mid)(?:-|\s+)'?|(?<=\s)')(?P<yy>\d{2})\b",
    re.I,
)
_PAREN_RE = re.compile(r"\([^()]{1,200}\)")
_EMDASH_ASIDE_RE = re.compile(r"\s+[—–-]\s+[^—–.]{1,200}(?=\s+[—–-]\s+|[.]|$)")


@dataclass
class NumberDrop:
    field: str
    removed: str
    numbers: List[str] = field(default_factory=list)

    def warn_line(self) -> str:
        nums = ", ".join(self.numbers) if self.numbers else "number"
        snippet = re.sub(r"\s+", " ", self.removed).strip()
        if len(snippet) > 160:
            snippet = snippet[:157] + "..."
        return f"WARN number check: dropped from {self.field} (unsupported {nums}): {snippet!r}"


def _to_dec(text: str) -> Optional[Decimal]:
    try:
        return Decimal(text.replace(",", "").replace("$", "").strip())
    except (InvalidOperation, AttributeError):
        return None


def _norm_set(values: Iterable[Decimal]) -> Set[Decimal]:
    out: Set[Decimal] = set()
    for v in values:
        if v is None:
            continue
        try:
            out.add(+v)
        except (InvalidOperation, ValueError):
            continue
    return out




def _mask_non_figures(text: str) -> str:
    text = _IDENTIFIER_RE.sub(" ", text or "")
    text = _PERSON_COUNT_RE.sub(" ", text)
    return text


def _add_scaled(values: List[Decimal], raw: Decimal, scale: Optional[Decimal]) -> None:
    # A scaled figure is the scaled value only, so "two million" does not
    # also unlock a bare "2 years" in the summary.
    if scale is not None and scale != 1:
        values.append(raw * scale)
    else:
        values.append(raw)



def _word_or_digit_value(tok: str) -> Optional[Decimal]:
    tok = (tok or "").strip().lower().replace("-", " ")
    d = _to_dec(tok)
    if d is not None:
        return d
    parts = [p for p in tok.split() if p]
    if len(parts) == 2 and parts[0] in _TENS and parts[1] in _ONES:
        return Decimal(_TENS[parts[0]] + _ONES[parts[1]])
    if len(parts) == 1 and parts[0] in _ONES:
        return Decimal(_ONES[parts[0]])
    if len(parts) == 1 and parts[0] in _TENS:
        return Decimal(_TENS[parts[0]])
    return None


def _expand_two_digit_year(yy: int) -> Decimal:
    # 00-29 -> 2000s; 30-99 -> 1900s. "late 99" is 1999, "in 01" is 2001.
    return Decimal(2000 + yy if yy <= 29 else 1900 + yy)


def _collect_spoken_figures(masked: str, values: List[Decimal], consumed: List[Tuple[int, int]]) -> None:
    """a million / five and a quarter / 90s / late 99, recorded so digit passes skip them."""
    def take(span, *vals):
        consumed.append(span)
        for v in vals:
            if v is not None:
                values.append(v)

    for m in _AND_A_FRAC_RE.finditer(masked):
        base = _word_or_digit_value(m.group("n"))
        frac = _FRAC.get((m.group("frac") or "").lower())
        if base is None or frac is None:
            continue
        raw = base + frac
        scale_w = (m.group("scale") or "").lower()
        scale = _SCALE_WORDS.get(scale_w) or _SCALE_WORDS.get(scale_w.rstrip("s"))
        take(m.span(), raw * scale if scale else raw)

    for m in _A_SCALE_RE.finditer(masked):
        if any(m.start() < y and m.end() > x for x, y in consumed):
            continue
        scale_w = (m.group("scale") or "").lower()
        scale = _SCALE_WORDS.get(scale_w) or _SCALE_WORDS.get(scale_w.rstrip("s"))
        if scale:
            take(m.span(), scale)  # "a million" == 1 * million

    for m in _DECADE_RE.finditer(masked):
        if m.group("cent"):
            year = int(m.group("cent")) * 100 + int(m.group("dec"))
        else:
            short = int(m.group("short"))
            year = 2000 + short if short <= 20 else 1900 + short
        take(m.span(), Decimal(year))

    for m in _YY_YEAR_RE.finditer(masked):
        if any(m.start() < y and m.end() > x for x, y in consumed):
            continue
        take(m.span(), _expand_two_digit_year(int(m.group("yy"))))


def extract_numbers(text: str) -> Set[Decimal]:
    """Canonical numeric values mentioned in text (our-voice or transcript)."""
    if not text:
        return set()
    masked = _mask_non_figures(text)
    values: List[Decimal] = []
    consumed: List[Tuple[int, int]] = []
    _collect_spoken_figures(masked, values, consumed)

    def taken(a: int, b: int) -> bool:
        return any(a < y and b > x for x, y in consumed)

    for m in _RANGE_RE.finditer(masked):
        a = _to_dec(m.group("a"))
        b = _to_dec(m.group("b"))
        if a is None or b is None:
            continue
        consumed.append(m.span())
        # Scale after the range: "1-3 years" has no scale; "1-3 million" does.
        tail = masked[m.end():m.end() + 16]
        sm = re.match(r"\s*-?\s*(hundreds?|thousands?|millions?|billions?|trillions?|[kKmMbBtT])\b", tail, re.I)
        scale = None
        if sm:
            tok = sm.group(1).lower().rstrip("s")
            scale = _SCALE_WORDS.get(tok) or _SCALE_WORDS.get(sm.group(1).lower()) or _COMPACT_SCALE.get(tok[:1])
        _add_scaled(values, a, scale)
        _add_scaled(values, b, scale)

    for m in _DIGIT_RE.finditer(masked):
        if taken(m.start(), m.end()):
            continue
        raw = _to_dec((m.group("num") or "") + (m.group("dec") or ""))
        if raw is None:
            continue
        scale = None
        comp = (m.group("comp") or "")
        if comp:
            scale = _COMPACT_SCALE.get(comp.lower())
        word = (m.group("scale") or "").lower()
        if word:
            scale = _SCALE_WORDS.get(word) or _SCALE_WORDS.get(word.rstrip("s"))
        _add_scaled(values, raw, scale)

    # Number words, including "two or three" / "twenty-five" / "one hundred fifty million".
    lower = masked.lower()
    word_iter = list(_WORD_RE.finditer(lower))
    i = 0
    while i < len(word_iter):
        chunk = [word_iter[i]]
        j = i + 1
        while j < len(word_iter):
            gap = lower[word_iter[j - 1].end():word_iter[j].start()]
            if re.fullmatch(r"[\s\-–—]+(?:(?:and|or|to)\s+)?", gap):
                chunk.append(word_iter[j])
                j += 1
                continue
            break
        words = [m.group().lower().rstrip("s") if m.group().lower() not in ("hundreds",) else "hundred"
                 for m in chunk]
        # Lone scales with no coefficient ("billion", "billions") are vague; skip.
        if len(words) == 1 and words[0] in {"hundred", "thousand", "million", "billion", "trillion"}:
            i = j
            continue
        parsed = _parse_word_run(words)
        values.extend(parsed)
        i = j

    return _norm_set(values)


def _parse_word_run(words: Sequence[str]) -> List[Decimal]:
    """Parse a run of number words into one or more values (splits on or/to)."""
    # Reconstruct using original connectors from the joined list: words is already split.
    # "two or three" arrives as ["two", "three"] because connectors were skipped.
    # We parse greedily into groups at implicit "or/to" by trying a single value first,
    # then falling back to each simple word if the run is a short range of small ones.
    if not words:
        return []
    # Short ranges of simple ones/tens: two, three / one, three / twenty, thirty.
    simple = []
    all_simple = True
    for w in words:
        if w in _ONES:
            simple.append(Decimal(_ONES[w]))
        elif w in _TENS:
            simple.append(Decimal(_TENS[w]))
        else:
            all_simple = False
            break
    if all_simple and len(simple) >= 2 and all(v < 100 for v in simple):
        # "twenty five" is 25, not 20 and 5. Detect compound tens+ones.
        if len(words) == 2 and words[0] in _TENS and words[1] in _ONES and _ONES[words[1]] < 10:
            return [Decimal(_TENS[words[0]] + _ONES[words[1]])]
        # "two or three" / "one to three": each bound is a figure.
        if len(simple) <= 3:
            return simple
    return [_parse_word_value(words)] if _parse_word_value(words) is not None else simple


def _parse_word_value(words: Sequence[str]) -> Optional[Decimal]:
    total = Decimal(0)
    current = Decimal(0)
    saw = False
    for w in words:
        if w in _ONES:
            current += _ONES[w]
            saw = True
        elif w in _TENS:
            current += _TENS[w]
            saw = True
        elif w == "hundred":
            current = (current or Decimal(1)) * 100
            saw = True
        elif w in _SCALE_WORDS and w not in {"hundred", "hundreds"}:
            scale = _SCALE_WORDS[w]
            total += (current or Decimal(1)) * scale
            current = Decimal(0)
            saw = True
        else:
            return None
    if not saw:
        return None
    return total + current


def transcript_number_set(transcript: str) -> Set[Decimal]:
    return extract_numbers(transcript or "")


def _quote_present(quote: str, transcript: str) -> bool:
    if not quote or not transcript:
        return False
    try:
        from two_pass_analyzer import quote_in_transcript
        return quote_in_transcript(quote, transcript, 0.85)
    except Exception:
        norm = re.sub(r"\s+", " ", quote).strip().lower()
        return bool(norm) and norm in re.sub(r"\s+", " ", transcript).lower()


def _own_voice_text(text: str, transcript: str) -> Tuple[str, List[Tuple[int, int, str]]]:
    """Mask attributed quotes; return (masked_text, failed_quotes).

    failed_quotes: attributed quotes that are not present in the transcript as-is.
    """
    failed: List[Tuple[int, int, str]] = []
    if not text:
        return text, failed
    chars = list(text)
    for a, b in _attributed_spans(text, quote_field=False):
        inner = text[a:b]
        bare = inner.strip().strip("\"'“”‘’")
        if _quote_present(bare, transcript):
            chars[a:b] = " " * (b - a)
        else:
            failed.append((a, b, inner))
            chars[a:b] = " " * (b - a)
    return "".join(chars), failed


def unsupported_in(text: str, allowed: Set[Decimal], transcript: str) -> List[str]:
    """Return display strings for our-voice numbers not in the transcript set."""
    masked, failed_quotes = _own_voice_text(text, transcript)
    if failed_quotes:
        # Invented "quotes" are not as-is in the transcript; treat as a quote failure,
        # reported separately by the caller when dropping the span/sentence.
        pass
    found = extract_numbers(masked)
    bad = sorted((v for v in found if v not in allowed), key=lambda x: (abs(x), x))
    return [_display_number(v) for v in bad]


def _display_number(v: Decimal) -> str:
    v = +v
    if v == v.to_integral_value():
        ival = int(v)
        if ival >= 10 ** 12 and ival % 10 ** 12 == 0:
            return f"{ival // 10 ** 12}T"
        if ival >= 10 ** 9 and ival % 10 ** 9 == 0:
            return f"{ival // 10 ** 9}B"
        if ival >= 10 ** 6 and ival % 10 ** 6 == 0:
            return f"{ival // 10 ** 6}M"
        return f"{ival:,}"
    s = format(v, "f").rstrip("0").rstrip(".")
    return s


_SENTENCE_END_RE = re.compile(
    r'([.!?]+["\u201d\u2019]?)\s+(?=[A-Z0-9"\'\u201c\u2018(])'
)

def _split_sentences(text: str) -> List[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Keep a closing quote with the sentence it belongs to ("...years." Next).
    marked = _SENTENCE_END_RE.sub(r"\1\n", text)
    parts = [p.strip() for p in marked.split("\n") if p.strip()]
    return parts


def _unsupported(text: str, allowed: Set[Decimal], transcript: str) -> List[str]:
    return unsupported_in(text, allowed, transcript)


def _strip_failed_quotes(text: str, failed: List[Tuple[int, int, str]]) -> str:
    if not failed:
        return text
    chars = list(text)
    for a, b, _ in failed:
        chars[a:b] = " " * (b - a)
    cleaned = re.sub(r"\s+", " ", "".join(chars))
    cleaned = re.sub(r"\s+([,;:])", r"\1", cleaned)
    return cleaned.strip()


def _try_drop_clause(sentence: str, allowed: Set[Decimal], transcript: str) -> Optional[str]:
    """If a parenthetical, em-dash aside, or semicolon clause holds the bad number, drop just that."""
    # Parentheticals
    for m in list(_PAREN_RE.finditer(sentence)):
        if _unsupported(m.group(), allowed, transcript) and not _unsupported(
            sentence[:m.start()] + " " + sentence[m.end():], allowed, transcript
        ):
            cut = (sentence[:m.start()] + sentence[m.end():]).strip()
            cut = re.sub(r"\s{2,}", " ", cut)
            return cut
    # Semicolon clauses
    parts = _CLAUSE_SPLIT_RE.split(sentence)
    if len(parts) >= 2:
        kept = [p.strip() for p in parts if p.strip() and not _unsupported(p, allowed, transcript)]
        if kept and len(kept) < len([p for p in parts if p.strip()]):
            joined = "; ".join(kept)
            if not joined.endswith((".", "!", "?")) and sentence.endswith((".", "!", "?")):
                joined += sentence[-1]
            if not _unsupported(joined, allowed, transcript):
                return joined
    return None


def strip_unsupported_numbers(
    text: str,
    transcript: str,
    *,
    allowed: Optional[Set[Decimal]] = None,
    field: str = "text",
) -> Tuple[str, List[NumberDrop]]:
    """Return (cleaned_text, drops). Preserves blank-line paragraph breaks."""
    if not isinstance(text, str):
        return "" if text is None else text, []
    if not (transcript or "").strip():
        return text, []
    if not text.strip():
        return text, []
    allowed = allowed if allowed is not None else transcript_number_set(transcript)
    drops: List[NumberDrop] = []
    paragraphs = re.split(r"\n\s*\n", text)
    kept_paras: List[str] = []
    for para in paragraphs:
        raw_sentences = _split_sentences(para)
        if not raw_sentences:
            # No terminal punctuation: treat the whole paragraph as one unit.
            raw_sentences = [para.strip()] if para.strip() else []
        kept_sents: List[str] = []
        for sent in raw_sentences:
            own, failed_quotes = _own_voice_text(sent, transcript)
            bad = _unsupported(sent, allowed, transcript)
            if failed_quotes and not bad:
                # Quote is not as-is in the transcript; drop the quote span, keep the rest
                # if it still reads as a sentence without new unsupported numbers.
                trimmed = _strip_failed_quotes(sent, failed_quotes)
                if trimmed and not _unsupported(trimmed, allowed, transcript):
                    drops.append(NumberDrop(field=field, removed=failed_quotes[0][2], numbers=["quote not in transcript"]))
                    kept_sents.append(trimmed)
                    continue
                drops.append(NumberDrop(field=field, removed=sent, numbers=["quote not in transcript"]))
                continue
            if not bad:
                kept_sents.append(sent)
                continue
            clause = _try_drop_clause(sent, allowed, transcript)
            if clause is not None and clause.strip():
                drops.append(NumberDrop(field=field, removed=sent, numbers=bad))
                kept_sents.append(clause)
                continue
            drops.append(NumberDrop(field=field, removed=sent, numbers=bad))
        if kept_sents:
            kept_paras.append(" ".join(kept_sents).strip())
    cleaned = "\n\n".join(kept_paras).strip()
    # Preserve a trailing newline only if the original was a single trailing newline-less string.
    return cleaned, drops


def apply_number_check(
    obj: Dict[str, Any],
    transcript: Optional[str],
    *,
    episode_ref: str = "",
    log_path=None,
    kind: str = "analysis",
) -> List[NumberDrop]:
    """Edit analysis / Deep Dive dict in place. Skip (WARN, do not block) if no transcript."""
    if not obj:
        return []
    if not (transcript or "").strip():
        print(f"    WARN number check: skipped (no transcript){f' for {episode_ref}' if episode_ref else ''}", flush=True)
        return []
    allowed = transcript_number_set(transcript)
    drops: List[NumberDrop] = []

    def walk(node: Any, key: str = "", path: str = "") -> Any:
        if key in SKIP_KEYS:
            return node
        if isinstance(node, str):
            if key in ANALYSIS_TEXT_FIELDS or key in DEEP_DIVE_TEXT_FIELDS or key in {"context", "definition", "investment_angle", "rationale", "positioning", "risk", "prose"}:
                cleaned, d = strip_unsupported_numbers(node, transcript, allowed=allowed, field=path or key)
                drops.extend(d)
                return cleaned
            return node
        if isinstance(node, list):
            if key in ANALYSIS_LIST_FIELDS or key in {"catalysts", "contrarian_signals"}:
                out = []
                for i, item in enumerate(node):
                    if isinstance(item, str):
                        cleaned, d = strip_unsupported_numbers(item, transcript, allowed=allowed, field=f"{path or key}[{i}]")
                        drops.extend(d)
                        if cleaned.strip():
                            out.append(cleaned)
                    else:
                        out.append(walk(item, key, f"{path}[{i}]"))
                return out
            return [walk(x, key, f"{path}[{i}]") for i, x in enumerate(node)]
        if isinstance(node, dict):
            # investment_implication: {prose, tickers, watch_items}
            out = {}
            for k, v in node.items():
                if k in SKIP_KEYS:
                    out[k] = v
                    continue
                out[k] = walk(v, k, f"{path}.{k}" if path else k)
            return out
        return node

    # Top-level in-place update via walk of a shallow copy of keys we care about.
    updated = walk(obj, "", "")
    if isinstance(updated, dict):
        obj.clear()
        obj.update(updated)

    _log_drops(drops, episode_ref=episode_ref, log_path=log_path)
    return drops


def _log_drops(drops: List[NumberDrop], *, episode_ref: str = "", log_path=None) -> None:
    if not drops:
        return
    for d in drops:
        print(f"    {d.warn_line()}", flush=True)
    try:
        if log_path is None:
            from workspace_paths import STATE_DIR
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            log_path = STATE_DIR / "number_check_drops.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            for d in drops:
                f.write(json.dumps({
                    "ts": datetime.now().isoformat(timespec="seconds"),
                    "episode": episode_ref,
                    "field": d.field,
                    "removed": d.removed,
                    "numbers": d.numbers,
                }) + "\n")
    except Exception as exc:
        print(f"    WARN number check: could not write drop log: {exc}", flush=True)


def site_text_prompts() -> Dict[str, str]:
    """Every prompt that writes site text (summaries, takeaways, Deep Dives, implications)."""
    from speaker_attribution import OUR_VOICE_WORDING_RULES
    from two_pass_analyzer import SITE_CONTRACT_PROMPT, SYNTHESIS_PROMPT
    from generate_deepdives import EXTRACTION_DEEPDIVE_PROMPT, LEGACY_DEEPDIVE_HARD_RULES
    import inspect
    import analyze_transcript as at

    return {
        "OUR_VOICE_WORDING_RULES": OUR_VOICE_WORDING_RULES,
        "SITE_CONTRACT_PROMPT": SITE_CONTRACT_PROMPT,
        "SYNTHESIS_PROMPT": SYNTHESIS_PROMPT,
        "EXTRACTION_DEEPDIVE_PROMPT": EXTRACTION_DEEPDIVE_PROMPT,
        "LEGACY_DEEPDIVE_HARD_RULES": LEGACY_DEEPDIVE_HARD_RULES,
        "analyze_transcript": inspect.getsource(at.analyze_transcript_with_ai),
    }
