#!/usr/bin/env python3
"""Trap Map validator (separate from publish_guard.py). Fails the build on a bad site/data/trap_map.json.

Checks, per row:
  - a primary link (event.link; a relative link must exist under site/)
  - reason of 20 words or fewer
  - no banned word ("bet", "thin", and the house list below) anywhere in the public data
  - no live/new row whose grade date (or event date) is already past
  - stock tickers only (a basket's legs must each be a stock)
  - every event date confirmed (event.date_confirmed + event.date_source)
  - grade date on or before the option expiry
  - expiry past next earnings needs earnings_reason
  - a Holding row needs a fixed stop rule (an index level or an event)
  - a grade date, unless the status is Holding

Usage: python3 pipeline/trap_map_check.py [path/to/trap_map.json]   (exit 1 on any failure)
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data" / "trap_map.json"
# Kept here, not in the public JSON (the list itself would trip the site style gate).
ALWAYS_BANNED = ("bet", "bets", "betting", "thin", "ATM", "going-concern", "going concern", "RPO", "Scout", "IV",
                 "convert", "agent")
NON_STOCK = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "TLT", "GLD", "SLV", "USO", "VIX", "VIXY", "UVXY",
             "SPX", "NDX", "RUT", "BTC", "ETH", "SOL", "IBIT", "GBTC", "ETHA", "TQQQ", "SQQQ", "XLK", "XLF",
             "XLE", "XLV", "SMH", "SOXX", "ARKK", "HYG", "LQD", "EEM", "EFA"}
TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
LIVE = ("live", "new")


def _d(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def today_ct() -> date:
    return datetime.now(ZoneInfo("America/Chicago")).date()


def _strings(obj, skip=("rules",)):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip:
                continue
            yield from _strings(v, ())
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v, ())


def _is_stock(t) -> bool:
    return bool(t) and bool(TICKER_RE.match(str(t))) and str(t) not in NON_STOCK


def check(d: dict, today: date | None = None, site: Path = SITE) -> list[str]:
    today = today or today_ct()
    errs: list[str] = []
    banned = {w.lower() for w in ALWAYS_BANNED} | {w.lower() for w in (d.get("rules") or {}).get("banned_words", [])}
    for s in _strings(d):
        for w in banned:
            if re.search(r"(?<![\w-])" + re.escape(w) + r"(?![\w-])", s, re.I):
                errs.append(f"banned word {w!r} in: {s[:80]!r}")
    for r in d.get("rows") or []:
        rid = r.get("id") or r.get("ticker") or "?"
        st = (r.get("status") or "").lower()
        ev, tr = r.get("event") or {}, r.get("trade") or {}
        link = (ev.get("link") or "").strip()
        if not link:
            errs.append(f"{rid}: missing primary link")
        elif not re.match(r"https?://", link) and not (site / link.split("#")[0]).is_file():
            errs.append(f"{rid}: primary link {link} not found under site/")
        if len((r.get("reason") or "").split()) > 20:
            errs.append(f"{rid}: reason over 20 words")
        if not (r.get("reason") or "").strip():
            errs.append(f"{rid}: missing reason")
        if r.get("kind") == "basket" or tr.get("legs") and isinstance(tr["legs"][0], dict) and "ticker" in tr["legs"][0]:
            legs = [l.get("ticker") for l in tr.get("legs") or []]
            if not legs or not all(_is_stock(t) for t in legs):
                errs.append(f"{rid}: basket has a non-stock leg {legs}")
        elif not _is_stock(r.get("ticker")) or (tr.get("underlying") and not _is_stock(tr["underlying"])):
            errs.append(f"{rid}: non-stock ticker {r.get('ticker')!r}")
        if ev.get("date") and not (ev.get("date_confirmed") is True and (ev.get("date_source") or "").strip()):
            errs.append(f"{rid}: unconfirmed date {ev.get('date')}")
        if ev.get("date_confirmed") is False:
            errs.append(f"{rid}: unconfirmed date")
        gd, exp = _d(tr.get("grade_date")), _d(tr.get("expiry"))
        if st == "holding":
            sr = tr.get("stop_rule") or {}
            if not (sr.get("fixed") is True and (sr.get("index_below") is not None or (sr.get("event") or "").strip())
                    and (tr.get("stop") or "").strip()):
                errs.append(f"{rid}: Holding row without a fixed stop rule (index level or event)")
        elif not gd:
            errs.append(f"{rid}: missing grade date")
        if gd and exp and gd > exp:
            errs.append(f"{rid}: grade date {gd} after expiry {exp}")
        ne = _d(r.get("next_earnings"))
        if exp and ne and exp > ne and not (r.get("earnings_reason") or "").strip():
            errs.append(f"{rid}: expiry {exp} past earnings {ne} without earnings_reason")
        if st in LIVE:
            last = gd or _d(ev.get("date"))
            if last and last < today:
                errs.append(f"{rid}: live row is past-dated ({last})")
        if st in LIVE + ("holding",):
            for k in ("cost", "value", "mid_time"):
                if tr.get(k) in (None, ""):
                    errs.append(f"{rid}: trade.{k} is blank")
    b = d.get("benchmark") or {}
    for x in b.get("buys") or []:
        for k in ("date", "price", "shares", "source"):
            if x.get(k) in (None, ""):
                errs.append(f"benchmark buy {x.get('date')}: missing {k}")
    return errs


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    p = Path(argv[0]) if argv else DATA
    errs = check(json.loads(p.read_text(encoding="utf-8")))
    for e in errs:
        print("TRAP MAP CHECK FAIL:", e)
    if not errs:
        print("Trap Map check: ok")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
