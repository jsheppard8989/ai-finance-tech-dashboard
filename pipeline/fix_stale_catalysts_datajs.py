#!/usr/bin/env python3
"""
Fix stale catalyst/watchlist dates directly in site/data/data.js.

Since the database is empty, this script works on the exported data.js file.
"""

import argparse
import json
import re
from pathlib import Path

SITE_DATA_JS = Path(__file__).parent.parent / "site" / "data" / "data.js"

QUARTER_TO_MONTH = {"Q1": 3, "Q2": 6, "Q3": 9, "Q4": 12}
QUARTER_YEAR_PATTERN = re.compile(r"\b(Q[1-4])\s*(20\d{2})\b", re.IGNORECASE)
MONTH_YEAR_PATTERN = re.compile(
    r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(20\d{2})\b",
    re.IGNORECASE,
)
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
H_YEAR_PATTERN = re.compile(r"\b(H[12])\s*(20\d{2})\b", re.IGNORECASE)


def extract_target_date(catalyst: str):
    """Extract (year, month) from a catalyst string."""
    qy = QUARTER_YEAR_PATTERN.search(catalyst)
    if qy:
        quarter = qy.group(1).upper()
        year = int(qy.group(2))
        return (year, QUARTER_TO_MONTH[quarter])

    hy = H_YEAR_PATTERN.search(catalyst)
    if hy:
        half = hy.group(1).upper()
        year = int(hy.group(2))
        return (year, 6 if half == "H1" else 12)

    my = MONTH_YEAR_PATTERN.search(catalyst)
    if my:
        month_name = my.group(1).lower()
        year = int(my.group(2))
        return (year, MONTH_MAP[month_name])

    standalone_year = re.match(r"^\s*(\d{4}):", catalyst)
    if standalone_year:
        return (int(standalone_year.group(1)), 12)

    late_year = re.search(r"\b(Late|End of|end-of-year)\s+(20\d{2})\b", catalyst, re.IGNORECASE)
    if late_year:
        return (int(late_year.group(2)), 12)

    mid_year = re.search(r"\bmid[- ]?(20\d{2})\b", catalyst, re.IGNORECASE)
    if mid_year:
        return (int(mid_year.group(1)), 6)

    early_year = re.search(r"\b(early|beginning of)\s+(20\d{2})\b", catalyst, re.IGNORECASE)
    if early_year:
        return (int(early_year.group(2)), 3)

    return None


def is_stale_catalyst(catalyst: str, episode_year: int, episode_month: int) -> bool:
    """Check if a catalyst's target date is clearly before the episode date."""
    target = extract_target_date(catalyst)
    if not target:
        return False

    target_year, target_month = target
    if target_year < episode_year:
        return True
    if target_year == episode_year and target_month < episode_month:
        return True
    return False


def find_deepdive_entries(content: str):
    """Find all deep dive entries with their boundaries and source dates."""
    deepdives_start = content.find("deepDives: {")
    if deepdives_start == -1:
        return []

    entries = []
    pos = deepdives_start

    entry_pattern = re.compile(r'"(\d+)":\s*\{')
    for match in entry_pattern.finditer(content, pos):
        entry_start = match.start()

        brace_count = 0
        entry_end = match.end() - 1
        for i, char in enumerate(content[match.end()-1:], match.end()-1):
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    entry_end = i + 1
                    break

        entry_text = content[entry_start:entry_end]

        source_date_match = re.search(r'"source_date":\s*"(\d{4}-\d{2}-\d{2})"', entry_text)
        title_match = re.search(r'"insight_title":\s*"([^"]*)"', entry_text)
        catalysts_match = re.search(r'"catalysts":\s*\[(.*?)\]', entry_text, re.DOTALL)

        if source_date_match and catalysts_match:
            source_date = source_date_match.group(1)
            title = title_match.group(1)[:60] if title_match else "Unknown"
            catalysts_str = catalysts_match.group(1)

            catalysts = []
            for item_match in re.finditer(r'"((?:[^"\\]|\\.)*)"', catalysts_str):
                catalysts.append(item_match.group(1))

            entries.append({
                "entry_start": entry_start,
                "entry_end": entry_end,
                "source_date": source_date,
                "title": title,
                "catalysts": catalysts,
                "catalysts_start": entry_start + catalysts_match.start(),
                "catalysts_end": entry_start + catalysts_match.end(),
            })

    return entries


def fix_stale_catalysts(dry_run: bool = True):
    """Fix stale catalysts in data.js."""
    content = SITE_DATA_JS.read_text(encoding="utf-8")

    entries = find_deepdive_entries(content)
    if not entries:
        print("Could not find deepDives entries in data.js")
        return []

    changes = []

    for entry in entries:
        source_date = entry["source_date"]
        ep_year = int(source_date[:4])
        ep_month = int(source_date[5:7])

        stale_items = []
        clean_items = []
        for cat in entry["catalysts"]:
            if is_stale_catalyst(cat, ep_year, ep_month):
                stale_items.append(cat)
            else:
                clean_items.append(cat)

        if stale_items:
            changes.append({
                "title": entry["title"],
                "source_date": source_date,
                "removed": stale_items,
                "kept": clean_items,
                "catalysts_start": entry["catalysts_start"],
                "catalysts_end": entry["catalysts_end"],
                "new_value": json.dumps(clean_items),
            })

    if not dry_run and changes:
        changes_sorted = sorted(changes, key=lambda x: x["catalysts_start"], reverse=True)
        for c in changes_sorted:
            new_text = f'"catalysts": {c["new_value"]}'
            content = content[:c["catalysts_start"]] + new_text + content[c["catalysts_end"]:]

        SITE_DATA_JS.write_text(content, encoding="utf-8")

    return changes


def main():
    parser = argparse.ArgumentParser(description="Fix stale catalyst dates in data.js")
    parser.add_argument("--fix", action="store_true", help="Actually fix the file (default: dry-run)")
    args = parser.parse_args()

    dry_run = not args.fix
    mode = "DRY RUN" if dry_run else "FIXING"
    print(f"\n{'='*60}")
    print(f"Scrubbing Stale Catalysts from data.js ({mode})")
    print(f"{'='*60}\n")

    changes = fix_stale_catalysts(dry_run=dry_run)

    if not changes:
        print("No stale catalysts found.")
        return

    for c in changes:
        print(f"Episode: {c['title']}")
        print(f"    Date: {c['source_date']}")
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
        print("Changes applied to data.js.")


if __name__ == "__main__":
    main()
