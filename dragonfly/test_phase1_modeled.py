"""Offline tests for the paper quote model (modeled $0.05 spread, PAPER ONLY):
risk_math.resolve_quote vectors and select_watchlist(spread_mode="modeled").
No network: fakes only.

Run: python3 dragonfly/test_phase1_modeled.py
"""

from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = _TMP
os.environ["DRAGONFLY_PIPELINE_LOCK"] = os.path.join(_TMP, "no-such.lock")
os.environ["DRAGONFLY_ALLOW_DAEMON_WINDOW"] = "1"

from dragonfly import guards  # noqa: E402
from dragonfly.build_watchlist import _quote_parts, select_watchlist, yahoo_quote_full  # noqa: E402
from dragonfly.risk_math import (  # noqa: E402
    MODELED_SPREAD,
    paper_buy_fill,
    paper_entry_fill,
    paper_sell_fill,
    resolve_quote,
    structural_blocks,
)

CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


D = Decimal


def test_resolve_quote() -> None:
    # yahoo-pass: real quote used as-is
    r = resolve_quote(100.00, 100.10, 100.05)
    check(r["usable"] and r["spread_source"] == "yahoo", "yahoo pass source")
    check(r["bid"] == D("100.0") and r["ask"] == D("100.1"), "yahoo pass keeps real bid/ask")
    check(r["mid"] == D("100.05") and r["mid_source"] == "quote_mid", "yahoo pass mid")
    check(r["fallback_reason"] is None and r["provisional"] is True, "yahoo pass still provisional (yfinance)")
    r = resolve_quote(20.00, 20.05, None)  # $0.05 floor passes even without last
    check(r["spread_source"] == "yahoo", "yahoo pass at the $0.05 floor")

    # crossed -> modeled around (bid+ask)/2
    r = resolve_quote(150.20, 150.00, 150.12)
    check(r["usable"] and r["spread_source"] == "modeled_mid_0.05", "crossed -> modeled_mid")
    check(r["mid"] == D("150.1") and r["mid_source"] == "quote_mid", "crossed mid")
    check(r["bid"] == D("150.075") and r["ask"] == D("150.125"), "crossed modeled bid/ask = mid -/+ 0.025")
    check(r["spread"] == MODELED_SPREAD and r["provisional"] is True, "crossed modeled spread, provisional")
    check(r["fallback_reason"] == "quote_crossed", "crossed reason")

    # zero bid/ask -> no usable mid -> last trade
    r = resolve_quote(0, 0, 231.40)
    check(r["usable"] and r["spread_source"] == "modeled_last_0.05", "zero -> modeled_last")
    check(r["mid"] == D("231.4") and r["mid_source"] == "last_trade", "zero uses last trade")
    check(r["bid"] == D("231.375") and r["ask"] == D("231.425"), "zero modeled bid/ask")
    check(r["fallback_reason"] == "quote_missing_or_zero", "zero reason")
    r = resolve_quote(231.30, 0, 231.40)  # one side zero
    check(r["spread_source"] == "modeled_last_0.05", "one side zero -> modeled_last")

    # missing -> last trade
    r = resolve_quote(None, None, 50.00)
    check(r["usable"] and r["spread_source"] == "modeled_last_0.05", "missing -> modeled_last")
    check(r["mid"] == D("50") and r["mid_source"] == "last_trade", "missing uses last trade")
    r = resolve_quote(float("nan"), 50.01, 50.00)
    check(r["spread_source"] == "modeled_last_0.05", "NaN side counts as missing")

    # gate fail -> modeled around (bid+ask)/2 (mid close to last)
    r = resolve_quote(99.80, 100.20, 100.00)  # 0.40 > 0.15 limit
    check(r["usable"] and r["spread_source"] == "modeled_mid_0.05", "gate fail -> modeled_mid")
    check(r["mid"] == D("100.0") and r["fallback_reason"] == "quote_fails_spread_gate", "gate fail mid")
    check(r["ask"] - r["bid"] == D("0.050"), "gate fail modeled spread is $0.05")
    check(r["yahoo_bid"] == 99.80 and r["yahoo_ask"] == 100.20 and r["last_trade"] == 100.00, "raw quote kept")

    # mid-vs-last sanity swap: mid more than the gate width from last -> last
    r = resolve_quote(180.00, 190.00, 184.00)  # mid 185.00, |1.00| > 0.276
    check(r["spread_source"] == "modeled_last_0.05", "sanity swap -> modeled_last")
    check(r["mid"] == D("184") and r["mid_source"] == "last_trade", "sanity swap uses last")
    check(r["fallback_reason"] == "quote_fails_spread_gate+mid_far_from_last", "sanity swap reason")
    r = resolve_quote(199.00, 201.00, 200.29)  # mid 200.00, |0.29| < 0.30 -> keep mid
    check(r["spread_source"] == "modeled_mid_0.05" and r["mid"] == D("200.0"), "within gate width keeps mid")
    r = resolve_quote(199.00, 201.00, 200.31)  # |0.31| > 0.30465 -> last
    check(r["spread_source"] == "modeled_last_0.05", "just outside gate width swaps")
    r = resolve_quote(20.20, 20.00, 20.06)  # crossed, mid 20.10, |0.04| <= $0.05 floor
    check(r["spread_source"] == "modeled_mid_0.05", "low price: $0.05 floor is the sanity width")
    r = resolve_quote(20.30, 20.00, 20.06)  # crossed, mid 20.15, |0.09| > 0.05
    check(r["spread_source"] == "modeled_last_0.05", "low price sanity swap")

    # mid usable, no last trade: admitted but unverified (only exclude when both missing)
    r = resolve_quote(99.80, 100.20, None)
    check(r["usable"] and r["spread_source"] == "modeled_mid_0.05", "no last keeps modeled mid")
    check(r["mid_source"] == "quote_mid_unverified", "no last -> mid unverified")

    # no usable mid and no usable last -> excluded, fail closed
    for q in ((None, None, None), (0, 0, 0), (0, 101.0, None), (None, None, float("nan")), (-1, -1, -5)):
        r = resolve_quote(*q)
        check(r["usable"] is False and r["reason"] == "no_usable_mid_or_last", f"no mid, no last {q}")
    check(resolve_quote("junk", None, None)["usable"] is False, "unparseable -> excluded")


def test_fills() -> None:
    check(paper_buy_fill(D("50.00")) == D("50.03"), "buy mid + 0.025, ceil")
    check(paper_sell_fill(D("50.00")) == D("49.97"), "sell mid - 0.025, floor")
    check(paper_buy_fill(D("50.005")) == D("50.03"), "buy exact cent")
    check(paper_sell_fill(D("50.005")) == D("49.98"), "sell exact cent")
    e = paper_entry_fill(D("200.00"))
    check(e["fill"] == D("200.03") and e["max_fill"] == D("200.30") and e["acceptable"], "entry at trigger")
    e = paper_entry_fill(D("200.00"), mid=D("200.28"))
    check(e["fill"] == D("200.31") and not e["acceptable"], "mid through trigger band invalidates")
    e = paper_entry_fill(D("16.67"))
    check(e["acceptable"], "16.67 is the lowest trigger where an at-trigger paper entry fits max_fill")
    check(not paper_entry_fill(D("16.66"))["acceptable"], "under 16.67 at-trigger paper entry exceeds max_fill")


def test_governor() -> None:
    base = dict(
        setup="catalyst_breakout",
        instrument="stock",
        direction="long",
        catalyst_quality="primary",
        earnings_in_window=False,
        invalidation=("stop_hit", "level_lost", "time_stop", "catalyst_retracted"),
        fields_complete=True,
        sector_already_open=False,
        setup_open_count=0,
        open_positions=0,
        risk_mode="normal",
        extension_atr=Decimal("0.4"),
        stop_distance_atr=Decimal("0.94"),
    )
    for source in ("modeled_mid_0.05", "modeled_last_0.05"):
        live = structural_blocks(**base, book="live", provisional_data=False, spread_source=source)
        check("provisional_source_live" in live, f"live rejects {source}")
        paper = structural_blocks(**base, book="paper", provisional_data=True, spread_source=source)
        check(paper == [], f"paper passes {source}")
    check(structural_blocks(**base, book="live", provisional_data=False, spread_source="yahoo") == [], "yahoo alone ok")


def _row(t, adv, price=100.0):
    return {"ticker": t, "price": price, "adv20_dollars": adv, "sector": "Tech"}


def test_selection() -> None:
    quotes = {
        "AAA": {"bid": 100.00, "ask": 100.05, "last": 100.02},  # yahoo pass
        "BBB": {"bid": 101.00, "ask": 100.00, "last": 100.50},  # crossed -> modeled_mid
        "CCC": {"bid": 0, "ask": 0, "last": 55.00},  # zero -> modeled_last
        "DDD": None,  # fetch failed -> excluded
        "EEE": {"bid": 99.00, "ask": 101.00, "last": 100.10},  # gate fail -> modeled_mid
        "FFF": {"bid": 180.0, "ask": 190.0, "last": 184.0},  # sanity swap -> modeled_last
        "GGG": {"bid": None, "ask": None, "last": None},  # nothing -> excluded
        "HHH": {"bid": 9.00, "ask": 9.20, "last": 9.10},  # resolved mid < $10 -> price gate
        "III": (100.0, 100.05),  # tuple quote (exact-mode fake shape) still works
        "JJJ": {"bid": 50.0, "ask": 50.02, "last": 50.01},
        "KKK": {"bid": 60.0, "ask": 60.02, "last": 60.01},
    }
    rows = [
        _row("AAA", 9e9),
        _row("BBB", 8e9),
        _row("CCC", 7e9),
        _row("DDD", 6e9),
        _row("EEE", 5e9),
        _row("FFF", 4e9),
        _row("GGG", 3.5e9),
        _row("HHH", 3.2e9, price=10.5),
        _row("III", 3e9),
        _row("JJJ", 2e9),
        _row("KKK", 1e9),
        _row("THIN", 1e6),  # ADV gate stays exact
        _row("CHEAP", 9e9, price=5.0),  # price gate stays exact
        _row("NOADV", None),
    ]
    calls = []

    def qf(t):
        calls.append(t)
        return quotes[t]

    res = select_watchlist(rows, qf, cap=7, batch=3, workers=2, spread_mode="modeled")
    names = [n["ticker"] for n in res["names"]]
    ex = res["excluded"]
    check(names == ["AAA", "BBB", "CCC", "EEE", "FFF", "III", "JJJ"], f"admitted in ADV order {names}")
    check([n["rank"] for n in res["names"]] == list(range(1, 8)), "ranks")
    by = {n["ticker"]: n for n in res["names"]}
    check(by["AAA"]["spread_source"] == "yahoo" and by["AAA"]["bid"] == 100.0, "AAA real quote")
    check(by["BBB"]["spread_source"] == "modeled_mid_0.05" and by["BBB"]["mid"] == 100.5, "BBB crossed")
    check(by["CCC"]["spread_source"] == "modeled_last_0.05" and by["CCC"]["mid_source"] == "last_trade", "CCC zero")
    check(by["EEE"]["spread_source"] == "modeled_mid_0.05" and abs(by["EEE"]["spread"] - 0.05) < 1e-9, "EEE gate fail")
    check(by["FFF"]["mid"] == 184.0 and by["FFF"]["spread_source"] == "modeled_last_0.05", "FFF sanity swap")
    check(by["III"]["spread_source"] == "yahoo", "tuple quote")
    check(all(n["provisional"] is True for n in res["names"]), "all admitted provisional")
    check(ex["DDD"] == "no_usable_mid_or_last", "fetch fail excluded, fail closed")
    check(ex["GGG"] == "no_usable_mid_or_last", "no mid no last excluded")
    check(ex["HHH"] == "price_below_minimum", "price gate on resolved mid stays exact")
    check(ex["KKK"] == "beyond_cap", "ranked below cap -> beyond_cap")
    check(ex["THIN"] == "adv_below_minimum", "ADV gate exact")
    check(ex["CHEAP"] == "price_below_minimum", "price gate exact")
    check(ex["NOADV"] == "adv_unavailable" or ex["NOADV"].startswith("adv"), f"no ADV excluded {ex['NOADV']}")
    check("not_spread_checked" not in ex.values() and "spread_unavailable" not in ex.values(), "no junk-quote exclusions")
    check("THIN" not in calls and "CHEAP" not in calls, "gated names never quoted")
    calls.clear()
    one = select_watchlist(rows, qf, cap=7, batch=1, workers=1, spread_mode="modeled")
    check([n["ticker"] for n in one["names"]] == names, "batch size does not change the list")
    check("KKK" not in calls, "quoting stops once the cap fills")
    f = res["funnel"]
    check(f["admitted"] == 7 and f["passed_price_adv"] == 11, f"funnel {f}")
    check(f["admitted_by_spread_source"] == {"modeled_last_0.05": 2, "modeled_mid_0.05": 2, "yahoo": 3}, "by source")
    check(f["mid_from_last_trade"] == 2, "last-trade count")
    check(set(res["fallbacks"]) == {"BBB", "CCC", "EEE", "FFF"}, "fallback reasons recorded")

    # exact mode unchanged on the same fixture (tuple-only quote fn)
    def qf_exact(t):
        q = quotes[t]
        b, a, _ = _quote_parts(q)
        return (b, a)

    exact = select_watchlist(rows, qf_exact, cap=7, batch=3, workers=2)
    check([n["ticker"] for n in exact["names"]] == ["AAA", "III", "JJJ", "KKK"], "exact mode strict")
    check(exact["excluded"]["BBB"] == "spread_unavailable", "exact mode still strict on crossed")

    # guard stop aborts modeled builds too
    def blocked(t):
        raise guards.GuardBlocked("pipeline_lock_held")

    try:
        select_watchlist(rows, blocked, cap=7, spread_mode="modeled")
    except guards.GuardBlocked:
        check(True, "guard stop propagates in modeled mode")
    else:
        check(False, "guard stop propagates in modeled mode")
    try:
        select_watchlist(rows, qf, spread_mode="bogus")
    except ValueError:
        check(True, "unknown spread_mode rejected")
    else:
        check(False, "unknown spread_mode rejected")


def test_full_quote_fetcher_guarded() -> None:
    lock = Path(os.environ["DRAGONFLY_PIPELINE_LOCK"])
    lock.write_text(str(os.getpid()))
    try:
        for fn, label in (
            (lambda: yahoo_quote_full("AAPL"), "full quote fetcher guarded"),
            (
                lambda: select_watchlist(
                    [{"ticker": "AAA", "price": 50.0, "adv20_dollars": 1e8}],
                    yahoo_quote_full,
                    cap=5,
                    batch=1,
                    workers=1,
                    spread_mode="modeled",
                ),
                "modeled build aborts on lock (no exclusions written)",
            ),
        ):
            try:
                fn()
            except guards.GuardBlocked:
                check(True, label)
            else:
                check(False, label)
    finally:
        lock.unlink()


def main() -> None:
    test_resolve_quote()
    test_fills()
    test_governor()
    test_selection()
    test_full_quote_fetcher_guarded()
    print(f"dragonfly phase1 modeled spread: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
