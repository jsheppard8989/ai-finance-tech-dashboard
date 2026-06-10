#!/usr/bin/env python3
"""
Backfill overton_terms episode + speaker columns from suggested_terms (same term text).

Run after migrating DB columns so older Overton rows pick up attribution that already
exists on suggested_terms. Does not re-read transcripts; for that, re-run analyze on
unprocessed transcripts or a dedicated reanalysis job.

Usage (from pipeline/):
  python3 refresh_overton_attribution.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db_manager import get_db


def main() -> None:
    db = get_db()
    with db._get_connection() as conn:
        cur = conn.execute(
            """
            UPDATE overton_terms AS o
            SET
              first_detected_episode_id = COALESCE(o.first_detected_episode_id, s.first_seen_episode_id),
              first_detected_speaker = COALESCE(o.first_detected_speaker, s.first_seen_speaker),
              last_mentioned_episode_id = COALESCE(s.last_seen_episode_id, o.last_mentioned_episode_id),
              last_mentioned_speaker = COALESCE(s.last_seen_speaker, o.last_mentioned_speaker)
            FROM suggested_terms AS s
            WHERE LOWER(TRIM(o.term)) = LOWER(TRIM(s.term))
            """
        )
        n = cur.rowcount if cur.rowcount is not None else -1
    print(f"refresh_overton_attribution: rows touched = {n}")


if __name__ == "__main__":
    main()
