#!/usr/bin/env python3
"""Suggest sourced Deep Dive quote-speaker overrides without modifying the DB."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

import requests
from bs4 import BeautifulSoup

PIPELINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PIPELINE_DIR))

from generate_deepdives import load_deepdive_speaker_overrides  # noqa: E402
from workspace_paths import DB_PATH  # noqa: E402


SPEAKER_MARKER_RE = re.compile(
    r"(?<!\w)([A-ZÀ-ɏ][A-Za-zÀ-ɏ.'’-]*(?:\s+[A-ZÀ-ɏ][A-Za-zÀ-ɏ.'’-]*){0,4})\s*:\s*"
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def extract_official_turns(page_text: str) -> List[Tuple[str, str]]:
    """Extract ``Speaker: words`` turns even when HTML collapses them onto one line."""
    text = re.sub(r"\s+", " ", page_text or "").strip()
    markers = list(SPEAKER_MARKER_RE.finditer(text))
    turns: List[Tuple[str, str]] = []
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
        turn_text = text[marker.end() : end].strip()
        if turn_text:
            turns.append((marker.group(1), turn_text))
    return turns


def _similarity(quote: str, turn: str) -> float:
    quote_words = _norm(quote).split()
    turn_words = _norm(turn).split()
    if not quote_words or not turn_words:
        return 0.0
    quote_norm = " ".join(quote_words)
    turn_norm = " ".join(turn_words)
    if quote_norm in turn_norm or turn_norm in quote_norm:
        return 1.0
    best = SequenceMatcher(None, quote_norm, turn_norm).ratio()
    radius = max(2, len(quote_words) // 5)
    for size in range(max(1, len(quote_words) - radius), len(quote_words) + radius + 1):
        for start in range(0, max(1, len(turn_words) - size + 1)):
            window = " ".join(turn_words[start : start + size])
            best = max(best, SequenceMatcher(None, quote_norm, window).ratio())
    return best


def _canonical_speaker(label: str, official_names: Sequence[str]) -> str:
    exact = [name for name in official_names if _norm(name) == _norm(label)]
    if exact:
        return exact[0]
    first = _norm(label).split()
    if len(first) == 1:
        matches = [name for name in official_names if _norm(name).split()[:1] == first]
        if len(matches) == 1:
            return matches[0]
    return label.strip()


def _extraction_quotes(extraction: Dict[str, Any]) -> Iterable[str]:
    for quote_obj in extraction.get("high_value_quotes") or []:
        if isinstance(quote_obj, dict) and quote_obj.get("quote"):
            yield str(quote_obj["quote"]).strip()
    for asset in extraction.get("companies_and_assets") or []:
        if not isinstance(asset, dict):
            continue
        for quote_obj in asset.get("key_quotes") or []:
            if isinstance(quote_obj, dict) and quote_obj.get("quote"):
                yield str(quote_obj["quote"]).strip()


def suggest_quote_speakers(
    extraction: Dict[str, Any],
    official_page_text: str,
    official_names: Sequence[str],
    *,
    threshold: float = 0.84,
) -> List[Dict[str, str]]:
    """Return paste-ready mappings only when an official transcript turn matches."""
    turns = []
    for label, turn_text in extract_official_turns(official_page_text):
        canonical = _canonical_speaker(label, official_names)
        if canonical in official_names:
            turns.append((canonical, turn_text))
    suggestions: List[Dict[str, str]] = []
    seen = set()
    for quote in _extraction_quotes(extraction):
        if quote in seen:
            continue
        seen.add(quote)
        scored = [
            (_similarity(quote, turn_text), speaker)
            for speaker, turn_text in turns
        ]
        if not scored:
            continue
        score, speaker = max(scored, key=lambda item: item[0])
        if score >= threshold:
            suggestions.append({"quote": quote, "speaker": speaker})
    return suggestions


def fetch_official_page_text(url: str) -> str:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser").get_text("\n")


def load_extraction(insight_id: int, db_path: Path = DB_PATH) -> Dict[str, Any]:
    uri = f"file:{db_path.resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        row = conn.execute(
            """
            SELECT pe.extraction_json
            FROM latest_insights li
            JOIN podcast_episodes pe ON pe.id = li.podcast_episode_id
            WHERE li.id = ?
            """,
            (insight_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        raise ValueError(f"insight {insight_id} has no extraction_json")
    extraction = json.loads(row[0])
    if not isinstance(extraction, dict):
        raise ValueError(f"insight {insight_id} extraction_json is not an object")
    return extraction


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fuzzy-match extraction quotes to an official episode transcript"
    )
    parser.add_argument("insight_id", type=int)
    parser.add_argument("url", help="Official show-note, episode, or transcript URL")
    args = parser.parse_args(argv)

    overrides = load_deepdive_speaker_overrides()
    entry = overrides.get(str(args.insight_id))
    if not entry:
        parser.error(f"no speaker override entry for insight {args.insight_id}")
    official_names = [entry["host"], *entry["guests"]]
    suggestions = suggest_quote_speakers(
        load_extraction(args.insight_id),
        fetch_official_page_text(args.url),
        official_names,
    )
    print(json.dumps(suggestions, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
