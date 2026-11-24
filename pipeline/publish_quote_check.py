#!/usr/bin/env python3
"""Flag-only transcript checks for main-page podcast summary cards."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from summary_number_check import _display_number, extract_numbers, transcript_number_set
from two_pass_analyzer import COMPANY_TO_TICKER, quote_match_score
from workspace_paths import PIPELINE_DIR, STATE_DIR, TRANSCRIPT_DIR

MATCH_THRESHOLD = 0.85
DEFAULT_LOG_PATH = STATE_DIR / "quote_check.jsonl"

SUMMARY_FIELDS = frozenset({
    "summary",
    "key_takeaway",
    "key_takeaways",
    "key_points",
    "investment_thesis",
    "notable_quotes",
    "pundit_quotes",
    "major_claims",
    "predictions",
    "risks",
    "contrarian_ideas",
})
KEY_POINT_FIELDS = frozenset({"key_takeaway", "key_takeaways", "key_points"})
QUOTE_VALUE_KEYS = frozenset({"quote", "speaker_quote"})
_QUOTED_RE = re.compile(r'["\u201c]([^"\u201d]{2,})["\u201d]')
_NUMBER_RE = re.compile(
    r"(?<![\w])\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?"
    r"(?:\s*(?:%|percent|pct|bps|basis points|[KMBT]\b)|\s+"
    r"(?:hundred|thousand|million|billion|trillion)s?)?",
    re.IGNORECASE,
)
_CAPITALIZED_RE = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9&.'-]*)(?:\s+(?:[A-Z][A-Za-z0-9&.'-]*)){0,4}\b"
)
_NAME_STOP = {
    "A", "An", "And", "As", "At", "By", "For", "From", "He", "Her", "His",
    "I", "If", "In", "It", "Its", "Key", "Our", "She", "That", "The", "Their",
    "They", "This", "We", "What", "When", "Where", "Who", "Why", "You",
}
_GENERIC_CAPITALIZED = {
    "Analysis", "Episode", "Growth", "Industry", "Investors", "Market", "Revenue",
    "Risk", "Summary", "Technology",
}
_KNOWN_COMPANIES = frozenset(COMPANY_TO_TICKER)
_KNOWN_TICKERS = frozenset(COMPANY_TO_TICKER.values())
_COMPANY_SUFFIXES = frozenset({
    "company", "corp", "corporation", "inc", "llc", "ltd", "labs", "technologies",
})
_ATTRIBUTION_VERBS_RE = re.compile(
    r"^\s+(?:said|says|argued|argues|claimed|claims|expects?|predicted|predicts|"
    r"believes?|disagrees?|warned|warns|estimated|estimates|reported|reports)\b",
    re.IGNORECASE,
)


def _episode_id(card: dict[str, Any]) -> Any:
    return card.get("podcast_episode_id") or card.get("episode_id") or card.get("id")


def _podcast(card: dict[str, Any]) -> str:
    return str(card.get("podcast_name") or card.get("source_name") or card.get("podcast") or "")


def _walk_text(value: Any, path: str) -> Iterable[tuple[str, str, str]]:
    if isinstance(value, str):
        yield path, path.rsplit(".", 1)[-1].split("[", 1)[0], value
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _walk_text(item, f"{path}[{index}]")
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _walk_text(item, f"{path}.{key}")


def _summary_texts(card: dict[str, Any]) -> Iterable[tuple[str, str, str]]:
    for field in SUMMARY_FIELDS:
        if field in card:
            yield from _walk_text(card[field], field)


def _quoted_values(field: str, key: str, text: str) -> Iterable[str]:
    seen: set[str] = set()
    if key in QUOTE_VALUE_KEYS:
        bare = text.strip().strip('"“”').strip()
        if bare:
            seen.add(bare)
            yield bare
    for match in _QUOTED_RE.finditer(text):
        quote = match.group(1).strip()
        if quote and quote not in seen:
            seen.add(quote)
            yield quote


def _number_mentions(text: str) -> Iterable[tuple[str, set]]:
    seen_values: set = set()
    for match in _NUMBER_RE.finditer(text or ""):
        raw = match.group(0).strip()
        values = extract_numbers(raw)
        if values:
            seen_values.update(values)
            yield raw.lstrip("$"), values
    for value in extract_numbers(text or "") - seen_values:
        yield _display_number(value), {value}


def _name_mentions(text: str, card: dict[str, Any]) -> Iterable[tuple[str, bool]]:
    """Yield (name, is_company), using repo ticker aliases plus capitalized phrases."""
    candidates: dict[str, bool] = {}
    lower = text.lower()
    card_tickers = {
        str(t).upper()
        for key in ("key_tickers", "tickers_mentioned")
        for t in (card.get(key) or [])
        if isinstance(card.get(key), list)
    }
    for company, ticker in COMPANY_TO_TICKER.items():
        if (
            re.search(rf"\b{re.escape(company)}\b", lower)
            and (not card_tickers or ticker in card_tickers)
        ):
            candidates[company] = True
    for ticker in card_tickers | _KNOWN_TICKERS:
        if re.search(rf"\b{re.escape(ticker)}\b", text):
            candidates[ticker] = True
    for match in _CAPITALIZED_RE.finditer(text):
        phrase = match.group(0).strip(" .,;:()[]")
        words = phrase.split()
        if not phrase or phrase in _NAME_STOP or phrase in _GENERIC_CAPITALIZED:
            continue
        company = (
            phrase.lower() in _KNOWN_COMPANIES
            or phrase.upper() in _KNOWN_TICKERS
            or (words and words[-1].rstrip(".").lower() in _COMPANY_SUFFIXES)
        )
        before = text[:match.start()]
        attributed = bool(_ATTRIBUTION_VERBS_RE.match(text[match.end():]))
        introduced = bool(re.search(
            r"\b(?:with|by|from|to|at|of|according to)\s+$",
            before,
            re.IGNORECASE,
        ))
        # Title case is often ordinary prose ("Higher Rates"). Keep aliases,
        # company suffixes, attributed speakers, and explicitly introduced names.
        if company or attributed or introduced:
            candidates[phrase] = company
    yield from candidates.items()


def _name_in_transcript(name: str, is_company: bool, transcript: str) -> bool:
    haystack = transcript.casefold()
    if is_company:
        return name.casefold() in haystack
    parts = [part.strip(".,'()") for part in name.split() if part.strip(".,'()")]
    needle = (parts[-1] if parts else name).casefold()
    return bool(needle) and re.search(rf"\b{re.escape(needle)}\b", haystack) is not None


def _base_miss(
    card: dict[str, Any], field: str, kind: str, text: str,
    score: Optional[float], transcript_path: str,
) -> dict[str, Any]:
    return {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "episode_id": _episode_id(card),
        "podcast": _podcast(card),
        "field": field,
        "kind": kind,
        "text": text,
        "best_match_score": score,
        "transcript_path": transcript_path,
    }


def _append_misses(misses: list[dict[str, Any]], log_path: Path | str) -> None:
    if not misses:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for miss in misses:
            handle.write(json.dumps(miss, ensure_ascii=False) + "\n")


def check_episode_summary(
    card: dict[str, Any],
    transcript: Optional[str],
    *,
    transcript_path: str,
    log_path: Path | str = DEFAULT_LOG_PATH,
) -> list[dict[str, Any]]:
    """Check one card, append only misses, and never edit the card."""
    if not (transcript or "").strip():
        misses = [_base_miss(card, "", "no_transcript", "", None, transcript_path)]
        _append_misses(misses, log_path)
        return misses

    misses: list[dict[str, Any]] = []
    allowed_numbers = transcript_number_set(transcript)
    for field, key, text in _summary_texts(card):
        for quote in _quoted_values(field, key, text):
            score = quote_match_score(quote, transcript)
            if score < MATCH_THRESHOLD:
                misses.append(_base_miss(card, field, "quote", quote, round(score, 4), transcript_path))

        root = field.split(".", 1)[0].split("[", 1)[0]
        if root not in KEY_POINT_FIELDS:
            continue
        for raw, values in _number_mentions(text):
            if not values.issubset(allowed_numbers):
                misses.append(_base_miss(card, field, "number", raw, 0.0, transcript_path))
        for name, is_company in _name_mentions(text, card):
            if not _name_in_transcript(name, is_company, transcript):
                misses.append(_base_miss(card, field, "name", name, 0.0, transcript_path))

    _append_misses(misses, log_path)
    return misses


def _resolve_transcript(db: Any, episode_id: Any) -> tuple[str, str]:
    if episode_id is None:
        return "", ""
    with db._get_connection() as conn:
        row = conn.execute(
            "SELECT transcript_path FROM podcast_episodes WHERE id = ?",
            (episode_id,),
        ).fetchone()
    raw = str(row["transcript_path"] or "") if row else ""
    if not raw:
        return "", ""
    path = Path(raw).expanduser()
    candidates = [path] if path.is_absolute() else [path, PIPELINE_DIR / path, TRANSCRIPT_DIR / path.name]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="ignore"), str(candidate)
    return "", raw


def check_main_page_summaries(
    main_content: dict[str, Any],
    db: Any,
    *,
    log_path: Path | str = DEFAULT_LOG_PATH,
    transcript_resolver: Optional[Callable[[Any, Any], tuple[str, str]]] = None,
) -> list[dict[str, Any]]:
    """Check every main-page podcast insight and return all logged misses."""
    resolver = transcript_resolver or _resolve_transcript
    misses: list[dict[str, Any]] = []
    for card in main_content.get("insights", []) or []:
        if not isinstance(card, dict) or not _episode_id(card):
            continue
        transcript, path = resolver(db, _episode_id(card))
        misses.extend(check_episode_summary(card, transcript, transcript_path=path, log_path=log_path))
    return misses
