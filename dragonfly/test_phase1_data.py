"""Offline tests for Phase 1 data plumbing: bars math + cache, chain fail-closed,
watchlist gate/selection. No network: fixtures and fakes only.

Run: python3 dragonfly/test_phase1_data.py
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = _TMP

from dragonfly import bars  # noqa: E402
from dragonfly import chains  # noqa: E402
from dragonfly.build_watchlist import (  # noqa: E402
    parse_constituents,
    parse_nasdaq_list,
    select_watchlist,
    spread_from_quote,
)

CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def bar(day, o, h, l, c, v):
    return {"date": day.isoformat() if isinstance(day, date) else day, "open": o, "high": h, "low": l, "close": c, "volume": v}


def series(n, start=date(2026, 8, 3), close=10.0, volume=100):
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(bar(d, close, close + 1, close - 1, close, volume))
        d += timedelta(days=1)
    return out


def raises(fn, exc_type, reason=None):
    try:
        fn()
    except exc_type as exc:
        return reason is None or getattr(exc, "reason", None) == reason
    return False


# ------------------------------------------------------------------ bars math

def test_bars_math():
    b = [
        bar("2026-09-14", 9, 10, 8, 9, 100),
        bar("2026-09-15", 10, 11, 9, 10, 100),
        bar("2026-09-16", 11, 12, 10, 11, 100),
        bar("2026-09-17", 10, 11, 7, 8, 100),
        bar("2026-09-18", 12, 14, 9, 13, 100),  # gap: TR uses prior close 8 -> 6
    ]
    check(bars.true_ranges(b) == [2, 2, 2, 4, 6], "true ranges incl. gap")
    check(abs(bars.atr(b, period=3) - 34 / 9) < 1e-12, "Wilder ATR(3) = 34/9")
    check(bars.atr(b[:3], period=3) is None, "ATR needs period+1 bars")

    flat = series(16)
    check(abs(bars.atr(flat) - 2.0) < 1e-12, "flat ATR14 = 2")

    ramp = [bar(f"d{i:02d}", 0, 0, 0, 10 + i, 1000) for i in range(20)]
    check(abs(bars.adv_dollars(ramp) - 19500.0) < 1e-9, "ADV$ = mean(close*vol)")
    check(bars.adv_dollars(ramp[:19]) is None, "ADV needs 20 bars")
    check(bars.adv_shares(ramp) == 1000, "ADV shares")

    rv = series(21, volume=100)
    rv[-1] = dict(rv[-1], volume=300)
    check(abs(bars.relative_volume(rv) - 3.0) < 1e-12, "rvol = last / prior-20 mean")
    check(bars.relative_volume(rv[:20]) is None, "rvol needs 21 bars")

    # Partial last bar: ADV/ATR exclude it, rvol is its pace vs completed ADV.
    part = series(21, volume=100)
    part[-1] = dict(part[-1], volume=50, close=99.0)
    m = bars.metrics(part, partial_last=True)
    check(m["completed_bars"] == 20 and m["adv20_shares"] == 100.0, "partial bar excluded from ADV")
    check(m["rvol20"] == 0.5 and m["rvol_partial"] is True, "partial rvol pace")
    check(m["last_price"] == 99.0, "last price from partial bar")
    check(m["provisional"] is True and m["source"] == "yahoo", "bars metrics stamped provisional")

    today = part[-1]["date"]
    ny = datetime.fromisoformat(today + "T11:00:00")
    check(bars.last_bar_partial(part, ny) is True, "today before 16:00 is partial")
    check(bars.last_bar_partial(part, datetime.fromisoformat(today + "T16:05:00")) is False, "after close not partial")
    check(bars.last_bar_partial(part, ny + timedelta(days=1)) is False, "older bar not partial")


# ------------------------------------------------------------------ bars cache

class FakeFetcher:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, ticker, start=None, period=None):
        self.calls.append({"ticker": ticker, "start": start, "period": period})
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_bars_cache():
    base = series(30)
    f = FakeFetcher([base])
    p = bars.refresh("tst", fetcher=f)
    check(f.calls[0]["period"] == "1y" and f.calls[0]["start"] is None, "first refresh is one full call")
    check(p["provisional"] is True and p["source"] == "yahoo" and p["last_fetch_mode"] == "full", "payload stamp")
    check(bars.cache_path("TST").is_file(), "cache written under state dir")
    check(str(bars.cache_path("TST")).startswith(_TMP), "cache honours DRAGONFLY_STATE_DIR")

    anchor = base[-2]
    last_partial_fixed = dict(base[-1], close=10.5, volume=150)
    new_day = bar(date.fromisoformat(base[-1]["date"]) + timedelta(days=3), 10, 11, 9, 10.7, 90)
    f2 = FakeFetcher([[anchor, last_partial_fixed, new_day]])
    p2 = bars.refresh("TST", fetcher=f2)
    check(len(f2.calls) == 1, "incremental refresh is one call")
    check(f2.calls[0]["start"] == date.fromisoformat(anchor["date"]), "incremental starts at 2nd-to-last cached bar")
    check(len(p2["bars"]) == 31 and p2["bars"][-2]["close"] == 10.5, "merge replaces partial and appends")
    check(p2["last_fetch_mode"] == "incremental", "incremental mode stamped")

    f3 = FakeFetcher([[]])
    p3 = bars.refresh("TST", fetcher=f3)
    check(len(p3["bars"]) == 31, "no new bars keeps cache")

    readjusted = [dict(p2["bars"][-2], close=p2["bars"][-2]["close"] * 0.5)]
    f4 = FakeFetcher([readjusted, series(40, close=5.0)])
    p4 = bars.refresh("TST", fetcher=f4)
    check(len(f4.calls) == 2 and f4.calls[1]["period"] == "1y", "re-adjusted history forces full refetch")
    check(len(p4["bars"]) == 40 and p4["last_fetch_mode"] == "full", "full refetch replaces cache")

    check(raises(lambda: bars.refresh("NOPE", fetcher=FakeFetcher([[]])), bars.BarsUnavailable, "empty_history"), "empty history fails closed")
    check(raises(lambda: bars.refresh("NOPE2", fetcher=FakeFetcher([RuntimeError("429")])), bars.BarsUnavailable, "fetch_failed"), "fetch error fails closed")
    check(not bars.cache_path("NOPE").exists(), "failed fetch writes no cache")

    m = bars.ticker_metrics("TST", fetcher=FakeFetcher([[]]), now_ny=datetime(2030, 1, 2, 12, 0))
    check(m["ticker"] == "TST" and m["atr14"] == 2.0 and m["adv20_dollars"] == 500.0, "metrics from cache")


# ------------------------------------------------------------------ chains

class FakeChain:
    def __init__(self, calls, puts, underlying=None):
        self.calls = calls
        self.puts = puts
        self.underlying = underlying or {}


class FakeTicker:
    def __init__(self, options=(), chains_by_exp=None, options_error=None, chain_error=None):
        self._options = options
        self._chains = chains_by_exp or {}
        self._options_error = options_error
        self._chain_error = chain_error
        self.chain_calls = []

    @property
    def options(self):
        if self._options_error:
            raise self._options_error
        return self._options

    def option_chain(self, exp):
        self.chain_calls.append(exp)
        if self._chain_error:
            raise self._chain_error
        return self._chains[exp]


def contract(strike, bid, ask, vol, oi, iv=0.4):
    return {
        "contractSymbol": f"TST261016C{int(strike * 1000):08d}",
        "strike": strike,
        "bid": bid,
        "ask": ask,
        "volume": vol,
        "openInterest": oi,
        "impliedVolatility": iv,
        "lastTradeDate": None,
        "change": 0.1,  # dropped
    }


def test_chains():
    exp = "2026-10-16"
    good = contract(100, 2.45, 2.55, 200.0, 500.0)
    nan_vol = contract(105, 1.0, 1.05, float("nan"), 300.0)
    fake = FakeTicker(options=(exp,), chains_by_exp={exp: FakeChain([good, nan_vol], [], {"regularMarketPrice": 101.2})})
    ch = chains.get_chain("tst", exp, ticker_factory=lambda s: fake)
    check(ch["source"] == "yahoo" and ch["provisional"] is True, "chain stamped yahoo provisional")
    check(ch["ticker"] == "TST" and ch["expiration"] == exp and ch["underlying_price"] == 101.2, "chain identity")
    check(fake.chain_calls == [exp], "exactly one option_chain call for one expiration")
    kept = ch["calls"][0]
    check(set(kept) == set(chains.KEEP) and "change" not in kept, "keeps only bid/ask/vol/OI/IV fields")
    check(kept["volume"] == 200 and kept["openInterest"] == 500 and kept["impliedVolatility"] == 0.4, "values kept")
    check(ch["calls"][1]["volume"] is None, "NaN volume stays None, never 0")
    check(chains.contract_passes_gates(kept) is True, "liquid contract passes option gates")
    check(chains.contract_passes_gates(ch["calls"][1]) is False, "missing volume fails gates")
    check(chains.contract_passes_gates(contract(1, 1.0, 1.2, 100, 500)) is False, "spread > 10% of mid fails")
    check(chains.contract_passes_gates(contract(1, 0, 0.1, 100, 500)) is False, "zero bid fails")
    check(chains.contract_passes_gates(contract(1, 2.45, 2.55, 100, 99)) is False, "OI < 100 fails")
    check(chains.contract_passes_gates(contract(1, 2.45, 2.55, 49, 500)) is False, "volume < 50 fails")

    def unavailable(fake_ticker, reason, expiration=exp):
        return raises(lambda: chains.get_chain("TST", expiration, ticker_factory=lambda s: fake_ticker), chains.ChainUnavailable, reason)

    check(unavailable(FakeTicker(options=()), "no_expirations"), "no expirations fails closed")
    check(unavailable(FakeTicker(options=None), "no_expirations"), "None expirations fails closed")
    check(unavailable(FakeTicker(options=("2026-10-23",)), "expiration_not_listed"), "unlisted expiration fails closed")
    check(unavailable(FakeTicker(options=(exp,), chains_by_exp={exp: FakeChain([], [])}), "empty_chain"), "empty chain fails closed")
    check(unavailable(FakeTicker(options=(exp,), chains_by_exp={exp: FakeChain(None, None)}), "empty_chain"), "None frames fail closed")
    check(unavailable(FakeTicker(options_error=RuntimeError("429")), "fetch_failed"), "expiration fetch error fails closed")
    check(unavailable(FakeTicker(options=(exp,), chain_error=RuntimeError("boom")), "fetch_failed"), "chain fetch error fails closed")

    exps = ["2026-09-25", "2026-10-02", "2026-10-09", "2026-12-18"]
    check(chains.pick_expiration(exps, date(2026, 9, 25)) == "2026-10-02", "first expiration >= 7 days out")
    check(raises(lambda: chains.pick_expiration(["2026-09-26"], date(2026, 9, 25)), chains.ChainUnavailable, "no_expiration_in_range"), "no expiration in range fails closed")


# ------------------------------------------------------------------ watchlist

def test_watchlist_selection():
    rows = [
        {"ticker": "AAA", "price": 50.0, "adv20_dollars": 100e6},
        {"ticker": "BBB", "price": 50.0, "adv20_dollars": 90e6},
        {"ticker": "CCC", "price": 50.0, "adv20_dollars": 80e6},
        {"ticker": "DDD", "price": 50.0, "adv20_dollars": 70e6},
        {"ticker": "EEE", "price": 50.0, "adv20_dollars": 60e6},
        {"ticker": "FFF", "price": 9.99, "adv20_dollars": 500e6},
        {"ticker": "GGG", "price": 50.0, "adv20_dollars": 24_999_999.0},
        {"ticker": "HHH", "price": 50.0, "adv20_dollars": None},
        {"ticker": "III", "price": 50.0, "adv20_dollars": 75e6},
    ]
    quotes = {
        "AAA": (49.99, 50.01),  # spread 0.02 <= 0.075 limit
        "CCC": (49.90, 50.00),  # spread 0.10 > 0.075
        "DDD": (50.00, 50.05),
        "EEE": (50.00, 50.01),
        "III": (0.0, 50.02),  # zero bid: unusable
    }
    called = []

    def quote_fn(t):
        called.append(t)
        if t == "BBB":
            raise RuntimeError("quote fetch failed")
        return quotes[t]

    res = select_watchlist(rows, quote_fn, cap=2, batch=1, workers=1)
    names = [n["ticker"] for n in res["names"]]
    ex = res["excluded"]
    check(names == ["AAA", "DDD"], "admits only spread-checked passes, ADV rank order")
    check(ex["BBB"] == "spread_unavailable", "failed bid/ask fetch is excluded")
    check(ex["CCC"] == "spread_too_wide", "wide spread excluded")
    check(ex["III"] == "spread_unavailable", "zero-bid quote excluded")
    check(ex["EEE"] == "not_spread_checked", "never spread-checked name is excluded, not admitted")
    check("EEE" not in called, "unchecked name really was not quoted")
    check(ex["FFF"] == "price_below_minimum" and ex["GGG"] == "adv_below_minimum", "price / ADV gates")
    check(ex["HHH"] == "adv_below_minimum", "missing ADV fails closed")
    check(called == ["AAA", "BBB", "CCC", "III", "DDD"], "spread checks run in ADV rank order")
    check(res["funnel"] == {"candidates": 9, "passed_price_adv": 6, "spread_checked": 5, "admitted": 2}, "funnel counts")
    check(len(names) + len(ex) == len(rows), "every candidate is admitted or has an exclusion reason")
    check(res["names"][0]["rank"] == 1 and res["names"][0]["spread"] == 0.02, "row carries measured spread")

    res2 = select_watchlist(rows, quote_fn, cap=2, batch=25, workers=3)
    check([n["ticker"] for n in res2["names"]] == ["AAA", "DDD"], "batching does not change admission")
    check(res2["excluded"]["EEE"] == "beyond_cap", "checked after cap filled is excluded")

    res3 = select_watchlist(rows, lambda t: (_ for _ in ()).throw(RuntimeError("down")), cap=200, batch=4, workers=2)
    check(res3["names"] == [], "provider down admits nobody")
    check(all(res3["excluded"][t] == "spread_unavailable" for t in ("AAA", "BBB", "CCC", "DDD", "EEE", "III")), "all unquoted excluded")

    check(spread_from_quote(None) == (None, None), "missing quote unusable")
    check(spread_from_quote((None, 10)) == (None, None), "missing bid unusable")
    check(spread_from_quote((10.2, 10.1)) == (None, None), "crossed quote unusable")


def test_constituent_parsers():
    html = "<table class='wikitable sortable' id='constituents'><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th></tr>"
    html += "".join(f"<tr><td>T{i}</td><td>Co {i}</td><td>Energy</td></tr>" for i in range(60))
    html += "<tr><td>BRK.B</td><td>Berkshire</td><td>Financials</td></tr></table>"
    rows = parse_constituents(html)
    check(len(rows) == 61 and rows[-1] == {"ticker": "BRK-B", "name": "Berkshire", "sector": "Financials"}, "S&P table parse + dot->dash")
    check(raises(lambda: parse_constituents("<table class='wikitable'><tr><th>Year</th></tr></table>"), ValueError), "missing table raises")
    payload = {"data": {"data": {"rows": [{"symbol": f"N{i}", "companyName": "x", "sector": ""} for i in range(100)]}}}
    check(len(parse_nasdaq_list(payload)) == 100, "nasdaq list parse")
    check(raises(lambda: parse_nasdaq_list({"data": {"data": {"rows": []}}}), ValueError), "short nasdaq list raises")


def main():
    test_bars_math()
    test_bars_cache()
    test_chains()
    test_watchlist_selection()
    test_constituent_parsers()
    print(f"dragonfly phase1 data: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
