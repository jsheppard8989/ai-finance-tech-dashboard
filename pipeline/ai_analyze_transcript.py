#!/usr/bin/env python3
"""
AI Transcript Entity/Idea Analyzer (skeleton).

Goal:
- Take a single podcast episode transcript.
- (Later) call an AI/MCP tool to extract:
  - people (hosts/guests) with bios/known_for
  - main investment-relevant ideas
- Ingest into semantic layer tables via ingest_ai_analysis.ingest_ai_result.

For now, this is a stub that wires argument parsing and ingestion so the
plumbing can be exercised safely without real AI calls.
"""

import argparse
import json
from pathlib import Path

from ingest_ai_analysis import ingest_ai_result
from db_manager import get_db


def load_episode_meta(episode_id: int) -> dict:
    """Fetch minimal metadata for a podcast episode."""
    db = get_db()
    with db._get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, podcast_name, episode_title, episode_date, transcript_path
            FROM podcast_episodes
            WHERE id = ?
            """,
            (episode_id,),
        ).fetchone()
    if not row:
        raise SystemExit(f"No podcast_episodes row found for id={episode_id}")
    return dict(row)


def call_ai_stub(transcript_text: str, episode_meta: dict) -> dict:
    """
    Placeholder for the real AI/MCP call.

    Returns a minimal, hard-coded payload so we can exercise ingestion:
    - If transcript_text is non-empty, emit a single dummy idea.
    """
    if not transcript_text.strip():
        return {"people": [], "ideas": []}

    title = episode_meta.get("episode_title") or "Unknown Episode"
    podcast = episode_meta.get("podcast_name") or "Unknown Podcast"

    return {
        "people": [],
        "ideas": [
            {
                "speaker_name": None,
                "summary": f"High-level discussion in '{title}' from {podcast}.",
                "thesis": None,
                "tickers": [],
                "sentiment": "neutral",
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="AI-enhanced transcript analyzer (stub).")
    parser.add_argument("--episode-id", type=int, required=True, help="podcast_episodes.id")
    parser.add_argument(
        "--transcript-path",
        type=str,
        required=True,
        help="Path to transcript text file for this episode",
    )
    args = parser.parse_args()

    episode_meta = load_episode_meta(args.episode_id)
    tpath = Path(args.transcript_path).expanduser()
    if not tpath.exists():
        raise SystemExit(f"Transcript file not found: {tpath}")

    text = tpath.read_text(encoding="utf-8", errors="ignore")

    # TODO: replace stub with real MCP/LLM pipeline (segmentation + consolidation)
    ai_payload = call_ai_stub(text, episode_meta)

    ingest_ai_result("podcast", args.episode_id, ai_payload)
    print(f"✓ Ingested AI stub result for episode {args.episode_id}")


if __name__ == "__main__":
    main()

