"""Shared fail-closed helpers for site/data/market_data.json.

Reject conflict markers and invalid JSON; never overwrite a good on-disk
file with a bad payload. Fetch scripts use load/save so a conflicted file
does not brick subsequent curve/COT/compute updates.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

from workspace_paths import SITE_DATA_DIR

MARKET_DATA_FILE = SITE_DATA_DIR / "market_data.json"
MARKET_DATA_BAK = SITE_DATA_DIR / "market_data.json.last_good"

CONFLICT_MARKERS = ("<<<<<<<", "=======", ">>>>>>>")

_CONFLICT_BLOCK = re.compile(
    r"^<<<<<<<[^\n]*\n(.*?)^=+\n(.*?)^>>>>>>>[^\n]*\n",
    re.M | re.S,
)


def contains_conflict_markers(text: str) -> bool:
    return any(m in text for m in CONFLICT_MARKERS)


def strip_conflict_markers(text: str) -> str:
    """Resolve conflict hunks by preferring the second (stashed/incoming) side."""
    prev = None
    while prev != text:
        prev = text
        text = _CONFLICT_BLOCK.sub(lambda m: m.group(2) if m.group(2).strip() else m.group(1), text)
    return text


def validate_json_text(text: str, *, label: str = "file") -> Tuple[bool, str, Optional[Any]]:
    if contains_conflict_markers(text):
        return False, f"{label} has unresolved git conflict markers", None
    try:
        return True, "ok", json.loads(text)
    except json.JSONDecodeError as e:
        return False, f"{label} invalid JSON: {e}", None


def load_market_data(
    path: Path | None = None,
    *,
    repair: bool = True,
) -> Tuple[dict, str]:
    """Load market_data.json.

    Returns (data, note). On corrupt/conflicted file:
      - if repair=True, attempt marker strip + parse; on success write repaired file
        and refresh last_good backup.
      - else fall back to .last_good if present.
      - else return empty dict with an error note (caller should not wipe disk).
    """
    path = path or MARKET_DATA_FILE
    if not path.is_file():
        return {}, f"missing {path}"

    raw = path.read_text(encoding="utf-8")
    ok, msg, data = validate_json_text(raw, label=str(path))
    if ok and isinstance(data, dict):
        _remember_good(path, raw)
        return data, "ok"

    notes = [msg]
    if repair and contains_conflict_markers(raw):
        repaired = strip_conflict_markers(raw)
        ok2, msg2, data2 = validate_json_text(repaired, label=f"{path} (repaired)")
        if ok2 and isinstance(data2, dict):
            path.write_text(json.dumps(data2, indent=2) + "\n", encoding="utf-8")
            _remember_good(path, path.read_text(encoding="utf-8"))
            notes.append("repaired conflict markers in place")
            return data2, "; ".join(notes)

    bak = _load_backup()
    if bak is not None:
        notes.append(f"using {MARKET_DATA_BAK.name}")
        return bak, "; ".join(notes)

    return {}, "; ".join(notes)


def save_market_data(market_data: dict, path: Path | None = None) -> Tuple[bool, str]:
    """Atomic write of market_data.json; refuse invalid payloads; keep prior on failure."""
    path = path or MARKET_DATA_FILE
    if not isinstance(market_data, dict):
        return False, "market_data payload is not a dict"

    text = json.dumps(market_data, indent=2) + "\n"
    ok, msg, _ = validate_json_text(text, label="new market_data payload")
    if not ok:
        return False, msg

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        # Keep prior good copy before replace
        if path.is_file():
            prev = path.read_text(encoding="utf-8")
            pok, _, _ = validate_json_text(prev, label="prior")
            if pok:
                _remember_good(path, prev)
        tmp.replace(path)
        _remember_good(path, text)
        return True, "ok"
    except Exception as e:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        return False, str(e)


def _remember_good(path: Path, raw: str) -> None:
    try:
        MARKET_DATA_BAK.write_text(raw, encoding="utf-8")
    except OSError:
        pass


def _load_backup() -> Optional[dict]:
    if not MARKET_DATA_BAK.is_file():
        return None
    try:
        raw = MARKET_DATA_BAK.read_text(encoding="utf-8")
        ok, _, data = validate_json_text(raw, label=str(MARKET_DATA_BAK))
        if ok and isinstance(data, dict):
            return data
    except OSError:
        pass
    return None


def scan_site_for_conflict_or_bad_json(site_dir: Path) -> Tuple[bool, str]:
    """Fail-closed gate for Pages-facing HTML/JSON/JS under site/.

    Rejects conflict markers anywhere in .html/.json/.js (and nested data/).
    JSON files must json.loads. data.js is text-checked for markers only
    (not full JSON).
    """
    if not site_dir.is_dir():
        return False, f"Missing site dir {site_dir}"

    patterns = ("**/*.html", "**/*.json", "**/*.js")
    checked = 0
    for pattern in patterns:
        for path in sorted(site_dir.glob(pattern)):
            if not path.is_file():
                continue
            # Skip huge vendor if any
            if "node_modules" in path.parts:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except Exception as e:
                return False, f"Cannot read {path.relative_to(site_dir)}: {e}"
            checked += 1
            if contains_conflict_markers(text):
                return False, (
                    f"{path.relative_to(site_dir)} has unresolved git conflict markers "
                    "(<<<<<<< / ======= / >>>>>>>)"
                )
            if path.suffix == ".json":
                try:
                    json.loads(text)
                except json.JSONDecodeError as e:
                    return False, f"{path.relative_to(site_dir)} invalid JSON: {e}"

    # Explicit must-haves for plumbing cards
    must = [
        site_dir / "data" / "market_data.json",
        site_dir / "price_data.json",
        site_dir / "data" / "data.js",
    ]
    for m in must:
        if not m.is_file():
            # price_data may live under data/ in some layouts — tolerate either
            alt = site_dir / "data" / m.name if m.name == "price_data.json" else None
            if alt and alt.is_file():
                continue
            if m.name == "price_data.json":
                # optional path variants already covered by glob; require at least one
                if list(site_dir.glob("**/price_data.json")):
                    continue
            return False, f"Missing required Pages file: {m.relative_to(site_dir)}"

    return True, f"No conflict markers; JSON parse OK ({checked} files scanned)"
