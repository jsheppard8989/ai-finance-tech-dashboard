"""Permanent Deep Dive skips (config only; never touches the DB).

Source of truth: pipeline/deepdive_permanent_skips.json ({"skips": [{"insight_id": ..., "reason": ...}]}).
Undo a skip by removing its entry from that file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

SKIPS_PATH = Path(__file__).resolve().parent / "deepdive_permanent_skips.json"


def load_permanent_skips(path: Optional[Path] = None) -> Dict[int, dict]:
    """Return {insight_id: entry}. Missing file -> {}. Malformed file raises (fail loud, not silent)."""
    p = Path(path) if path is not None else SKIPS_PATH
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    out: Dict[int, dict] = {}
    for entry in data.get("skips") or []:
        iid = int(entry["insight_id"])
        out[iid] = dict(entry, insight_id=iid)
    return out


def filter_skipped_ids(
    insight_ids: Iterable[int], skips: Dict[int, dict], force: bool = False
) -> Tuple[List[int], List[int]]:
    """Split requested ids into (kept, skipped). With force=True nothing is skipped."""
    ids = list(insight_ids)
    if force:
        return ids, []
    kept = [i for i in ids if i not in skips]
    skipped = [i for i in ids if i in skips]
    return kept, skipped
