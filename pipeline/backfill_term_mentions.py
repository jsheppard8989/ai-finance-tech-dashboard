#!/usr/bin/env python3
"""
Re-scan all transcript files and record per-episode mentions for tracked Overton terms.

Resets last_seen / last_mentioned episode ids are NOT cleared — this only adds mentions
for episodes where the term appears and was not yet counted for that episode.

Usage (from pipeline/):
  python3 backfill_term_mentions.py
  python3 backfill_term_mentions.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from db_manager import get_db  # noqa: E402
from workspace_paths import TRANSCRIPT_DIR, PROCESSING_MARKER_DIR  # noqa: E402
from term_mention_scan import find_canonical_terms_in_text  # noqa: E402
from term_alias_util import expand_terms_for_scan  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill tracked term mentions from transcripts")
    ap.add_argument("--dry-run", action="store_true", help="Report only; do not write DB")
    args = ap.parse_args()

    db = get_db()
    transcripts = sorted(TRANSCRIPT_DIR.glob("*.txt"))
    print(f"Scanning {len(transcripts)} transcripts…")

    total_updates = 0
    term_totals: dict[str, int] = {}

    with db._get_connection() as conn:
        scan_pairs = expand_terms_for_scan(conn)
        print(f"Tracking {len({p[1].lower() for p in scan_pairs})} canonical terms")

        for path in transcripts:
            episode_id = None
            marker = PROCESSING_MARKER_DIR / f"{path.stem}.processed"
            if marker.exists():
                try:
                    meta = json.loads(marker.read_text(encoding="utf-8"))
                    episode_id = meta.get("episode_id")
                except Exception:
                    pass
            if not episode_id:
                meta_path = path.with_name(path.stem + ".meta.json")
                if meta_path.exists():
                    try:
                        meta = json.loads(meta_path.read_text(encoding="utf-8"))
                        episode_id = meta.get("episode_id")
                    except Exception:
                        pass
            if not episode_id:
                row = conn.execute(
                    "SELECT id FROM podcast_episodes WHERE transcript_path LIKE ? LIMIT 1",
                    (f"%{path.name}%",),
                ).fetchone()
                if row:
                    episode_id = row["id"]
            if not episode_id or int(episode_id) < 1:
                continue

            text = path.read_text(encoding="utf-8", errors="ignore")
            hits = find_canonical_terms_in_text(text, scan_pairs)
            for term in hits:
                if args.dry_run:
                    term_totals[term] = term_totals.get(term, 0) + 1
                    continue
                if db.record_tracked_term_episode_mention(
                    conn,
                    term,
                    episode_id=int(episode_id),
                ):
                    total_updates += 1
                    term_totals[term] = term_totals.get(term, 0) + 1

    if not args.dry_run:
        synced = db.sync_all_overton_from_suggested()
        print(f"Synced {synced} overton rows from suggested_terms")

    print(f"Done. Episode-term updates: {total_updates if not args.dry_run else 'dry-run'}")
    top = sorted(term_totals.items(), key=lambda x: -x[1])[:20]
    if top:
        print("Top terms by episodes matched:")
        for term, n in top:
            print(f"  {term}: {n}")


if __name__ == "__main__":
    main()
