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
    ("Elena Berger", "Elena Burger", True),
    ("Laina Berger", "Elena Burger", True),
    ("Palmer Lucky", "Palmer Luckey", True),
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


# ---------------------------------------------------------------------------
# Style gate (Oct 2026). Jared's rule: nothing on the public site is called a
# "bet". The gate only FLAGS wording (it never rewrites text): curated swaps live
# in pipeline/summary_overrides.json (global_replacements / summaries rules) so
# Mac exports keep them. Exempt: title fields (podcast episode titles), cites,
# URLs/slugs and Alphabet's "Other Bets". Mode is WARN: export prints leftovers
# and continues; publish_guard BLOCKS on any hit.
#
# Quote scope (decisions.md 2026-11-09 ~11:15 PM CT): the rule covers OUR voice
# only (calls, views, leans, our copy). ATTRIBUTED guest quotes stay verbatim
# and pass. A quote counts as attributed when:
#   * structured: a quote field (quote/quotes/text) whose record names a
#     speaker (speaker/guest/attribution/speaker_name/author);
#   * a speaker line in a quote field (episode_evidence / notable_quotes /
#     quote): "Andy Constan: my bet today ...";
#   * inline, in any text: quote marks with a speaker cue right before
#     ('Alex Zhang: "..."', 'The host says "..."', 'according to Name, "..."')
#     or right after ('"..." -- Name', '"...," Name said').
# Unattributed quotes, scare quotes and our own "we say" quotes stay strict.
# ---------------------------------------------------------------------------

BANNED_WORDS_RE = re.compile(r"\b(?:bets?|betting|bettors?|wager(?:s|ed|ing)?)\b", re.IGNORECASE)
STYLE_GATE_SKIP_KEYS = frozenset({
    "title", "episode_title", "insight_title", "last_episode_title", "last_mentioned_episode_title",
    "last_proof_cite",
    "net_worth_source", "url", "source_url", "link", "slug",
    "speaker",
})
# Fields that hold guest quotes/evidence: speaker lines ("Name: words") pass there.
QUOTE_FIELD_KEYS = frozenset({"episode_evidence", "notable_quotes", "quote", "quotes"})
_QUOTE_TEXT_KEYS = ("quote", "quotes", "text")
SPEAKER_KEYS = ("speaker", "speaker_name", "guest", "attribution", "author")

_ALWAYS_PROTECTED_RE = re.compile(r"https?://\S+|\bOther Bets\b")
_QUOTED_RE = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d|(?<![A-Za-z])'[^']*'(?![A-Za-z])")
_CUE_VERBS = (r"says?|said|saying|mentions?|mentioned|notes?|noted|argues?|argued|explains?|explained|adds?|added|"
              r"tells?|told|asks?|asked|puts? it|claims?|claimed|states?|stated|writes?|wrote|recalls?|recalled|"
              r"warns?|warned|insists?|insisted|quips?|quipped|remarks?|remarked|observes?|observed|"
              r"emphasi[sz]es|emphasi[sz]ed|stresses|stressed|believes?|believed|predicts?|predicted|"
              r"describes?|described|calls? it|called it|framed it|summari[sz]ed|replies|replied|joked")
_NAME = r"[A-Z][\w.'\u2019-]*(?:\s+(?:[A-Z][\w.'\u2019-]*|de|van|von|da|del|bin|al))*"
_OWN_VOICE = r"(?:we|We|our|Our|us|Us|I|this site|the site|the dashboard)"
# Speaker cue immediately before the opening quote mark.
_CUE_BEFORE_RE = re.compile(
    r"(?:\b(?:" + _CUE_VERBS + r")\b(?:\s+(?:that|how|it|this))?|\b(?i:according to)\s+" + _NAME + r"|"
    r"\b(?:in\s+(?:his|her|their)\s+words)|(?:^|[\s(\[\u2014-])" + _NAME + r"(?:\s*\([^)]{0,60}\))?\s*)"
    r"\s*[:,\u2014-]?\s*$")
# Speaker cue immediately after the closing quote mark.
_CUE_AFTER_RE = re.compile(
    r"^\s*[,.;:!?]?\s*(?:(?:[\u2014\u2013]|--)\s*" + _NAME + r"|" + _NAME + r"\s+(?:" + _CUE_VERBS + r")\b|"
    r"(?:" + _CUE_VERBS + r")\s+" + _NAME + r")")
# Speaker line inside a quote field: "Andy Constan: ..." / "Jane Doe (CEO, X): ...".
_SPEAKER_LINE_RE = re.compile(r"(?m)^[ \t]*(?:[-*\u2022][ \t]*)?(" + _NAME + r")(?:[ \t]*\([^)\n]{0,60}\))?[ \t]*:[ \t]*(.+)$")
_NOT_SPEAKERS = frozenset({
    "our view", "view", "lean", "our lean", "call", "our call", "takeaway", "bottom line", "note", "summary",
    "why", "what", "thesis", "risk", "risks", "catalyst", "catalysts", "evidence", "context", "update", "watch",
    "signal", "verdict", "position", "positioning", "tl;dr", "tldr", "key", "we", "our", "us", "i",
})
STYLE_GATE_MISSES: list = []


def _own_voice_before(before: str) -> bool:
    tail = before[-60:]
    return bool(re.search(r"\b" + _OWN_VOICE + r"\s+(?:\w+\s+){0,2}(?:" + _CUE_VERBS + r")\b(?:\s+(?:that|how|it|this))?\s*[:,\u2014-]?\s*$", tail))


def _is_speaker(name: str) -> bool:
    n = name.strip().lower()
    return bool(n) and n not in _NOT_SPEAKERS and not n.startswith(("our ", "we ", "my "))


def _attributed_spans(text: str, quote_field: bool = False) -> list[tuple[int, int]]:
    """Character spans of attributed guest quotes in text (exempt from the gate)."""
    spans = []
    for m in _QUOTED_RE.finditer(text):
        before, after = text[max(0, m.start() - 120):m.start()], text[m.end():m.end() + 80]
        cue = _CUE_BEFORE_RE.search(before)
        if cue and not _own_voice_before(before):
            # A bare name before the quote must be a real speaker, not "Our view".
            word = re.search(r"(" + _NAME + r")(?:\s*\([^)]{0,60}\))?\s*[:\u2014]\s*$", before)
            verb = re.search(r"\b(?:" + _CUE_VERBS + r"|(?i:according to)|in (?:his|her|their) words)\b", cue.group())
            if verb or (word and _is_speaker(word.group(1))):
                spans.append(m.span())
                continue
        if _CUE_AFTER_RE.search(after):
            spans.append(m.span())
    if quote_field:
        for m in _SPEAKER_LINE_RE.finditer(text):
            if _is_speaker(m.group(1)):
                spans.append(m.span(2))
    return spans


def style_gate_hits(text: str, quote_field: bool = False) -> list:
    """Return banned-word snippets in text outside attributed guest quotes, URLs and 'Other Bets'.

    quote_field=True (episode_evidence / notable_quotes / quote) also lets
    speaker lines ("Name: words") through. Unattributed quotes are checked.
    """
    if not isinstance(text, str) or not BANNED_WORDS_RE.search(text):
        return []
    chars = list(text)
    for a, b in _attributed_spans(text, quote_field):
        chars[a:b] = " " * (b - a)
    stripped = _ALWAYS_PROTECTED_RE.sub(" ", "".join(chars))
    return [stripped[max(0, m.start() - 40): m.end() + 40].strip() for m in BANNED_WORDS_RE.finditer(stripped)]


def _has_speaker(rec: dict) -> bool:
    return any(isinstance(rec.get(k), str) and _is_speaker(rec[k]) for k in SPEAKER_KEYS)


def find_style_gate_hits(obj: Any, _key: str = "", _path: str = "", _quote_field: bool = False) -> list:
    """Recursively collect (path, snippet) style-gate hits, skipping exempt fields.

    A quote text field passes when its record names a speaker; quote fields
    without one are checked like any other text (speaker lines still pass).
    """
    out = []
    if isinstance(obj, str):
        if _key not in STYLE_GATE_SKIP_KEYS:
            out.extend((_path, s) for s in style_gate_hits(obj, quote_field=_quote_field))
    elif isinstance(obj, dict):
        attributed = _has_speaker(obj)
        for k, v in obj.items():
            if k in STYLE_GATE_SKIP_KEYS:
                continue
            if attributed and k in _QUOTE_TEXT_KEYS:
                continue  # attributed guest quote: verbatim, never flagged
            qf = _quote_field or k in QUOTE_FIELD_KEYS
            out.extend(find_style_gate_hits(v, k, f"{_path}.{k}", qf))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out.extend(find_style_gate_hits(v, _key, f"{_path}[{i}]", _quote_field))
    return out


def apply_style_gate(obj: Any) -> Any:
    """Warn-only gate: record hits for report_style_gate_misses(); returns obj unchanged."""
    STYLE_GATE_MISSES.extend(find_style_gate_hits(obj))
    return obj


def report_style_gate_misses() -> int:
    """Print leftover 'bet' wording as a warning (never raises). Returns the count."""
    n = len(STYLE_GATE_MISSES)
    if n:
        print(f"  \u26a0 style gate (warn): {n} 'bet' wording hit(s) on public text; "
              "add a swap to pipeline/summary_overrides.json global_replacements:")
        for path, s in sorted(set(STYLE_GATE_MISSES))[:20]:
            print(f"     - {path}: {s}")
    STYLE_GATE_MISSES.clear()
    return n
