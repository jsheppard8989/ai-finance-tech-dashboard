#!/usr/bin/env python3
"""
Scrub stale catalyst/watchlist dates from deep_dive_content.

Removes or flags catalyst items whose target dates are clearly before the episode date.
For example, "Q4 2023" deadlines on a Sep 2026 episode are hallucinated/stale.

Usage:
    python3 scrub_stale_catalysts.py          # Dry-run: show what would be removed
    python3 scrub_stale_catalysts.py --fix    # Actually fix the database
"""

import argparse
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Tuple, Optional

DB_PATH = Path(__file__).parent / "dashboard.db"

QUARTER_TO_MONTH = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
QUARTER_YEAR_PATTERN = re.compile(r"\b(Q[1-4])\s*(20\d{2})\b", re.IGNORECASE)
MONTH_YEAR_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
    re.IGNORECASE,
)
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def extract_target_date(catalyst: str) -> Optional[Tuple[int, int]]:
    """Extract (year, month) from a catalyst string. Returns None if no date found."""
    qy = QUARTER_YEAR_PATTERN.search(catalyst)
    if qy:
        quarter = qy.group(1).upper()
        year = int(qy.group(2))
        return (year, QUARTER_TO_MONTH[quarter])

    my = MONTH_YEAR_PATTERN.search(catalyst)
    if my:
        month_name = my.group(1).lower()
        year = int(my.group(2))
        return (year, MONTH_MAP[month_name])

    ym = YEAR_PATTERN.search(catalyst)
    if ym:
        year = int(ym.group(1))
        return (year, 12)

    return None


def is_stale_catalyst(catalyst: str, episode_year: int, episode_month: int) -> bool:
    """Check if a catalyst's target date is before the episode date."""
    target = extract_target_date(catalyst)
    if not target:
        return False

    target_year, target_month = target
    if target_year < episode_year:
        return True
    if target_year == episode_year and target_month < episode_month:
        return True
    return False


def parse_episode_date(date_str: str) -> Tuple[int, int]:
    """Parse YYYY-MM-DD or similar to (year, month)."""
    if not date_str:
        return (2026, 9)
    try:
        dt = datetime.fromisoformat(date_str[:10])
        return (dt.year, dt.month)
    except Exception:
        m = re.search(r"(\d{4})-(\d{2})", date_str)
        if m:
            return (int(m.group(1)), int(m.group(2)))
    return (2026, 9)


def scrub_catalysts(dry_run: bool = True) -> List[dict]:
    """Scrub stale catalysts from all deep dives. Returns list of changes."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    changes = []

    cursor = conn.execute("""
        SELECT ddc.id, ddc.insight_id, ddc.catalysts, li.title, li.source_date
        FROM deep_dive_content ddc
        JOIN latest_insights li ON ddc.insight_id = li.id
        WHERE ddc.catalysts IS NOT NULL AND ddc.catalysts != '' AND ddc.catalysts != '[]'
    """)

    for row in cursor:
        dd_id = row["id"]
        insight_id = row["insight_id"]
        title = row["title"] or ""
        source_date = row["source_date"] or ""
        catalysts_json = row["catalysts"]

        try:
            catalysts = json.loads(catalysts_json)
        except (json.JSONDecodeError, TypeError):
            continue

        if not isinstance(catalysts, list):
            continue

        ep_year, ep_month = parse_episode_date(source_date)

        stale_items = []
        clean_items = []
        for cat in catalysts:
            if not isinstance(cat, str):
                clean_items.append(cat)
                continue
            if is_stale_catalyst(cat, ep_year, ep_month):
                stale_items.append(cat)
            else:
                clean_items.append(cat)

        if stale_items:
            changes.append({
                "dd_id": dd_id,
                "insight_id": insight_id,
                "title": title,
                "source_date": source_date,
                "removed": stale_items,
                "kept": clean_items,
            })

            if not dry_run:
                conn.execute(
                    "UPDATE deep_dive_content SET catalysts = ? WHERE id = ?",
                    (json.dumps(clean_items), dd_id)
                )

    if not dry_run:
        conn.commit()

    conn.close()
    return changes


def main():
    parser = argparse.ArgumentParser(description="Scrub stale catalyst dates from deep dives")
    parser.add_argument("--fix", action="store_true", help="Actually fix the database (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.fix
    mode = "DRY RUN" if dry_run else "FIXING"
    print(f"\n{'='*60}")
    print(f"Scrubbing Stale Catalysts ({mode})")
    print(f"{'='*60}\n")

    changes = scrub_catalysts(dry_run=dry_run)

    if not changes:
        print("No stale catalysts found.")
        return

    for c in changes:
        print(f"[{c['insight_id']}] {c['title'][:60]}")
        print(f"    Episode date: {c['source_date']}")
        print(f"    REMOVED ({len(c['removed'])}):")
        for item in c["removed"]:
            print(f"      - {item}")
        if c["kept"]:
            print(f"    KEPT ({len(c['kept'])}):")
            for item in c["kept"]:
                print(f"      + {item}")
        print()

    print(f"\nTotal: {len(changes)} deep dive(s) with stale catalysts")
    if dry_run:
        print("Run with --fix to apply changes.")
    else:
        print("Changes applied to database.")


if __name__ == "__main__":
    main()
