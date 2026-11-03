"""Deep Dive "What would change our view" lists name only future events (Jared's rule, Nov 2 2026).

drop_past_falsifiers() removes falsification_tracks lines whose date has already passed at build
time. Conservative: a line is dropped only when it carries at least one parseable date AND every
date it names (its latest one) is before the build date. Lines with no parseable date stay.

Formats: "Sep 30", "Sep 30, 2026", "September 30 2026", "2026-09-30", "Nov 2025",
"Q3 2026" / "by Q3 2026" / "3Q26". "end of 2026" is not parsed (stays).
A quarter named as a report ("the Q3 2026 10-Q / earnings / PCE release") resolves to quarter end
+ one more quarter, since that report comes out after the quarter closes.
A line naming a date after "after"/"since"/"following" (e.g. "the next earnings after 2026-10-28")
points at an open-ended future event and always stays.
A day+month without a year takes the year of the deep dive's source/created date, rolled to the
next year if that would put it before the source date (an episode only names dates ahead of it).
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_name) if m})
_MONTHS["sept"] = 9
_MON = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|June?|July?|Aug(?:ust)?|Sept?(?:ember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?"

# Month Day[, Year]  (case-sensitive month: "may" the verb never matches)
_MDY = re.compile(_MON + r"\s+(\d{1,2})(?:st|nd|rd|th)?\b(?:,?\s+(\d{4})\b)?")
# Month Year (no day)
_MY = re.compile(_MON + r",?\s+(\d{4})\b")
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_Q = re.compile(r"\bQ([1-4])\s*(?:FY\s*)?'?(\d{4}|\d{2})\b")
_Q2 = re.compile(r"\b([1-4])Q\s*'?(\d{4}|\d{2})\b")
_REPORT_AFTER = re.compile(r"^\W*(?:\w+\W+){0,3}?(?:release|earnings|report|results|10-Q|10-K|filing|print|data)\b", re.I)
_OPEN_ENDED = re.compile(r"\b(?:after|since|following)\s*$", re.I)


def _year(y: str) -> int:
    y = int(y)
    return y + 2000 if y < 100 else y


def _anchor(dd: dict, today: date) -> date:
    for k in ("source_date", "created_at"):
        v = str(dd.get(k) or "")[:10]
        try:
            return datetime.strptime(v, "%Y-%m-%d").date()
        except ValueError:
            continue
    return today


def line_dates(text: str, anchor: date) -> list[date]:
    """All dates a line names, each resolved to the last day it covers."""
    out: list[date] = []
    taken: list[tuple[int, int]] = []

    def add(d, span):
        if _OPEN_ENDED.search(text[:span[0]]):
            out.append(date.max)  # open-ended future event: never past
            taken.append(span)
            return
        out.append(d)
        taken.append(span)

    for m in _ISO.finditer(text):
        try:
            add(date(int(m[1]), int(m[2]), int(m[3])), m.span())
        except ValueError:
            pass
    for m in _MDY.finditer(text):
        mon, day = _MONTHS[m[1].lower().rstrip(".")], int(m[2])
        if m[3] is None and day > 31:
            continue
        try:
            if m[3]:
                d = date(int(m[3]), mon, day)
            else:
                d = date(anchor.year, mon, day)
                if d < anchor:
                    d = date(anchor.year + 1, mon, day)
        except ValueError:
            continue
        add(d, m.span())
    for m in _MY.finditer(text):
        if any(a <= m.start() < b for a, b in taken):
            continue
        y, mon = int(m[2]), _MONTHS[m[1].lower().rstrip(".")]
        add(date(y, mon, calendar.monthrange(y, mon)[1]), m.span())
    for rx in (_Q, _Q2):
        for m in rx.finditer(text):
            q, y = int(m[1]), _year(m[2])
            if _REPORT_AFTER.match(text[m.end():]):
                q += 1
                if q == 5:
                    q, y = 1, y + 1
            mon = q * 3
            add(date(y, mon, calendar.monthrange(y, mon)[1]), m.span())
    return out


def is_past(text: str, today: date, anchor: date | None = None) -> bool:
    ds = line_dates(str(text), anchor or today)
    return bool(ds) and max(ds) < today


def drop_past_falsifiers(deepdives, today: date | None = None) -> list[tuple[str, str]]:
    """Mutates deep dives in place (dict keyed by id, or list). Returns [(id, dropped line)]."""
    today = today or date.today()
    items = deepdives.values() if isinstance(deepdives, dict) else (deepdives or [])
    dropped = []
    for dd in items:
        if not isinstance(dd, dict):
            continue
        tracks = dd.get("falsification_tracks")
        if not isinstance(tracks, list):
            continue
        anchor = _anchor(dd, today)
        keep = []
        for line in tracks:
            if isinstance(line, str) and is_past(line, today, anchor):
                dropped.append((str(dd.get("insight_id") or dd.get("id")), line))
            else:
                keep.append(line)
        dd["falsification_tracks"] = keep
    return dropped


def apply_to_data_js(path, today: date | None = None, write: bool = True) -> list[tuple[str, str]]:
    """Apply the same filter to an already-exported site/data/data.js (no DB needed).
    Rewrites only the deepDives value, serialized exactly as export_data does (json.dumps indent=2)."""
    import json
    from pathlib import Path

    p = Path(path)
    text = p.read_text(encoding="utf-8")
    key = "\n  deepDives: "
    i = text.index(key) + len(key)
    obj, end = json.JSONDecoder().raw_decode(text, i)
    if json.dumps(obj, indent=2) != text[i:end]:
        raise RuntimeError("deepDives block is not in export_data's format; refusing to rewrite")
    dropped = drop_past_falsifiers(obj, today)
    if dropped and write:
        p.write_text(text[:i] + json.dumps(obj, indent=2) + text[end:], encoding="utf-8")
    return dropped


if __name__ == "__main__":
    import argparse
    from workspace_paths import SITE_DATA_DIR

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dropped = apply_to_data_js(SITE_DATA_DIR / "data.js", write=not a.dry_run)
    for iid, line in dropped:
        print(f"{iid}: {line}")
    if dropped and not a.dry_run:
        from export_data import bump_data_js_cache_in_site_html
        bump_data_js_cache_in_site_html()  # same cache bump export_data does after writing data.js
