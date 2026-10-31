#!/usr/bin/env python3
"""Trap Map validator (separate from publish_guard.py). Fails the build on a bad site/data/trap_map.json.

Checks, per row:
  - a primary link (event.link; a relative link must exist under site/)
  - reason of 20 words or fewer
  - no banned word ("bet", "thin", and the house list below) anywhere in the public data
  - no live/new row whose exit date (the option expiry) is already past
  - stock tickers only (a basket's legs must each be a stock)
  - every event date confirmed (event.date_confirmed + event.date_source)
  - every option row exits at its expiry: trade.exit = {type: expiry, date: trade.expiry}
  - expiry past next earnings needs earnings_reason
  - a Holding row needs a fixed stop rule (an index level or an event)
  - no grading anywhere (Jared, Oct 31): no "grade"/"graded" words in public text, no grade* keys
  - past_calls: each entry has ticker, outcome_text, exit_reason (one of EXIT_REASONS) and evidence_url
  - v9: every open row has a direction (Long/Short/Net long/Net short) and an expression; the direction
    matches the trade type (put debit spread -> Net short, call debit spread -> Net long, stock basket -> Long)
    and the lean (Positive for long, Negative for short)
  - v9 (check_computed, after build): each row's change equals value minus cost, and totals equal the row sums

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
                 "convert", "agent", "grade", "grades", "graded", "grading")
NON_STOCK = {"SPY", "QQQ", "IWM", "DIA", "VOO", "VTI", "TLT", "GLD", "SLV", "USO", "VIX", "VIXY", "UVXY",
             "SPX", "NDX", "RUT", "BTC", "ETH", "SOL", "IBIT", "GBTC", "ETHA", "TQQQ", "SQQQ", "XLK", "XLF",
             "XLE", "XLV", "SMH", "SOXX", "ARKK", "HYG", "LQD", "EEM", "EFA"}
TICKER_RE = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")
LIVE = ("live", "new")
CLOSED = "closed"
# How a past call ended. "not placed" and "no data" are listed but never counted.
EXIT_REASONS = ("stop", "target", "expiry", "time exit", "reported", "no trade", "open", "not placed", "no data")
PAST_CALL_FIELDS = ("ticker", "outcome_text", "exit_reason", "evidence_url")


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
        if r.get("kind") == "spread_set":
            und = [s.get("underlying") for s in tr.get("spreads") or []]
            if not und or not all(_is_stock(t) for t in und):
                errs.append(f"{rid}: spread set has a non-stock underlying {und}")
            for s in tr.get("spreads") or []:
                if s.get("expiry") != tr.get("expiry"):
                    errs.append(f"{rid}: {s.get('underlying')} spread expiry {s.get('expiry')} differs from the row expiry")
        elif r.get("kind") == "basket" or tr.get("legs") and isinstance(tr["legs"][0], dict) and "ticker" in tr["legs"][0]:
            legs = [l.get("ticker") for l in tr.get("legs") or []]
            if not legs or not all(_is_stock(t) for t in legs):
                errs.append(f"{rid}: basket has a non-stock leg {legs}")
        elif not _is_stock(r.get("ticker")) or (tr.get("underlying") and not _is_stock(tr["underlying"])):
            errs.append(f"{rid}: non-stock ticker {r.get('ticker')!r}")
        if ev.get("date") and not (ev.get("date_confirmed") is True and (ev.get("date_source") or "").strip()):
            errs.append(f"{rid}: unconfirmed date {ev.get('date')}")
        if ev.get("date_confirmed") is False:
            errs.append(f"{rid}: unconfirmed date")
        exp = _d(tr.get("expiry"))
        ex = tr.get("exit") or {}
        if st == "holding":
            sr = tr.get("stop_rule") or {}
            if not (sr.get("fixed") is True and (sr.get("index_below") is not None or (sr.get("event") or "").strip())
                    and (tr.get("stop") or "").strip()):
                errs.append(f"{rid}: Holding row without a fixed stop rule (index level or event)")
        elif st in LIVE:
            if not exp:
                errs.append(f"{rid}: option row without an expiry")
            elif ex.get("type") != "expiry" or _d(ex.get("date")) != exp:
                errs.append(f"{rid}: exit must be the option expiry {exp} (got {ex.get('type')} {ex.get('date')})")
        ne = _d(r.get("next_earnings"))
        if exp and ne and exp > ne and not (r.get("earnings_reason") or "").strip():
            errs.append(f"{rid}: expiry {exp} past earnings {ne} without earnings_reason")
        if st in LIVE:
            last = exp
            if last and last < today:
                errs.append(f"{rid}: live row is past-dated ({last})")
        if st in LIVE + ("holding",):
            for k in ("cost", "value", "mid_time"):
                if tr.get(k) in (None, ""):
                    errs.append(f"{rid}: trade.{k} is blank")
        if st != CLOSED:
            errs.extend(_direction_errs(r, rid))
    errs.extend(_grade_key_errs(d))
    errs.extend(check_past_calls(d.get("past_calls") or []))
    b = d.get("benchmark") or {}
    for x in b.get("buys") or []:
        for k in ("date", "price", "shares", "source"):
            if x.get(k) in (None, ""):
                errs.append(f"benchmark buy {x.get('date')}: missing {k}")
    return errs


def _grade_key_errs(obj, path="") -> list[str]:
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if "grade" in k.lower():
                out.append(f"grading field {path}{k} (no grading: positions show market value; exits are expiry/target/stop)")
            out.extend(_grade_key_errs(v, f"{path}{k}."))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.extend(_grade_key_errs(v, f"{path}{i}."))
    return out


def _own_decision(c: dict) -> bool:
    """Only exemption from the evidence link: a call we chose not to place (exit reason 'not placed'
    and the public text says 'Not placed'). Nothing else is exempt."""
    return c.get("exit_reason") == "not placed" and "Not placed" in str(c.get("outcome_text") or "")


def check_past_calls(calls: list) -> list[str]:
    """Required fields and allowed exit reasons for every published past call."""
    errs = []
    for i, c in enumerate(calls):
        tag = f"past_calls[{i}] {c.get('ticker') or '?'}"
        for k in PAST_CALL_FIELDS:
            if k == "evidence_url" and _own_decision(c):
                continue  # our own decision not to place it: nothing external to link
            if not str(c.get(k) or "").strip():
                errs.append(f"{tag}: missing {k.replace('_', ' ')}")
        if c.get("exit_reason") and c["exit_reason"] not in EXIT_REASONS:
            errs.append(f"{tag}: exit reason {c['exit_reason']!r} not one of {EXIT_REASONS}")
        url = str(c.get("evidence_url") or "")
        if url and not re.match(r"https?://", url):
            errs.append(f"{tag}: evidence link must be a full http(s) URL")
    return errs


DIRECTIONS = ("Long", "Short", "Net long", "Net short")


def expected_direction(r: dict) -> str | None:
    """What the trade itself says: put debit spread -> Net short, call debit spread -> Net long, basket -> Long."""
    tr = r.get("trade") or {}
    legs = tr.get("legs") or []
    if r.get("kind") == "spread_set":
        dirs = {expected_direction({"trade": {"legs": s.get("legs") or []}}) for s in tr.get("spreads") or []}
        return dirs.pop() if len(dirs) == 1 else None
    if r.get("kind") == "basket" or (legs and isinstance(legs[0], dict) and "ticker" in legs[0]):
        return "Long"
    rights = {l.get("right") for l in legs}
    long_k = [l["strike"] for l in legs if (l.get("qty") or 0) > 0]
    short_k = [l["strike"] for l in legs if (l.get("qty") or 0) < 0]
    if rights == {"P"} and long_k and short_k and max(long_k) > max(short_k):
        return "Net short"
    if rights == {"C"} and long_k and short_k and min(long_k) < min(short_k):
        return "Net long"
    text = (tr.get("text") or "").lower()
    if "put spread" in text:
        return "Net short"
    if "call spread" in text:
        return "Net long"
    return None


def _direction_errs(r: dict, rid: str) -> list[str]:
    errs = []
    dr = r.get("direction")
    if dr not in DIRECTIONS:
        return [f"{rid}: direction {dr!r} not one of {DIRECTIONS}"]
    ex = (r.get("trade") or {}).get("expression") or {}
    if not (ex.get("type") or "").strip():
        errs.append(f"{rid}: no expression")
    want = expected_direction(r)
    if want is None:
        errs.append(f"{rid}: can't tell the direction from the trade")
    elif dr != want:
        errs.append(f"{rid}: direction {dr} doesn't match the trade ({want})")
    ty = (ex.get("type") or "").lower()
    if ("put" in ty and dr != "Net short") or ("call" in ty and dr != "Net long") or ("basket" in ty and dr != "Long"):
        errs.append(f"{rid}: direction {dr} doesn't match the expression {ex.get('type')!r}")
    lean = r.get("lean")
    if lean and lean != ("Negative" if "hort" in dr else "Positive"):
        errs.append(f"{rid}: direction {dr} doesn't match the lean {lean}")
    return errs


def check_computed(d: dict) -> list[str]:
    """After build: each open row's change equals value minus cost; totals equal the row sums."""
    errs = []
    rows = [r for r in d.get("rows") or [] if r.get("status") != CLOSED and (r.get("trade") or {}).get("cost") is not None]
    for r in rows:
        t = r["trade"]
        if t.get("change") is None or abs(t["change"] - (t["value"] - t["cost"])) >= 0.005:
            errs.append(f"{r.get('id')}: change {t.get('change')} isn't value minus cost")
    T = d.get("totals") or {}
    b = d.get("benchmark") or {}
    want = {"cost": sum(r["trade"]["cost"] for r in rows), "value": sum(r["trade"]["value"] for r in rows),
            "spy_value": sum(x["shares"] for x in b.get("buys") or []) * (b.get("spy_close_now") or 0)}
    for k, v in want.items():
        if T.get(k) is None or abs(T[k] - v) >= 0.01:
            errs.append(f"totals.{k} {T.get(k)} doesn't match the rows ({v:.2f})")
    if T.get("change") is None or abs(T["change"] - (T.get("value", 0) - T.get("cost", 0))) >= 0.005:
        errs.append("totals.change isn't value minus cost")
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
