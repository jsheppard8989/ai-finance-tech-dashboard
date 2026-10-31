#!/usr/bin/env python3
"""After-close price pull for the Trap Map (free sources only; read-only; never places orders).

For each open spread row: leg bid/ask from Cboe's free delayed-quotes JSON (cdn.cboe.com), falling
back to Yahoo Finance's public options endpoint. Every leg is marked at the bottom third of its
bid-ask spread, bid + (ask - bid) / 3 (Jared, Oct 31: used for every open, quote and close), and the
spread's per-share mark is sum(qty x leg mark). Writes trade.mark, trade.value and trade.mid_time.
Basket legs and the SPY benchmark use Yahoo Finance daily closes.

Unrealistic quotes are not used: no bid, no ask, bid > ask, zero volume and zero open interest, a quote
older than STALE_DAYS, or a bid-ask spread wider than WIDE_PCT of the leg's midpoint. Such a row keeps
its last good mark/value/mid_time and lists the problem in trade.quote_flags (cleared on the next good
quote). On any fetch failure a row also keeps its last values and the run prints a warning.

No grading: option spreads are held to expiry (the result is the spread's value at expiry) and the
basket is held until its fixed stop. After the close on an option's expiry day the row is closed at that
day's value (exit: expiry); a basket whose index closes under its stop is closed (exit: stop).

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
    return {o["option"]: _q(o.get("bid"), o.get("ask"), o.get("volume"), o.get("open_interest"), ts)
            for o in j["data"]["options"]}, ts


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
        lt = c.get("lastTradeDate")
        qt = datetime.fromtimestamp(lt, timezone.utc) if isinstance(lt, (int, float)) else None
        out[c["contractSymbol"]] = _q(c.get("bid"), c.get("ask"), c.get("volume"), c.get("openInterest"), qt)
    return out, datetime.now(timezone.utc)


STALE_DAYS = 3      # a leg quote older than this (vs the run time) is stale
WIDE_PCT = 0.50     # a leg whose ask - bid is wider than 50% of its midpoint is too wide to use


def _q(bid, ask, volume=None, oi=None, ts=None):
    return {"bid": bid, "ask": ask, "volume": volume, "oi": oi, "ts": ts}


def bottom_third(bid: float, ask: float) -> float:
    """Jared's price rule for every open, quote and close: bid + (ask - bid) / 3."""
    return bid + (ask - bid) / 3


def quote_problems(sym: str, q: dict, now: datetime) -> list[str]:
    bid, ask = q.get("bid"), q.get("ask")
    if bid is None or bid <= 0:
        return [f"{sym}: no bid ({bid}/{ask})"]
    if ask is None or ask <= 0:
        return [f"{sym}: no ask ({bid}/{ask})"]
    if bid > ask:
        return [f"{sym}: bid above ask ({bid}/{ask})"]
    out = []
    if not q.get("volume") and not q.get("oi") and (q.get("volume") is not None or q.get("oi") is not None):
        out.append(f"{sym}: zero volume and zero open interest")
    mid = (bid + ask) / 2
    if (ask - bid) > WIDE_PCT * mid:
        out.append(f"{sym}: spread {bid}/{ask} is wider than {int(WIDE_PCT * 100)}% of mid")
    ts = q.get("ts")
    if ts is not None and (now - ts).total_seconds() > STALE_DAYS * 86400:
        out.append(f"{sym}: quote is stale ({ts.astimezone(CT):%b %d %H:%M} CT)")
    return out


class UnrealisticQuote(Exception):
    def __init__(self, flags):
        super().__init__("; ".join(flags))
        self.flags = flags


def spread_mark(t, now=None):
    """Per-share spread mark at the bottom third of each leg's bid-ask. Raises UnrealisticQuote with the
    flags if the first source that answers has a leg that fails quote_problems()."""
    now = now or datetime.now(timezone.utc)
    legs = [(occ(t["underlying"], t["expiry"], l["right"], l["strike"]), l["qty"]) for l in t["legs"]]
    errs = []
    for src in (lambda: cboe_quotes(t["underlying"]), lambda: yahoo_quotes(t["underlying"], t["expiry"])):
        try:
            q, ts = src()
            flags = [f for sym, _ in legs for f in quote_problems(sym, q[sym], now)]
            if flags:
                raise UnrealisticQuote(flags)
            mark = sum(qty * bottom_third(q[sym]["bid"], q[sym]["ask"]) for sym, qty in legs)
            return round(mark, 4), ts
        except UnrealisticQuote:
            raise  # a real quote that looks wrong: don't shop for a better-looking one
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
    warn = []
    for r in d["rows"]:
        t = r.get("trade") or {}
        if r.get("status") == "closed":
            continue
        try:
            if r.get("kind") == "spread":
                try:
                    mark, ts = spread_mark(t, now)
                except UnrealisticQuote as uq:
                    t["quote_flags"] = uq.flags
                    warn.append(f"{r['id']}: unrealistic quote, kept last good price ({t.get('mid_time')}): {uq}")
                    continue
                t.pop("mid", None)
                t["mark"], t["value"] = mark, round(mark * 100 * t["contracts"], 2)
                t["mid_time"] = ts.astimezone(CT).isoformat(timespec="minutes")
                t.pop("quote_flags", None)
            elif r.get("kind") == "spread_set":
                marks, ts, flags = [], None, []
                for s in t["spreads"]:
                    try:
                        m, ts = spread_mark(s, now)
                        marks.append(m)
                    except UnrealisticQuote as uq:
                        flags += uq.flags
                if flags:
                    t["quote_flags"] = flags
                    warn.append(f"{r['id']}: unrealistic quote, kept last good price ({t.get('mid_time')}): {flags}")
                else:
                    for s, m in zip(t["spreads"], marks):
                        s["mark"], s["value"] = m, round(m * 100 * s["contracts"], 2)
                    t["value"] = round(sum(s["value"] for s in t["spreads"]), 2)
                    t["mid_time"] = ts.astimezone(CT).isoformat(timespec="minutes")
                    t.pop("quote_flags", None)
                il = (t.get("stop_rule") or {}).get("index_legs")
                if il:
                    t["index_now"] = equal_weight_index([(l["base"], yahoo_close(l["ticker"])[0]) for l in il])
            elif r.get("kind") == "basket":
                total, ts = 0.0, None
                for l in t["legs"]:
                    c, ts = yahoo_close(l["ticker"])
                    l["close"], l["value"] = c, round(l["shares"] * c, 2)
                    total += l["value"]
                t["value"], t["mid_time"] = round(total, 2), ts.isoformat(timespec="minutes")
                t["index_now"] = round(100 * total / t["cost"], 1)
        except Exception as e:
            warn.append(f"{r['id']}: kept last price/time ({t.get('mid_time')}): {e}")
            continue
        sr = t.get("stop_rule") or {}
        if r["status"] in ("live", "new") and sr.get("index_below") is not None and t.get("index_now") is not None \
                and t["index_now"] < sr["index_below"]:
            close_row(r, "stop", now)
        elif r["status"] in ("live", "new") and t.get("expiry") == now.date().isoformat() and now.hour >= 15:
            close_row(r, "expiry", now)
        elif r["status"] == "holding" and (t.get("stop_rule") or {}).get("index_below") is not None \
                and t.get("index_now") is not None and t["index_now"] < t["stop_rule"]["index_below"]:
            close_row(r, "stop", now)
    try:
        c, ts = yahoo_close("SPY")
        d["benchmark"]["spy_close_now"], d["benchmark"]["spy_close_time"] = c, ts.isoformat(timespec="minutes")
    except Exception as e:
        warn.append(f"SPY: kept last close: {e}")
    d["as_of"] = now.isoformat(timespec="minutes")
    return warn


def equal_weight_index(pairs) -> float:
    """Equal-weight index, 100 at the base closes: 100 x mean(close / base)."""
    return round(100 * sum(c / b for b, c in pairs) / len(pairs), 1)


def close_row(r, reason, now):
    """Exit a position (expiry, target or stop) at its current value. No grade: the result is the money."""
    t = r["trade"]
    r["status"] = "closed"
    r["exit"] = {"reason": reason, "date": now.date().isoformat(), "value": t["value"],
                 "result": round(t["value"] - t["cost"], 2)}
    word = {"expiry": "at expiry", "stop": "at its stop", "target": "at its target"}[reason]
    sign = "+" if r["exit"]["result"] >= 0 else "\u2212"
    r.setdefault("history", []).append({"at": now.isoformat(timespec="minutes"), "text":
        f"{r['company']}: closed {word} on {now:%b} {now.day}, worth ${t['value']:,.2f} against ${t['cost']:,.2f} "
        f"allocated ({sign}${abs(r['exit']['result']):,.2f})."})


def main():
    d = json.loads(DATA.read_text(encoding="utf-8"))
    warn = pull(d)
    for w in warn:
        print("WARN", w)
    for r in d["rows"]:
        print(r["id"], r["status"], r["trade"].get("mark", r["trade"].get("mid")), r["trade"].get("value"), r["trade"].get("mid_time"))
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
