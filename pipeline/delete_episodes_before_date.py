#!/usr/bin/env python3
"""
Delete all podcast episodes (and related data) published before a given date.
Use: python delete_episodes_before_date.py [--before YYYY-MM-DD] [--dry-run]
Default: before 2026-02-01 (Feb 2026).
"""
import argparse
import json
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "dashboard.db"
STATE_DIR = Path(__file__).parent / "state"
STATUS_FILE = STATE_DIR / "pipeline_status.json"
CURATION_LOG = STATE_DIR / "curation_log.json"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--before", default="2026-02-01", help="Delete episodes with episode_date < this (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="Only print what would be deleted")
    args = ap.parse_args()
    before = args.before
    dry_run = args.dry_run

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # 1. Get episode ids and (podcast_name, episode_title) for episode_date < before
    cursor = conn.execute(
        "SELECT id, podcast_name, episode_title, episode_date FROM podcast_episodes WHERE episode_date < ? ORDER BY episode_date",
        (before,),
    )
    rows = [dict(r) for r in cursor.fetchall()]
    if not rows:
        print(f"No episodes with episode_date < {before}. Nothing to delete.")
        conn.close()
        return

    ids = [r["id"] for r in rows]
    deleted_titles = [(r["podcast_name"], r["episode_title"]) for r in rows]
    print(f"Episodes to delete (episode_date < {before}): {len(ids)}")
    for r in rows:
        print(f"  - {r['episode_date']} | {r['podcast_name'][:40]} | {r['episode_title'][:50]}")

    if dry_run:
        print("\n[DRY RUN] Would delete related rows and then episodes. Exiting.")
        conn.close()
        return

    # 2. Get insight ids for these episodes
    placeholders = ",".join("?" * len(ids))
    insight_ids = [
        row[0]
        for row in conn.execute(
            f"SELECT id FROM latest_insights WHERE podcast_episode_id IN ({placeholders})",
            ids,
        ).fetchall()
    ]

    # 3. Delete deep_dive_content for those insights
    if insight_ids:
        ph = ",".join("?" * len(insight_ids))
        conn.execute(f"DELETE FROM deep_dive_content WHERE insight_id IN ({ph})", insight_ids)
        print(f"  Deleted deep_dive_content for {len(insight_ids)} insights")

    # 4. Delete latest_insights for these episodes
    conn.execute(f"DELETE FROM latest_insights WHERE podcast_episode_id IN ({placeholders})", ids)
    print(f"  Deleted latest_insights for {len(ids)} episodes")

    # 5. Delete appearances and ideas (source_type='podcast', source_id in ids)
    conn.execute("DELETE FROM appearances WHERE source_type = 'podcast' AND source_id IN (" + placeholders + ")", ids)
    conn.execute("DELETE FROM ideas WHERE source_type = 'podcast' AND source_id IN (" + placeholders + ")", ids)
    print("  Deleted appearances and ideas for those episodes")

    # 6. Delete ticker_mentions that match (source_name, episode_title) for podcast
    for podcast_name, episode_title in deleted_titles:
        conn.execute(
            "DELETE FROM ticker_mentions WHERE source_type = 'podcast' AND source_name = ? AND (episode_title = ? OR episode_title LIKE ?)",
            (podcast_name, episode_title, episode_title[:200] + "%"),
        )
    print("  Deleted matching ticker_mentions (podcast)")

    # 7. Delete podcast_episodes
    conn.execute(f"DELETE FROM podcast_episodes WHERE id IN ({placeholders})", ids)
    conn.commit()
    print(f"  Deleted {len(ids)} podcast_episodes")

    conn.close()

    # 8. Remove deleted episodes from pipeline_status.json so they don't show in "Episodes in pipeline"
    if STATUS_FILE.exists():
        try:
            with open(STATUS_FILE, "r") as f:
                status = json.load(f)
        except Exception as e:
            print(f"  ⚠ Could not read pipeline_status.json: {e}")
        else:
            episodes = status.get("episodes") or {}
            deleted_set = {(p, t[:60]) for p, t in deleted_titles}
            kept = {}
            for ep_id, data in episodes.items():
                info = data.get("info") or {}
                p, t = info.get("podcast", ""), info.get("title", "")[:60]
                if (p, t) not in deleted_set:
                    kept[ep_id] = data
            if len(kept) < len(episodes):
                status["episodes"] = kept
                with open(STATUS_FILE, "w") as f:
                    json.dump(status, f, indent=2)
                print(f"  Updated pipeline_status.json: removed {len(episodes) - len(kept)} episodes from tracking")
    print("Done.")


if __name__ == "__main__":
    main()
