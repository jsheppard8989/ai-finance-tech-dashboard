"""Offline tests for the NDX top-5-per-sector universe: ranking, short sectors,
missing sector / market cap (fail closed), no backfill through the gates, and
the weekly membership refresh. Fakes only, no network.

Run: python3 dragonfly/test_phase1_universe.py
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = _TMP

from dragonfly import ndx_universe as nu  # noqa: E402
from dragonfly.build_watchlist import KNOWN_DEPOSITARY_RECEIPTS, run_gates  # noqa: E402

CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    return False


def ndx_payload(rows):
    return {"data": {"data": {"rows": rows}}}


def screener_payload(rows):
    return {"data": {"rows": rows}}


# Tech: 7 names (top 5 taken). Discretionary: 6 names with an ADR (PDD) at #3.
# Energy: 1 name. Utilities: 3 names. Plus a missing sector and a missing cap.
FEED = [
    ("NVDA", "Technology", "5,400,000,000,000"),
    ("AAPL", "Technology", "4,965,888,657,700"),
    ("GOOGL", "Technology", "4,208,343,000,000"),
    ("GOOG", "Technology", "4,176,178,100,000"),
    ("MSFT", "Technology", "3,840,000,000,000"),
    ("SPCX", "Technology", "2,011,000,000,000"),
    ("META", "Technology", "1,915,000,000,000"),
    ("AMZN", "Consumer Discretionary", "2,690,000,000,000"),
    ("WMT", "Consumer Discretionary", "857,000,000,000"),
    ("PDD", "Consumer Discretionary", "500,000,000,000"),
    ("COST", "Consumer Discretionary", "408,000,000,000"),
    ("NFLX", "Consumer Discretionary", "296,000,000,000"),
    ("BKNG", "Consumer Discretionary", "123,000,000,000"),
    ("FANG", "Energy", "52,000,000,000"),
    ("CEG", "Utilities", "93,000,000,000"),
    ("AEP", "Utilities", "64,000,000,000"),
    ("XEL", "Utilities", "43,000,000,000"),
    ("NOSEC", "", "900,000,000,000"),
    ("NOCAP", "Technology", ""),
    ("ZEROCAP", "Utilities", "0"),
] + [(f"FILL{i}", "Industrials", f"{i},000,000,000") for i in range(1, 80)]


def feed(rows=FEED, sector_override=None):
    sector_override = sector_override or {}
    ndx = ndx_payload([{"symbol": t, "companyName": f"{t} Common Stock", "marketCap": c, "sector": ""} for t, _s, c in rows])
    scr = screener_payload([{"symbol": t, "name": f"{t} Common Stock", "sector": sector_override.get(t, s)} for t, s, _c in rows])
    return ndx, scr


def fake_get_json(rows=FEED, counter=None, sector_override=None):
    ndx, scr = feed(rows, sector_override)

    def get(url):
        if counter is not None:
            counter.append(url)
        if url == nu.NDX_URL:
            return ndx
        if url == nu.SCREENER_URL:
            return scr
        raise AssertionError(url)

    return get


def test_parse_and_rank():
    check(nu.parse_market_cap("4,965,888,657,700") == 4965888657700.0, "comma cap")
    check(nu.parse_market_cap("48728583125.00") == 48728583125.0, "screener-style cap")
    for bad in (None, "", "N/A", "0", "-5", "nan"):
        check(nu.parse_market_cap(bad) is None, f"bad cap {bad!r}")
    ndx, scr = feed()
    members = nu.parse_members(ndx, scr)
    check(len(members) == len(FEED), "every constituent parsed")
    by = {m["ticker"]: m for m in members}
    check(by["AAPL"]["sector"] == "Technology" and by["AAPL"]["market_cap"] == 4965888657700.0, "sector from screener, cap from NDX list")
    check(by["NOSEC"]["sector"] is None, "blank screener sector -> None")
    check(raises(lambda: nu.parse_members(ndx_payload([]), scr), ValueError), "short NDX list raises")

    r = nu.rank_by_sector(members)
    tech = [m["ticker"] for m in r["sectors"]["Technology"]]
    check(tech == ["NVDA", "AAPL", "GOOGL", "GOOG", "MSFT"], f"tech top 5 by cap {tech}")
    check([m["sector_rank"] for m in r["sectors"]["Technology"]] == [1, 2, 3, 4, 5], "sector ranks")
    check("SPCX" not in tech and "META" not in tech, "#6/#7 not members")
    check([m["ticker"] for m in r["sectors"]["Energy"]] == ["FANG"], "1-member sector contributes 1")
    check([m["ticker"] for m in r["sectors"]["Utilities"]] == ["CEG", "AEP", "XEL"], "3-member sector contributes 3")
    check(r["sector_sizes"]["Utilities"] == 3 and r["sector_sizes"]["Technology"] == 7, "sizes count ranked names only")
    check(r["excluded"] == {"NOCAP": "market_cap_missing", "NOSEC": "sector_missing", "ZEROCAP": "market_cap_missing"}, f"fail closed {r['excluded']}")
    check(all(m["ticker"] not in r["excluded"] for m in r["members"]), "excluded names never members")
    check(len(r["members"]) == 5 + 5 + 1 + 3 + 5, "members = sum of per-sector slots")
    tie = nu.rank_by_sector([
        {"ticker": "BBB", "sector": "X", "market_cap": 10.0},
        {"ticker": "AAA", "sector": "X", "market_cap": 10.0},
    ])
    check([m["ticker"] for m in tie["sectors"]["X"]] == ["AAA", "BBB"], "ties broken by ticker (stable)")
    check([m["ticker"] for m in nu.rank_by_sector(members, per_sector=2)["sectors"]["Technology"]] == ["NVDA", "AAPL"], "per_sector param")


def _types_for(members):
    out = {}
    for m in members:
        t = m["ticker"]
        if t in KNOWN_DEPOSITARY_RECEIPTS:
            out[t] = {"class": "depositary_receipt", "descriptor": "ADS", "source": "denylist"}
        elif t == "COST":
            out[t] = {"class": None, "descriptor": None, "source": None}  # type unknown
        else:
            out[t] = {"class": "common", "descriptor": f"{t} Common Stock", "source": "nasdaq_screener"}
    return out


def test_no_backfill():
    universe = nu.fetch_and_rank(fake_get_json(), datetime(2026, 9, 25, 10, 0))
    types = _types_for(universe["members"])
    quoted = []

    def rows_fn(eligible):
        rows, errors = [], {}
        for c in eligible:
            t = c["ticker"]
            if t == "NFLX":
                errors[t] = "bars_unavailable"
                continue
            price = 8.0 if t == "XEL" else 100.0
            adv = 1e6 if t == "AEP" else 5e9
            rows.append({"ticker": t, "sector": c.get("sector"), "security_type": c.get("security_type"), "price": price, "adv20_dollars": adv})
        return rows, errors

    def quote_fn(t):
        quoted.append(t)
        if t == "WMT":
            return {"bid": None, "ask": None, "last": None}  # no usable mid / last
        if t == "GOOG":
            return {"bid": 0, "ask": 0, "last": 250.0}  # modeled around last
        return {"bid": 99.99, "ask": 100.01, "last": 100.0}

    res = run_gates(universe, types, quote_fn, spread_mode="modeled", rows_fn=rows_fn)
    names = {n["ticker"] for n in res["names"]}
    ex = res["excluded_members"]
    check(ex["PDD"]["reason"] == "depositary_receipt" and ex["PDD"]["sector_rank"] == 3, "ADR in top 5 excluded with its slot")
    check(ex["COST"]["reason"] == "security_type_unknown", "unknown type excluded")
    check(ex["NFLX"]["reason"] == "bars_unavailable", "bars failure excluded")
    check(ex["WMT"]["reason"] == "no_usable_mid_or_last", "no mid/no last excluded")
    check(ex["XEL"]["reason"] == "price_below_minimum", "price gate exact")
    check(ex["AEP"]["reason"] == "adv_below_minimum", "ADV gate exact")
    check("BKNG" not in names and "BKNG" not in ex and "BKNG" not in quoted, "#6 in Discretionary never pulled in (no backfill)")
    check("SPCX" not in names and "META" not in names and "SPCX" not in quoted, "#6/#7 in Tech never considered")
    check(names == {"NVDA", "AAPL", "GOOGL", "GOOG", "MSFT", "AMZN", "FANG", "CEG"} | {f"FILL{i}" for i in range(75, 80)}, f"admitted {sorted(names)}")
    disc = res["sectors"]["Consumer Discretionary"]
    check([e["ticker"] for e in disc] == ["AMZN", "WMT", "PDD", "COST", "NFLX"], "sector view keeps the 5 slots")
    check([e["status"] for e in disc] == ["admitted", "excluded", "excluded", "excluded", "excluded"], "empty slots stay empty")
    check(disc[2]["reason"] == "depositary_receipt", "slot reason recorded")
    by = {n["ticker"]: n for n in res["names"]}
    check(by["GOOG"]["spread_source"] == "modeled_last_0.05" and by["GOOG"]["mid"] == 250.0, "modeled fallback inside universe")
    check(by["NVDA"]["sector"] == "Technology" and by["NVDA"]["sector_rank"] == 1 and by["NVDA"]["market_cap"] == 5.4e12, "name carries sector/rank/cap")
    f = res["funnel"]
    check(f["universe_members"] == 19 and f["admitted"] == 13 and f["empty_slots"] == 6, f"funnel {f}")
    check(len(res["names"]) + len(ex) == len(universe["members"]), "every member admitted or excluded with a reason")


def test_weekly_refresh():
    path = Path(_TMP) / "universe.json"
    t0 = datetime(2026, 9, 25, 16, 0)
    calls = []
    u0 = nu.get_universe(path, fake_get_json(counter=calls), t0)
    check(u0["reused"] is False and len(calls) == 2 and path.exists(), "first build fetches and persists")
    saved = json.loads(path.read_text())
    check(saved["as_of_date"] == "2026-09-25" and "reused" not in saved, "persisted with as_of date")
    members0 = [m["ticker"] for m in u0["members"]]

    # A reshuffled feed (META now #1 in Tech, AAPL demoted) must NOT change membership on daily builds.
    shuffled = [(t, s, "9,999,000,000,000" if t == "META" else c) for t, s, c in FEED]
    for day in range(1, 7):
        calls.clear()
        u = nu.get_universe(path, fake_get_json(shuffled, counter=calls), t0 + timedelta(days=day))
        check(u["reused"] is True and calls == [] and u["age_days"] == day, f"day {day}: reused, no fetch")
        check([m["ticker"] for m in u["members"]] == members0, f"day {day}: membership unchanged")
    calls.clear()
    u7 = nu.get_universe(path, fake_get_json(shuffled, counter=calls), t0 + timedelta(days=7))
    check(u7["reused"] is False and len(calls) == 2, "7 days old -> refresh")
    check([m["ticker"] for m in u7["sectors"]["Technology"]][0] == "META", "refresh picks up new ranking")
    check(json.loads(path.read_text())["as_of_date"] == "2026-10-02", "refresh re-stamps as_of")

    calls.clear()
    uf = nu.get_universe(path, fake_get_json(counter=calls), t0 + timedelta(days=8), refresh=True)
    check(uf["reused"] is False and len(calls) == 2, "--refresh-universe forces a refresh")

    today = datetime(2026, 9, 25).date()
    good = {"schema": nu.SCHEMA, "per_sector": 5, "members": [{"ticker": "X"}], "as_of_date": "2026-09-25"}
    check(nu.is_stale(None, today), "missing file stale")
    check(nu.is_stale({**good, "schema": "old"}, today), "wrong schema stale")
    check(nu.is_stale({**good, "per_sector": 4}, today), "different N stale")
    check(nu.is_stale({**good, "members": []}, today), "empty membership stale")
    check(nu.is_stale({**good, "as_of_date": "garbage"}, today), "bad date stale")
    check(nu.is_stale({**good, "as_of_date": "2026-09-26"}, today), "future-dated stale")
    check(not nu.is_stale({**good, "as_of_date": "2026-09-19"}, today), "6 days old fresh")
    check(nu.is_stale({**good, "as_of_date": "2026-09-18"}, today), "7 days old stale")

    # Stale + fetch failure: raise, keep the old file untouched (no silent reuse, no partial write).
    before = path.read_text()

    def down(url):
        raise OSError("nasdaq down")

    check(raises(lambda: nu.get_universe(path, down, t0 + timedelta(days=30)), OSError), "failed refresh raises")
    check(path.read_text() == before, "failed refresh leaves file untouched")
    path.write_text("{not json")
    calls.clear()
    ur = nu.get_universe(path, fake_get_json(counter=calls), t0)
    check(ur["reused"] is False and len(calls) == 2, "corrupt file -> refresh")


def test_missing_sector_or_cap_fail_closed():
    # The screener drops a top-cap name's sector: excluded with a reason, never ranked or gated.
    get = fake_get_json(sector_override={"NVDA": ""})
    u = nu.fetch_and_rank(get, datetime(2026, 9, 25, 10, 0))
    check(u["excluded"].get("NVDA") == "sector_missing", "missing sector excluded with reason")
    check("NVDA" not in [m["ticker"] for m in u["members"]], "missing-sector name not a member")
    check(u["excluded"].get("NOCAP") == "market_cap_missing", "missing cap excluded with reason")
    rows = [r for r in FEED if r[0] != "NOSEC"] + [("GONE", "Energy", None)]
    u2 = nu.rank_by_sector(nu.parse_members(*feed(rows)))
    check(u2["excluded"].get("GONE") == "market_cap_missing", "null cap excluded")


def main():
    test_parse_and_rank()
    test_no_backfill()
    test_weekly_refresh()
    test_missing_sector_or_cap_fail_closed()
    print(f"dragonfly phase1 universe: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
