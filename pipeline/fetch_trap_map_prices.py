#!/usr/bin/env python3
"""After-close price pull for the Trap Map (free sources only; read-only; never places orders).

For each open spread row: leg bid/ask from Cboe's free delayed-quotes JSON (cdn.cboe.com), falling
back to Yahoo Finance's public options endpoint; writes trade.mid (per-share spread mid), trade.value
and trade.mid_time. Basket legs and the SPY benchmark use Yahoo Finance daily closes.
On any failure a row keeps its last mid/value/mid_time (never blank) and the run prints a warning.

Grading (spec): on a row's grade date, after the close, the row is graded Right if value > cost,
Wrong otherwise. A Holding row is graded only when its index stop is hit (Right if exit > cost).
The HIMS-subscriber event stop is applied by hand.

Then rebuilds site/trap-map.html + homepage strip via build_trap_map.py.
Usage: python3 pipeline/fetch_trap_map_prices.py [--dry-run]
"""
from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date, datetime, timezone
from http.cookiejar import CookieJar
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_trap_map  # noqa: E402

CT = ZoneInfo("America/Chicago")
UA = {"User-Agent": "Mozilla/5.0 (trap-map price pull; read-only)"}
DATA = build_trap_map.DATA


def _get(url, opener=None, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with (opener.open(req, timeout=timeout) if opener else urllib.request.urlopen(req, timeout=timeout)) as r:
        return json.loads(r.read().decode())


def occ(underlying, expiry, right, strike):
    d = date.fromisoformat(expiry)
    return f"{underlying}{d:%y%m%d}{right}{int(round(strike * 1000)):08d}"


def cboe_quotes(underlying):
    j = _get(f"https://cdn.cboe.com/api/global/delayed_quotes/options/{underlying}.json")
    ts = datetime.strptime(j["timestamp"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return {o["option"]: (o.get("bid"), o.get("ask")) for o in j["data"]["options"]}, ts


def yahoo_quotes(underlying, expiry):
    jar = CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        op.open(urllib.request.Request("https://fc.yahoo.com", headers=UA), timeout=15)
    except Exception:
        pass
    crumb = op.open(urllib.request.Request("https://query2.finance.yahoo.com/v1/test/getcrumb", headers=UA), timeout=15).read().decode()
    ep = int(datetime(*date.fromisoformat(expiry).timetuple()[:3], tzinfo=timezone.utc).timestamp())
    j = _get(f"https://query2.finance.yahoo.com/v7/finance/options/{underlying}?date={ep}&crumb={crumb}", op)
    o = j["optionChain"]["result"][0]["options"][0]
    out = {}
    for c in o.get("calls", []) + o.get("puts", []):
        out[c["contractSymbol"]] = (c.get("bid"), c.get("ask"))
    return out, datetime.now(timezone.utc)


def spread_mid(t):
    legs = [(occ(t["underlying"], t["expiry"], l["right"], l["strike"]), l["qty"]) for l in t["legs"]]
    errs = []
    for src in (lambda: cboe_quotes(t["underlying"]), lambda: yahoo_quotes(t["underlying"], t["expiry"])):
        try:
            q, ts = src()
            mid = 0.0
            for sym, qty in legs:
                bid, ask = q[sym]
                if not bid and not ask or bid is None or ask is None or ask <= 0 or bid > ask:
                    raise ValueError(f"no usable quote for {sym}: {bid}/{ask}")
                mid += qty * (bid + ask) / 2
            return round(mid, 4), ts
        except Exception as e:  # try next source
            errs.append(repr(e))
    raise RuntimeError("; ".join(errs))


def yahoo_close(ticker):
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=5d&interval=1d")["chart"]["result"][0]
    now = datetime.now(CT)
    pairs = [(t, c) for t, c in zip(j["timestamp"], j["indicators"]["quote"][0]["close"]) if c is not None
             and (now.hour >= 15 or datetime.fromtimestamp(t, CT).date() < now.date())]  # no intraday "closes"
    t, c = pairs[-1]
    day = datetime.fromtimestamp(t, CT).date()
    return round(c, 2), datetime(day.year, day.month, day.day, 15, 0, tzinfo=CT)


def pull(d, now=None):
    now = now or datetime.now(CT)
    today = now.date()
    warn = []
    for r in d["rows"]:
        t = r.get("trade") or {}
        if r.get("status") == "graded":
            continue
        try:
            if r.get("kind") == "spread":
                mid, ts = spread_mid(t)
                t["mid"], t["value"] = mid, round(mid * 100 * t["contracts"], 2)
                t["mid_time"] = ts.astimezone(CT).isoformat(timespec="minutes")
            elif r.get("kind") == "basket":
                total, ts = 0.0, None
                for l in t["legs"]:
                    c, ts = yahoo_close(l["ticker"])
                    l["close"], l["value"] = c, round(l["shares"] * c, 2)
                    total += l["value"]
                t["value"], t["mid_time"] = round(total, 2), ts.isoformat(timespec="minutes")
                t["index_now"] = round(100 * total / t["cost"], 1)
        except Exception as e:
            warn.append(f"{r['id']}: kept last mid/time ({t.get('mid_time')}): {e}")
            continue
        # Grade on the grade date's close (spreads) or a hit index stop (Holding).
        if r["status"] in ("live", "new") and t.get("grade_date") == today.isoformat() and now.hour >= 15:
            _grade(r, today)
        elif r["status"] == "holding" and (t.get("stop_rule") or {}).get("index_below") is not None \
                and t.get("index_now") is not None and t["index_now"] < t["stop_rule"]["index_below"]:
            _grade(r, today)
    try:
        c, ts = yahoo_close("SPY")
        d["benchmark"]["spy_close_now"], d["benchmark"]["spy_close_time"] = c, ts.isoformat(timespec="minutes")
    except Exception as e:
        warn.append(f"SPY: kept last close: {e}")
    d["as_of"] = now.isoformat(timespec="minutes")
    return warn


def _grade(r, today):
    t = r["trade"]
    r["status"], r["graded_on"] = "graded", today.isoformat()
    r["outcome"] = "Right" if t["value"] > t["cost"] else "Wrong"
    r["grade_detail"] = f"Worth ${t['value']:,.2f} against ${t['cost']:,.2f} paid at the {today:%b} {today.day} close."
    r.setdefault("history", []).append({"at": datetime.now(CT).isoformat(timespec="minutes"),
                                        "text": f"{r['company']}: graded {r['outcome']}. {r['grade_detail']}"})


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    warn = pull(d)
    for w in warn:
        print("WARN", w)
    for r in d["rows"]:
        print(r["id"], r["status"], r["trade"].get("mid"), r["trade"].get("value"), r["trade"].get("mid_time"))
    print("SPY", d["benchmark"]["spy_close_now"], d["benchmark"]["spy_close_time"])
    if "--dry-run" in sys.argv:
        return 0
    errs = build_trap_map.trap_map_check.check(d)
    if errs:
        print("Trap Map check failed; nothing written:\n  " + "\n  ".join(errs))
        return 1
    DATA.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print("Wrote:", [str(p) for p in build_trap_map.build()])
    return 0


if __name__ == "__main__":
    sys.exit(main())
