#!/usr/bin/env python3
"""
Regenerate trap_map_home.json from trap_map.json.

This script reads the full trap_map.json and produces a lightweight summary
for the home page with:
  - last_monitored: last 3 traps by most recent updated_at
  - upcoming_watches: next 3 upcoming watches from next_datapoint fields

Called automatically when export_data runs (same path as weekday strip refresh).
Can also be invoked directly after stamping a trap datapoint.

Usage:
  python3 regenerate_trap_home.py              # Regenerate from trap_map.json
  python3 regenerate_trap_home.py --dry-run    # Show output without writing
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from workspace_paths import SITE_DATA_DIR

TRAP_MAP_PATH = SITE_DATA_DIR / "trap_map.json"
TRAP_HOME_PATH = SITE_DATA_DIR / "trap_map_home.json"


def _parse_date_key(date_str: str) -> tuple[int, int, int]:
    """
    Extract sortable (year, month, day) from date strings.
    Handles various formats: "2026-09-14", "Sep 16 2026", "Nov 4 2026", etc.
    Returns (9999, 12, 31) for unparseable dates (sorts to end).
    """
    if not date_str:
        return (9999, 12, 31)
    
    s = str(date_str).strip()
    
    iso_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if iso_match:
        return (int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3)))
    
    month_map = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
    }
    text_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2})(?:\s+|,\s*)(\d{4})", s, re.IGNORECASE)
    if text_match:
        month = month_map.get(text_match.group(1).lower()[:3], 12)
        return (int(text_match.group(3)), month, int(text_match.group(2)))
    
    month_year_match = re.search(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{4})", s, re.IGNORECASE)
    if month_year_match:
        month = month_map.get(month_year_match.group(1).lower()[:3], 12)
        return (int(month_year_match.group(2)), month, 15)
    
    year_match = re.search(r"\b(202\d)\b", s)
    if year_match:
        return (int(year_match.group(1)), 6, 15)
    
    return (9999, 12, 31)


def _shorten_title(title: str, max_len: int = 30) -> str:
    """Create a short title for display."""
    if not title:
        return ""
    title = title.strip()
    if len(title) <= max_len:
        return title
    long_prefix_cut = re.sub(r"^(Power \+ interconnect into|ARK Genomic Revolution —|AST SpaceMobile —|Buyback as confession —)\s*", "", title)
    if long_prefix_cut != title and len(long_prefix_cut) <= max_len:
        return long_prefix_cut
    return title[:max_len - 3].rstrip() + "..."


def _extract_upcoming_watch(trap: dict) -> dict | None:
    """
    Extract upcoming watch info from a trap's next_datapoint.
    Returns None if no valid upcoming watch.
    """
    nd = trap.get("next_datapoint")
    if not nd:
        return None
    
    label = nd.get("label", "") or ""
    expected = nd.get("expected_date", "") or ""
    
    if not label and not expected:
        return None
    
    what = label[:100] if label else expected[:100]
    
    date_label = expected if expected else ""
    if not date_label and label:
        date_match = re.search(
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2}(?:\s+|,\s*)\d{4}|"
            r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{4}|"
            r"\d{4}-\d{2}-\d{2}",
            label, re.IGNORECASE
        )
        if date_match:
            date_label = date_match.group(0)
    
    return {
        "trap_id": trap.get("id", ""),
        "date_label": date_label,
        "what": what,
        "_sort_key": _parse_date_key(date_label or expected),
    }


def regenerate_trap_home(trap_map_path: Path = TRAP_MAP_PATH) -> dict:
    """
    Read trap_map.json and generate trap_map_home.json content.
    
    Returns the generated home data dict.
    Raises FileNotFoundError if trap_map.json doesn't exist.
    """
    if not trap_map_path.is_file():
        raise FileNotFoundError(f"trap_map.json not found at {trap_map_path}")
    
    data = json.loads(trap_map_path.read_text(encoding="utf-8"))
    traps = data.get("traps", [])
    
    sorted_by_updated = sorted(
        traps,
        key=lambda t: _parse_date_key(t.get("updated_at", "")),
        reverse=True
    )
    
    last_monitored = []
    for trap in sorted_by_updated[:3]:
        title = trap.get("title", "")
        short_title = _shorten_title(title)
        if trap.get("id") == "trap-1-power-interconnect":
            short_title = "Power + DC interconnect"
        elif trap.get("id") == "buyback-confession-captive-duration":
            short_title = "Buyback / captive duration"
        elif trap.get("id") == "asts-secondary-watch":
            short_title = "AST SpaceMobile"
        elif trap.get("id") == "arkg-hold-goalposts":
            short_title = "ARK Genomic / ARKG"
        
        last_monitored.append({
            "id": trap.get("id", ""),
            "short_title": short_title,
            "status": trap.get("validation_status", ""),
            "updated_at": trap.get("updated_at", ""),
        })
    
    upcoming_raw = []
    for trap in traps:
        watch = _extract_upcoming_watch(trap)
        if watch:
            upcoming_raw.append(watch)
    
    upcoming_raw.sort(key=lambda w: w["_sort_key"])
    
    upcoming_watches = []
    for watch in upcoming_raw[:3]:
        upcoming_watches.append({
            "trap_id": watch["trap_id"],
            "date_label": watch["date_label"],
            "what": watch["what"],
        })
    
    home_data = {
        "_comment": "Home page summary of Trap Map. Regenerate from trap_map.json when a trap datapoint is stamped. Script hook: pipeline/regenerate_trap_home.py",
        "_generated_at": datetime.now(tz=__import__('datetime').timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "_source": "data/trap_map.json",
        "last_monitored": last_monitored,
        "upcoming_watches": upcoming_watches,
    }
    
    return home_data


def write_trap_home(home_data: dict, output_path: Path = TRAP_HOME_PATH) -> None:
    """Write the trap home data to the output path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(home_data, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Regenerate trap_map_home.json from trap_map.json")
    ap.add_argument("--dry-run", action="store_true", help="Print output without writing file")
    args = ap.parse_args()
    
    try:
        home_data = regenerate_trap_home()
    except FileNotFoundError as e:
        print(f"✗ {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"✗ Invalid JSON in trap_map.json: {e}")
        return 1
    
    if args.dry_run:
        print(json.dumps(home_data, indent=2))
        print(f"\n(dry run — would write to {TRAP_HOME_PATH})")
        return 0
    
    write_trap_home(home_data)
    print(f"✓ Regenerated {TRAP_HOME_PATH.name}")
    print(f"  last_monitored: {len(home_data['last_monitored'])} traps")
    print(f"  upcoming_watches: {len(home_data['upcoming_watches'])} watches")
    return 0


if __name__ == "__main__":
    sys.exit(main())
