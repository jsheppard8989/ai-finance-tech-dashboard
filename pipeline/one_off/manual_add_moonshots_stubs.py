#!/usr/bin/env python3
"""
One-off helper to insert Moonshots episodes into podcast_episodes when
AI analysis is blocked (e.g. content filter), using RSS sidecar metadata
only. This creates minimal episode rows so the pipeline can advance.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workspace_paths import TRANSCRIPT_DIR as TRANSCRIPTS_DIR

from db_manager import DashboardDB, PodcastEpisode, DB_PATH


def load_sidecar(stem: str) -> dict:
    meta_path = TRANSCRIPTS_DIR / f"{stem}.meta.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"Missing sidecar: {meta_path}")
    with meta_path.open() as f:
        return json.load(f)


def ensure_episode_from_sidecar(stem: str) -> int:
    """Insert a minimal PodcastEpisode row based on sidecar metadata.

    Returns the existing or newly created episode id.
    """
    sidecar = load_sidecar(stem)
    rss_guid = (sidecar.get("rss_guid") or "").strip()
    podcast_name = (sidecar.get("podcast_name") or "").strip() or "Moonshots with Peter Diamandis"
    episode_title = (sidecar.get("episode_title") or "").strip()
    published_date = (sidecar.get("published_date") or "").strip()
    audio_url = (sidecar.get("audio_url") or "").strip()

    if not episode_title:
        raise ValueError(f"Sidecar {stem} missing episode_title")
    if not published_date:
        raise ValueError(f"Sidecar {stem} missing published_date")

    year, month, day = map(int, published_date.split("-"))
    ep_date = date(year, month, day)

    db = DashboardDB(DB_PATH)

    # If we already have an episode with this rss_guid, return it.
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if rss_guid:
            cur = conn.execute(
                "SELECT id FROM podcast_episodes WHERE rss_guid = ?",
                (rss_guid,),
            )
            row = cur.fetchone()
            if row:
                return int(row["id"])

        # Fallback: look for exact title match on this podcast and date.
        cur = conn.execute(
            """
            SELECT id FROM podcast_episodes
            WHERE podcast_name = ? AND episode_title = ? AND episode_date = ?
            """,
            (podcast_name, episode_title, published_date),
        )
        row = cur.fetchone()
        if row:
            # Backfill rss_guid if missing.
            if rss_guid:
                conn.execute(
                    "UPDATE podcast_episodes SET rss_guid = ? WHERE id = ? AND (rss_guid IS NULL OR rss_guid = '')",
                    (rss_guid, row["id"]),
                )
                conn.commit()
            return int(row["id"])

    # No existing row: create a minimal episode.
    transcript_path = str(TRANSCRIPTS_DIR / f"{stem}.txt")
    episode = PodcastEpisode(
        podcast_name=podcast_name,
        episode_title=episode_title,
        episode_date=ep_date,
        audio_url=audio_url or None,
        transcript_path=transcript_path,
        summary=None,
        key_takeaways=None,
        key_tickers=None,
        investment_thesis=None,
        relevance_score=0,
    )

    episode_id = db.add_podcast_episode(episode)

    # Backfill rss_guid and mark as not-yet-processed for clarity.
    with sqlite3.connect(DB_PATH) as conn:
        if rss_guid:
            conn.execute(
                "UPDATE podcast_episodes SET rss_guid = ?, is_processed = 0 WHERE id = ?",
                (rss_guid, episode_id),
            )
        else:
            conn.execute(
                "UPDATE podcast_episodes SET is_processed = 0 WHERE id = ?",
                (episode_id,),
            )
        conn.commit()

    return episode_id


def main() -> None:
    targets = ["DVVTS6372073266", "DVVTS3579530070"]
    ids = []
    for stem in targets:
        eid = ensure_episode_from_sidecar(stem)
        print(f"Episode for {stem}: id={eid}")
        ids.append(eid)
    print("Done. Episodes inserted/ensured:", ids)


if __name__ == "__main__":
    main()

