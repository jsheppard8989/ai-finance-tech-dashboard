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
from dragonfly.build_watchlist import (  # noqa: E402
    ETF_INFO_URL,
    KNOWN_DEPOSITARY_RECEIPTS,
    QUOTE_INFO_URL,
    SCREENER_URL,
    fetch_security_types,
    run_gates,
)

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
    check(tech == ["NVDA", "AAPL", "GOOGL", "MSFT", "SPCX"], f"tech top 5 companies by cap {tech}")
    check([m["sector_rank"] for m in r["sectors"]["Technology"]] == [1, 2, 3, 4, 5], "sector ranks")
    check("GOOG" not in tech and "META" not in tech, "dropped class / #6 company not members")
    check([m["ticker"] for m in r["sectors"]["Energy"]] == ["FANG"], "1-member sector contributes 1")
    check([m["ticker"] for m in r["sectors"]["Utilities"]] == ["CEG", "AEP", "XEL"], "3-member sector contributes 3")
    check(r["sector_sizes"]["Utilities"] == 3 and r["sector_sizes"]["Technology"] == 6, "sizes count ranked names only")
    check(r["excluded"] == {"GOOG": "duplicate_share_class", "NOCAP": "market_cap_missing", "NOSEC": "sector_missing", "ZEROCAP": "market_cap_missing"}, f"fail closed {r['excluded']}")
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
        if t == "SPCX":
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
    check("META" not in names and "META" not in quoted and "GOOG" not in quoted, "#6 company / dropped class in Tech never considered")
    check(names == {"NVDA", "AAPL", "GOOGL", "MSFT", "SPCX", "AMZN", "FANG", "CEG"} | {f"FILL{i}" for i in range(75, 80)}, f"admitted {sorted(names)}")
    disc = res["sectors"]["Consumer Discretionary"]
    check([e["ticker"] for e in disc] == ["AMZN", "WMT", "PDD", "COST", "NFLX"], "sector view keeps the 5 slots")
    check([e["status"] for e in disc] == ["admitted", "excluded", "excluded", "excluded", "excluded"], "empty slots stay empty")
    check(disc[2]["reason"] == "depositary_receipt", "slot reason recorded")
    by = {n["ticker"]: n for n in res["names"]}
    check(by["SPCX"]["spread_source"] == "modeled_last_0.05" and by["SPCX"]["mid"] == 250.0, "modeled fallback inside universe")
    check(by["NVDA"]["sector"] == "Technology" and by["NVDA"]["sector_rank"] == 1 and by["NVDA"]["market_cap"] == 5.4e12, "name carries sector/rank/cap")
    f = res["funnel"]
    check(f["universe_members"] == 19 and f["admitted"] == 13 and f["empty_slots"] == 6, f"funnel {f}")
    check(ex["GOOG"] == {"reason": "duplicate_share_class", "origin": ["ndx_top5"], "kept": "GOOGL", "sector": "Technology", "sector_rank": None, "market_cap": None}, "dropped class recorded in watchlist exclusions")
    check(len(res["names"]) + len(ex) == len(universe["members"]) + 1, "every member admitted or excluded with a reason (+1 dropped class)")


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


def test_share_class_collapse():
    key = nu.issuer_key
    check(key("GOOG", "Alphabet Inc. Class C Capital Stock") == key("GOOGL", "Alphabet Inc. Class A Common Stock"), "alphabet same issuer")
    check(key("AAA", "Fox Corporation Class A Common Stock") == key("BBB", "Fox Corporation Class B Common Stock") == "fox corporation", "name-based: class suffix ignored")
    check(key("HONA", "Honeywell Aerospace Inc. Common Stock ") != key("HON", "Honeywell International Inc. Common Stock"), "different companies not merged")
    check(key("MSTR", "Strategy Inc Common Stock Class A") == "strategy inc", "trailing class suffix")
    check(key("SHOP", "Shopify Inc. Class A Subordinate Voting Shares") == "shopify inc", "subordinate voting suffix")
    check(key("ZZZ", None) == "ticker:ZZZ" and key("ZZZ", "  ") == "ticker:ZZZ", "no name -> ticker is its own issuer")

    # GOOGL kept even when GOOG shows the higher market cap (explicit preference).
    members = [
        {"ticker": "GOOG", "name": "Alphabet Inc. Class C Capital Stock", "sector": "Technology", "market_cap": 5e12},
        {"ticker": "GOOGL", "name": "Alphabet Inc. Class A Common Stock", "sector": "Technology", "market_cap": 4e12},
        {"ticker": "FOXB", "name": "Fox Corporation Class B Common Stock", "sector": "Telecommunications", "market_cap": 2e10},
        {"ticker": "FOXQ", "name": "Fox Corporation Class A Common Stock", "sector": "Telecommunications", "market_cap": 3e10},
        {"ticker": "TIE2", "name": "Tie Co Class B Common Stock", "sector": "Energy", "market_cap": 1e10},
        {"ticker": "TIE1", "name": "Tie Co Class A Common Stock", "sector": "Energy", "market_cap": 1e10},
        {"ticker": "META", "name": "Meta Platforms, Inc. Class A Common Stock", "sector": "Technology", "market_cap": 1.9e12},
    ]
    c = nu.collapse_share_classes(members)
    kept = {m["ticker"] for m in c["kept"]}
    check(kept == {"GOOGL", "FOXQ", "TIE1", "META"}, f"one class per company {sorted(kept)}")
    check(c["dropped"] == {"FOXB": "FOXQ", "GOOG": "GOOGL", "TIE2": "TIE1"}, f"dropped -> kept {c['dropped']}")
    g = next(m for m in c["kept"] if m["ticker"] == "GOOGL")
    check(g["share_classes"] == ["GOOGL", "GOOG"] and g["issuer"] == "alphabet inc", "kept row lists its classes")
    check(g["market_cap"] == 4e12, "company cap = kept class figure (not summed)")

    # Ranking counts companies: with Alphabet collapsed, META takes a Tech slot.
    rows = [
        ("NVDA", "Technology", "5,400,000,000,000"),
        ("AAPL", "Technology", "4,965,888,657,700"),
        ("GOOGL", "Technology", "4,208,343,000,000"),
        ("GOOG", "Technology", "4,176,178,100,000"),
        ("MSFT", "Technology", "3,840,000,000,000"),
        ("META", "Technology", "1,915,000,000,000"),
        ("AVGO", "Technology", "1,500,000,000,000"),
    ] + [(f"FILL{i}", "Industrials", f"{i},000,000,000") for i in range(1, 90)]
    ndx, scr = feed(rows)
    ndx["data"]["data"]["rows"][2]["companyName"] = "Alphabet Inc. Class A Common Stock"
    ndx["data"]["data"]["rows"][3]["companyName"] = "Alphabet Inc. Class C Capital Stock"
    r = nu.rank_by_sector(nu.parse_members(ndx, scr))
    tech = [m["ticker"] for m in r["sectors"]["Technology"]]
    check(tech == ["NVDA", "AAPL", "GOOGL", "MSFT", "META"], f"META in after collapse {tech}")
    check(r["excluded"]["GOOG"] == "duplicate_share_class" and r["duplicate_share_classes"] == {"GOOG": "GOOGL"}, "GOOG recorded")
    check(r["companies"] == r["constituents"] - 1, "companies = constituents - dropped classes")
    check(nu.SCHEMA.endswith("/2") and nu.is_stale({"schema": "dragonfly.ndx_universe/1", "per_sector": 5, "members": [{"ticker": "X"}], "as_of_date": "2026-09-25"}, datetime(2026, 9, 25).date()), "pre-collapse universe file forces a refresh")


def _screener_rows():
    rows = [
        # pinned, not NDX members
        {"symbol": "ORCL", "name": "Oracle Corporation Common Stock", "sector": "Technology", "marketCap": "421932121440.00"},
        {"symbol": "IREN", "name": "IREN Limited Ordinary Shares", "sector": "Finance", "marketCap": "18185806605.00"},
        {"symbol": "NTLA", "name": "Intellia Therapeutics Inc. Common Stock", "sector": "Health Care", "marketCap": "1703940587.00"},
        {"symbol": "PENNY", "name": "Penny Corp Common Stock", "sector": "Energy", "marketCap": "900000000.00"},
        {"symbol": "NOSECP", "name": "No Sector Inc. Common Stock", "sector": "", "marketCap": "5000000000.00"},
        {"symbol": "NOQUOTE", "name": "No Quote Inc. Common Stock", "sector": "Utilities", "marketCap": "5000000000.00"},
    ]
    return {"data": {"rows": rows}}


def test_pinned():
    cfg = Path(_TMP) / "universe_config.json"
    pinned_list = ["NVDA", "orcl", "IREN", "NTLA", "ARKG", "TLT", "PENNY", "NOSECP", "NOQUOTE", "GHOST", "ORCL"]
    cfg.write_text(json.dumps({"schema": nu.CONFIG_SCHEMA, "universe_pinned": pinned_list}))
    check(nu.load_pinned(cfg) == ["NVDA", "ORCL", "IREN", "NTLA", "ARKG", "TLT", "PENNY", "NOSECP", "NOQUOTE", "GHOST"], "config normalized + de-duplicated")
    for bad in ({"schema": "x", "universe_pinned": []}, {"schema": nu.CONFIG_SCHEMA, "universe_pinned": "META"}, {"schema": nu.CONFIG_SCHEMA, "universe_pinned": ["BAD TICKER!"]}):
        bp = Path(_TMP) / "bad_config.json"
        bp.write_text(json.dumps(bad))
        check(raises(lambda: nu.load_pinned(bp), ValueError), f"malformed config raises {bad}")
    check(raises(lambda: nu.load_pinned(Path(_TMP) / "missing.json"), OSError), "missing config raises (never silently empty)")

    # A weekly refresh never touches the pinned config, and pinned survives it.
    upath = Path(_TMP) / "universe_pinned_test.json"
    before = cfg.read_bytes()
    nu.get_universe(upath, fake_get_json(), datetime(2026, 9, 25, 16, 0))
    nu.get_universe(upath, fake_get_json(), datetime(2026, 10, 9, 16, 0), refresh=True)
    check(cfg.read_bytes() == before, "refresh leaves the pinned config byte-identical")
    check(nu.load_pinned(cfg)[1] == "ORCL", "pinned list still loads after refresh")
    universe = nu.load(upath)
    check("ORCL" not in [m["ticker"] for m in universe["members"]], "pinned never written into the ranked membership")

    pinned = nu.resolve_pinned(nu.load_pinned(cfg), _screener_rows())
    pby = {p["ticker"]: p for p in pinned}
    check(pby["ORCL"]["sector"] == "Technology" and pby["ORCL"]["market_cap"] == 421932121440.0, "pinned sector/cap from screener")
    check(pby["GHOST"]["sector"] is None and pby["GHOST"]["market_cap"] is None, "unknown pinned stays None")

    types = _types_for(universe["members"])
    types.update({
        "ORCL": {"class": "common"}, "IREN": {"class": "common"}, "NTLA": {"class": "common"},
        "PENNY": {"class": "common"}, "NOSECP": {"class": "common"}, "NOQUOTE": {"class": "common"},
        "ARKG": {"class": "not_common_stock", "descriptor": "ARK Genomic Revolution ETF [assetclass: etf]"},
        "TLT": {"class": "not_common_stock", "descriptor": "iShares 20+ Year Treasury Bond ETF [assetclass: etf]"},
        "GHOST": {"class": None},
    })
    quoted = []

    def rows_fn(eligible):
        rows = []
        for c in eligible:
            t = c["ticker"]
            price = 5.0 if t == "PENNY" else 100.0
            adv = 1e7 if t == "NTLA" else 5e9
            rows.append({"ticker": t, "sector": c.get("sector"), "price": price, "adv20_dollars": adv})
        return rows, {}

    def quote_fn(t):
        quoted.append(t)
        if t == "NOQUOTE":
            return None
        return {"bid": 99.99, "ask": 100.01, "last": 100.0}

    base = run_gates(universe, types, quote_fn, rows_fn=rows_fn)
    res = run_gates(universe, types, quote_fn, rows_fn=rows_fn, pinned=pinned)
    by = {n["ticker"]: n for n in res["names"]}
    ex = res["excluded_members"]
    check(by["NVDA"]["origin"] == ["ndx_top5", "pinned"], "pinned top-5 member appears once with both origins")
    check(sum(1 for n in res["names"] if n["ticker"] == "NVDA") == 1, "no duplicate row")
    check(by["ORCL"]["origin"] == ["pinned"] and by["ORCL"]["sector_rank"] is None, "pinned-only name admitted without a slot")
    check(by["IREN"]["sector"] == "Finance" and by["IREN"]["market_cap"] == 18185806605.0, "pinned carries screener sector/cap")
    check(ex["ARKG"]["reason"] == "not_common_stock" and ex["ARKG"]["origin"] == ["pinned"], "pinned ETF excluded, tagged pinned")
    check(ex["TLT"]["reason"] == "not_common_stock", "pinned bond ETF excluded")
    check(ex["NTLA"] == {"reason": "adv_below_minimum", "origin": ["pinned"], "sector": "Health Care", "sector_rank": None, "market_cap": 1703940587.0}, "pinned ADV failure recorded")
    check(ex["PENNY"]["reason"] == "price_below_minimum", "pinned price failure recorded")
    check(ex["NOSECP"]["reason"] == "security_type_unknown", "pinned with no sector -> security_type_unknown")
    check(ex["GHOST"]["reason"] == "security_type_unknown", "pinned unknown everywhere -> security_type_unknown")
    check(ex["NOQUOTE"]["reason"] == "no_usable_mid_or_last", "pinned modeled-mid rule applies")
    check("NOSECP" not in quoted and "ARKG" not in quoted and "GHOST" not in quoted, "failed pinned names never quoted")

    # Pinned names never consume or displace sector slots.
    check(res["sectors"] == {k: [dict(e, origin=(["ndx_top5", "pinned"] if e["ticker"] == "NVDA" else e["origin"])) for e in v] for k, v in base["sectors"].items()}, "sector slots identical with and without pinned")
    top5_names = {n["ticker"] for n in res["names"] if "ndx_top5" in n["origin"]}
    check(top5_names == {n["ticker"] for n in base["names"]}, "top-5 admissions unchanged by pinned")
    check(all(len(v) <= 5 for v in res["sectors"].values()), "still at most 5 slots per sector")
    check("ORCL" not in [e["ticker"] for e in res["sectors"]["Technology"]], "pinned Tech name not in the Tech slots")
    f = res["funnel"]
    check(f["empty_slots"] == base["funnel"]["empty_slots"] and f["admitted_top5"] == len(base["names"]), "empty slots stay empty (no backfill)")
    check(f["pinned"] == 10 and f["pinned_also_top5"] == 1 and f["admitted_pinned_only"] == 2, f"pinned funnel {f}")
    pv = {e["ticker"]: e for e in res["pinned"]}
    check(set(pv) == set(nu.load_pinned(cfg)) and pv["NTLA"]["status"] == "excluded" and pv["ORCL"]["status"] == "admitted", "pinned view covers every pinned name")


def test_etf_type_probe():
    screener = {"data": {"rows": [{"symbol": "ORCL", "name": "Oracle Corporation Common Stock"}]}}
    urls = []

    def get_json(url):
        urls.append(url)
        if url == SCREENER_URL:
            return screener
        if url == QUOTE_INFO_URL.format(symbol="ARKG"):
            return {"data": None, "status": {"rCode": 400}}  # "Symbol not exists." for stocks
        if url == ETF_INFO_URL.format(symbol="ARKG"):
            return {"data": {"symbol": "ARKG", "companyName": "ARK Genomic Revolution ETF", "stockType": None}}
        raise RuntimeError("404")

    t = fetch_security_types(["ORCL", "ARKG", "GHOST"], get_json=get_json)
    check(t["ORCL"]["class"] == "common" and ETF_INFO_URL.format(symbol="ORCL") not in urls, "stock resolved without ETF probe")
    check(t["ARKG"]["class"] == "not_common_stock" and t["ARKG"]["source"] == "nasdaq_quote_info_etf", "ETF -> not_common_stock")
    check(t["GHOST"]["class"] is None, "unknown everywhere stays unknown (security_type_unknown)")


def main():
    test_parse_and_rank()
    test_share_class_collapse()
    test_no_backfill()
    test_weekly_refresh()
    test_missing_sector_or_cap_fail_closed()
    test_pinned()
    test_etf_type_probe()
    print(f"dragonfly phase1 universe: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
