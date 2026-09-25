"""Offline tests: pipeline/schedule guards, chains shortlist cap, security type
(ADR) exclusion, and cache-first bars. No network.

Run: python3 dragonfly/test_phase1_guards.py
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-guard-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = str(Path(_TMP) / "state")
LOCK = Path(_TMP) / "auto_pipeline.lock"
LOCK2 = Path(_TMP) / "other.lock"
os.environ["DRAGONFLY_PIPELINE_LOCK"] = str(LOCK) + os.pathsep + str(LOCK2)
os.environ.pop("DRAGONFLY_ALLOW_DAEMON_WINDOW", None)
os.environ.pop("DRAGONFLY_CHAINS_MAX_NAMES", None)

from dragonfly import bars, chains, guards  # noqa: E402
from dragonfly.build_watchlist import (  # noqa: E402
    KNOWN_DEPOSITARY_RECEIPTS,
    QUOTE_INFO_URL,
    SCREENER_URL,
    apply_security_types,
    classify_security,
    fetch_security_types,
    select_watchlist,
    yahoo_quote,
)

CHECKS = 0


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def raises(fn, exc_type, reason=None):
    try:
        fn()
    except exc_type as exc:
        return reason is None or getattr(exc, "reason", None) == reason
    return False


def dead_pid() -> int:
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


def ct(h, m):
    from zoneinfo import ZoneInfo

    return datetime(2026, 9, 28, h, m, tzinfo=ZoneInfo("America/Chicago"))


def clear_locks():
    for p in (LOCK, LOCK2):
        if p.exists():
            p.unlink()


# ------------------------------------------------------------------ guards

def test_lock_guard():
    clear_locks()
    check(guards.lock_paths() == [LOCK, LOCK2], "lock paths from env (pathsep list)")
    check(guards.pipeline_busy() is None, "no lock file -> free")
    LOCK.write_text(str(os.getpid()))
    check("live pid" in (guards.pipeline_busy() or ""), "live pid holds the lock")
    check(raises(lambda: guards.check_pipeline(0), guards.GuardBlocked, "pipeline_running"), "held lock blocks")
    LOCK.write_text(str(dead_pid()))
    check(guards.pipeline_busy() is None, "dead pid lock is stale -> free")
    LOCK.write_text("not-a-pid")
    check("pid unreadable" in (guards.pipeline_busy() or ""), "unreadable lock counts as held (fail closed)")
    clear_locks()
    LOCK2.write_text(str(os.getpid()))
    check(guards.pipeline_busy() is not None, "second configured path honoured")
    clear_locks()

    # bounded wait: held throughout -> abort after the wait, with sleeps in between
    LOCK.write_text(str(os.getpid()))
    t = {"now": 0.0}
    sleeps = []

    def fake_sleep(s):
        sleeps.append(s)
        t["now"] += s

    check(
        raises(lambda: guards.check_pipeline(30, poll_seconds=10, sleep=fake_sleep, clock=lambda: t["now"]), guards.GuardBlocked, "pipeline_running"),
        "bounded wait then abort",
    )
    check(sum(sleeps) >= 30 and len(sleeps) == 3, "waited the bounded time in polls")

    # released during the wait -> proceeds
    t["now"] = 0.0

    def release_sleep(s):
        t["now"] += s
        clear_locks()

    guards.check_pipeline(300, poll_seconds=10, sleep=release_sleep, clock=lambda: t["now"])
    check(t["now"] == 10, "proceeds as soon as the lock is released")
    clear_locks()


def test_schedule_guard():
    blocked = [(5, 0), (6, 30), (7, 10), (7, 59), (12, 0), (12, 54), (14, 59), (22, 0), (23, 59)]
    open_ = [(4, 59), (8, 0), (8, 5), (11, 59), (15, 0), (21, 59)]
    for h, m in blocked:
        check(guards.daemon_window(ct(h, m)) is not None, f"{h:02d}:{m:02d} inside a daemon window")
    for h, m in open_:
        check(guards.daemon_window(ct(h, m)) is None, f"{h:02d}:{m:02d} outside daemon windows")
    check(raises(lambda: guards.check_schedule(ct(7, 10)), guards.GuardBlocked, "daemon_window"), "07:10 pre-open is blocked")
    guards.check_schedule(ct(7, 10), allow=True)
    check(True, "explicit override allows")
    os.environ["DRAGONFLY_ALLOW_DAEMON_WINDOW"] = "1"
    guards.check_schedule(ct(12, 30))
    check(True, "env override allows")
    os.environ.pop("DRAGONFLY_ALLOW_DAEMON_WINDOW")
    check(guards.RECOMMENDED_PREOPEN_CT == "08:05" and guards.daemon_window(ct(8, 5)) is None, "recommended pre-open is outside windows")
    clear_locks()
    guards.preflight(wait_seconds=0, now_ct=ct(8, 5))
    check(True, "preflight passes at 08:05 with no lock")
    LOCK.write_text(str(os.getpid()))
    check(raises(lambda: guards.preflight(wait_seconds=0, now_ct=ct(8, 5)), guards.GuardBlocked, "pipeline_running"), "preflight blocks on lock")
    check(raises(lambda: guards.preflight(wait_seconds=0, now_ct=ct(6, 0)), guards.GuardBlocked, "daemon_window"), "preflight blocks in window first")
    clear_locks()


def test_fetchers_are_guarded():
    """Default network fetchers refuse before touching the network."""
    os.environ["DRAGONFLY_ALLOW_DAEMON_WINDOW"] = "1"  # isolate the lock check from wall-clock time
    LOCK.write_text(str(os.getpid()))
    try:
        check(raises(lambda: bars.yahoo_history("AAPL", period="1y"), guards.GuardBlocked, "pipeline_running"), "bars fetcher guarded")
        check(raises(lambda: bars.refresh("GUARDX"), guards.GuardBlocked, "pipeline_running"), "refresh propagates guard, not BarsUnavailable")
        check(not bars.cache_path("GUARDX").exists(), "no cache written when blocked")
        check(raises(lambda: chains.default_ticker_factory("AAPL"), guards.GuardBlocked), "chains factory guarded")
        check(raises(lambda: chains.get_chain("AAPL", "2026-10-16"), guards.GuardBlocked), "get_chain propagates guard, not ChainUnavailable")
        check(raises(lambda: chains.fetch_shortlist_chains(["AAPL"], save=False), guards.GuardBlocked), "shortlist aborts on guard")
        check(raises(lambda: yahoo_quote("AAPL"), guards.GuardBlocked), "quote fetcher guarded")
        rows = [{"ticker": "AAA", "price": 50.0, "adv20_dollars": 1e8}]
        check(raises(lambda: select_watchlist(rows, yahoo_quote, cap=5, batch=1, workers=1), guards.GuardBlocked), "watchlist build aborts on guard (no exclusions written)")
    finally:
        clear_locks()
        os.environ.pop("DRAGONFLY_ALLOW_DAEMON_WINDOW", None)


# ------------------------------------------------------------------ chains shortlist

class FakeChain:
    def __init__(self, calls, puts):
        self.calls, self.puts, self.underlying = calls, puts, {}


class FakeTicker:
    def __init__(self, options, chain=None):
        self._options = options
        self._chain = chain
        self.option_calls = 0

    @property
    def options(self):
        self.option_calls += 1
        return self._options

    def option_chain(self, exp):
        return self._chain


def test_chains_shortlist():
    twenty = [f"T{i}" for i in range(20)]
    check(chains.validate_shortlist(twenty) == twenty, "20 names allowed by default")
    check(raises(lambda: chains.validate_shortlist(twenty + ["T20"]), chains.ShortlistRefused), "21 names refused (not truncated)")
    check(raises(lambda: chains.validate_shortlist([f"W{i}" for i in range(200)]), chains.ShortlistRefused), "full 200-name watchlist refused")
    check(raises(lambda: chains.validate_shortlist({"names": []}), chains.ShortlistRefused), "watchlist document refused")
    check(raises(lambda: chains.validate_shortlist("AAPL"), chains.ShortlistRefused), "bare string refused")
    check(raises(lambda: chains.validate_shortlist([]), chains.ShortlistRefused), "empty shortlist refused")
    check(chains.validate_shortlist(["aapl", "AAPL", "msft"]) == ["AAPL", "MSFT"], "dedupe + upper")
    check(raises(lambda: chains.validate_shortlist(["A", "B", "C"], max_names=2), chains.ShortlistRefused), "explicit max_names")
    os.environ["DRAGONFLY_CHAINS_MAX_NAMES"] = "5"
    check(raises(lambda: chains.validate_shortlist(twenty[:6]), chains.ShortlistRefused), "env cap")
    os.environ.pop("DRAGONFLY_CHAINS_MAX_NAMES")

    exp = "2026-10-16"
    good = [{"contractSymbol": "X", "strike": 100, "bid": 2.45, "ask": 2.55, "volume": 200, "openInterest": 500, "impliedVolatility": 0.3}]
    made = []
    tickers = {"AAA": FakeTicker((exp,), FakeChain(good, [])), "BBB": FakeTicker(())}

    def factory(sym):
        made.append(sym)
        return tickers[sym]

    res = chains.fetch_shortlist_chains(["AAA", "BBB"], today=date(2026, 9, 28), ticker_factory=factory)
    check(set(res["chains"]) == {"AAA"} and res["unavailable"] == {"BBB": "no_expirations"}, "per-name fail closed")
    check(made == ["AAA", "BBB"], "one Ticker per name")
    check(res["chains"]["AAA"]["provisional"] is True and res["chains"]["AAA"]["expiration"] == exp, "picked + stamped")

    made.clear()
    res2 = chains.fetch_shortlist_chains(["AAA"], expiration=exp, ticker_factory=factory)
    check(res2["from_cache"] == ["AAA"] and made == [], "cache-first: fresh cached chain, no fetch")
    res3 = chains.fetch_shortlist_chains(["AAA"], expiration=exp, ticker_factory=factory, max_age_minutes=0)
    check(res3["from_cache"] == [] and made == ["AAA"], "stale cache refetches")
    check(raises(lambda: chains.fetch_shortlist_chains([f"W{i}" for i in range(21)], ticker_factory=factory), chains.ShortlistRefused), "entry point refuses >20")


# ------------------------------------------------------------------ security type (ADR)

def test_security_types():
    cases = {
        "Apple Inc. Common Stock": "common",
        "Alphabet Inc. Class A Common Stock": "common",
        "Thomson Reuters Corporation Common Shares": "common",
        "Linde plc Ordinary Shares": "common",
        "Johnson Controls International plc Ordinary Share": "common",
        "Shopify Inc. Class A Subordinate Voting Shares": "common",
        "Vivmark Residential Common Shares of Beneficial Interest": "common",
        "PDD Holdings Inc. American Depositary Shares": "depositary_receipt",
        "ASML Holding N.V. New York Registry Shares": "depositary_receipt",
        "Some Co ADR": "depositary_receipt",
        "Foo Corp 5.25% Series A Preferred Stock": "not_common_stock",
        "Bar Acquisition Corp Units": "not_common_stock",
        "Berkshire Hathaway Inc.": None,
        "": None,
        None: None,
    }
    for desc, want in cases.items():
        check(classify_security(desc) == want, f"classify {desc!r}")

    screener = {
        "data": {
            "rows": [
                {"symbol": "AAA", "name": "AAA Inc. Common Stock"},
                {"symbol": "BBB", "name": "BBB plc American Depositary Shares"},
                {"symbol": "CCC", "name": "CCC Inc."},
                {"symbol": "DDD", "name": "DDD Corp."},
                {"symbol": "BRK/B", "name": "Berkshire Hathaway Inc."},
                {"symbol": "ASML", "name": "ASML Holding N.V. Common Stock"},  # feed wrong; denylist wins
            ]
        }
    }
    info = {
        "CCC": {"data": {"stockType": "Common Stock"}},
        "BRK.B": {"data": {"stockType": "Common Stock"}},
        "EEE": {"data": {"stockType": "Ordinary Shares"}},
        "FFF": {"data": {"stockType": "American Depositary Shares"}},
    }
    urls = []

    def get_json(url):
        urls.append(url)
        if url == SCREENER_URL:
            return screener
        for sym, payload in info.items():
            if url == QUOTE_INFO_URL.format(symbol=sym):
                return payload
        raise RuntimeError("404")

    tickers = ["AAA", "BBB", "CCC", "DDD", "BRK-B", "ASML", "EEE", "FFF", "GGG"]
    types = fetch_security_types(tickers, get_json=get_json)
    got = {t: types[t]["class"] for t in tickers}
    check(got == {
        "AAA": "common", "BBB": "depositary_receipt", "CCC": "common", "DDD": None,
        "BRK-B": "common", "ASML": "depositary_receipt", "EEE": "common", "FFF": "depositary_receipt", "GGG": None,
    }, "screener -> quote info -> denylist resolution")
    check(QUOTE_INFO_URL.format(symbol="BRK.B") in urls, "class shares looked up with a dot")
    check(QUOTE_INFO_URL.format(symbol="AAA") not in urls, "no second lookup when screener is decisive")
    check("denylist" in types["ASML"]["source"] and "ASML" in KNOWN_DEPOSITARY_RECEIPTS, "denylist overrides feed")

    down = fetch_security_types(["AAA", "PDD"], get_json=lambda url: (_ for _ in ()).throw(RuntimeError("down")))
    check(down["AAA"]["class"] is None and down["PDD"]["class"] == "depositary_receipt", "feeds down: unknown, denylist still applies")

    cands = [{"ticker": t, "sector": "X"} for t in tickers]
    eligible, excluded = apply_security_types(cands, types)
    check([c["ticker"] for c in eligible] == ["AAA", "CCC", "BRK-B", "EEE"], "only positively-typed common stock is eligible")
    check(excluded == {
        "BBB": "depositary_receipt", "DDD": "security_type_unknown", "ASML": "depositary_receipt",
        "FFF": "depositary_receipt", "GGG": "security_type_unknown",
    }, "exclusion reasons")
    check(eligible[0]["security_type"] == "AAA Inc. Common Stock", "descriptor carried")
    check(apply_security_types([{"ticker": "ZZZ"}], {})[1] == {"ZZZ": "security_type_unknown"}, "missing type fails closed")

    # Backfill: the highest-ADV name is an ADR; the next names by ADV fill the list.
    rows = [
        {"ticker": "ADR1", "price": 50.0, "adv20_dollars": 900e6},
        {"ticker": "C1", "price": 50.0, "adv20_dollars": 800e6},
        {"ticker": "C2", "price": 50.0, "adv20_dollars": 700e6},
        {"ticker": "C3", "price": 50.0, "adv20_dollars": 600e6},
    ]
    t2 = {"ADR1": {"class": "depositary_receipt"}, "C1": {"class": "common"}, "C2": {"class": "common"}, "C3": {"class": "common"}}
    elig, exc = apply_security_types(rows, t2)
    res = select_watchlist(elig, lambda t: (49.99, 50.01), cap=2, batch=1, workers=1)
    check([n["ticker"] for n in res["names"]] == ["C1", "C2"] and exc == {"ADR1": "depositary_receipt"}, "ADR excluded, next by ADV backfills")
    res_short = select_watchlist(elig, lambda t: (49.99, 50.01), cap=5, batch=2, workers=1)
    check(len(res_short["names"]) == 3, "list may be shorter than the cap; gate not softened")


# ------------------------------------------------------------------ cache-first bars

def test_bars_cache_first():
    start = date(2026, 8, 3)
    seq = []
    d = start
    while len(seq) < 25:
        if d.weekday() < 5:
            seq.append({"date": d.isoformat(), "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100})
        d += timedelta(days=1)
    calls = []

    def fetcher(ticker, start=None, period=None):
        calls.append((start, period))
        return list(seq) if period else []

    bars.refresh("CF1", fetcher=fetcher)
    check(len(calls) == 1, "first fetch")
    p = bars.refresh("CF1", fetcher=fetcher, max_age_minutes=30)
    check(len(calls) == 1 and p["last_fetch_mode"] == "cache", "fresh cache: no network")
    bars.refresh("CF1", fetcher=fetcher, max_age_minutes=0)
    check(len(calls) == 2, "max_age 0 forces incremental fetch")
    bars.refresh("CF1", fetcher=fetcher)
    check(len(calls) == 3, "default (None) keeps prior behaviour")


def main():
    test_lock_guard()
    test_schedule_guard()
    test_fetchers_are_guarded()
    test_chains_shortlist()
    test_security_types()
    test_bars_cache_first()
    print(f"dragonfly phase1 guards/types: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
