#!/usr/bin/env python3
"""
One-time / maintenance: Set latest_insights.source_date from podcast_episodes.episode_date
for all insights that have a podcast_episode_id. Ensures insight cards and pundit cards
show the same date for the same episode (date consistency across the site).
"""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "dashboard.db"


def main():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Update source_date from linked episode's episode_date
    cursor = conn.execute("""
        UPDATE latest_insights
        SET source_date = (SELECT episode_date FROM podcast_episodes WHERE id = latest_insights.podcast_episode_id)
        WHERE podcast_episode_id IS NOT NULL
        AND (
            source_date IS NULL
            OR source_date != (SELECT episode_date FROM podcast_episodes WHERE id = latest_insights.podcast_episode_id)
        )
    """)
    updated = cursor.rowcount
    conn.commit()
    conn.close()
    print(f"Synced source_date from episode_date for {updated} insight(s).")
    if updated:
        print("Re-run export (generate_website_js) to refresh site data.")


if __name__ == "__main__":
    main()
