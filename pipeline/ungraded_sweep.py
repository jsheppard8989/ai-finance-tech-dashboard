#!/usr/bin/env python3
"""Daily ungraded sweep (Red Team Fix 3, Jared yes 2026-10-16). Lists every public item dated before today with
no outcome field (process_checks.ungraded_items), plus the STALE list, and writes
<out-dir>/ungraded_guard_<date>.md (default /workspace/cos). Read-only on site/.
G's own routine writes ungraded_<date>.md at 11:17 CT; this file is the guard's copy, kept separate on purpose.
CLI: python3 ungraded_sweep.py [--site DIR] [--out-dir DIR] [--date YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import process_checks as pc  # noqa: E402


def render(site: Path, today: date) -> str:
    items = pc.ungraded_items(site, today)
    stale = pc.check_stale(site, today)
    out = [f"# Ungraded sweep (publish guard) {today.isoformat()}", "",
           f"Source: {site} (public site data). Items dated before {today.isoformat()} with no outcome field.",
           "Owner writes: happened / didn't / not disclosed + source, or UNVERIFIED. Target: graded within 2 trading days.",
           "", f"## Ungraded: {len(items)}", ""]
    out += [f"- {i['date']} | {i['where']} | {i.get('what') or ''} | missing: {i['missing']}" for i in items] or ["- none"]
    out += ["", f"## STALE (no exit / exit date / expiry; tickets > {pc.TICKET_STALE_DAYS}d, cards > {pc.CARD_STALE_DAYS}d): {len(stale)}", ""]
    out += [f"- STALE {s['kind']} | {s['where']} | {s['age_days']} days | missing: {', '.join(s['missing'])}" for s in stale] or ["- none"]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", default=str(_HERE.parent / "site"))
    ap.add_argument("--out-dir", default="/workspace/cos")
    ap.add_argument("--date", default=None)
    a = ap.parse_args(argv)
    today = date.fromisoformat(a.date) if a.date else pc._today()
    p = Path(a.out_dir) / f"ungraded_guard_{today.isoformat()}.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(render(Path(a.site), today), encoding="utf-8")
    print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
