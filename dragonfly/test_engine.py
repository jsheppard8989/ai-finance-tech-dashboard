"""Offline tests for the pre-open engine, red team gating, setup gates, the NYSE
calendar, READY/DONE markers and ops templates.

A temp bare git repo stands in for dragonfly-private, with two clones: the
Mac's engine checkout and a box agent that pushes drafts, red team files and
prep. A fake book and a fake bars cache live in a temp state dir. No network:
sockets are patched to fail, the load guards and the bars fetchers are patched
to fail if called, and yfinance is never imported.

Run: python3 dragonfly/test_engine.py
"""

from __future__ import annotations

import atexit
import copy
import io
import json
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-engine-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = str(Path(_TMP) / "state")
# A pipeline lock held by a live PID (this process). A data fetch would block
# on it; the engine must not care.
LOCK = Path(_TMP) / "auto_pipeline.lock"
LOCK.write_text(f"{os.getpid()}\n")
os.environ["DRAGONFLY_PIPELINE_LOCK"] = str(LOCK)
os.environ.pop("DRAGONFLY_ALLOW_DAEMON_WINDOW", None)
for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    os.environ.pop(var, None)


# ---------------------------------------------------------------- no network
class NetworkUsed(AssertionError):
    pass


_real_connect = socket.socket.connect


def _no_connect(self, address):  # pragma: no cover - only fires on a violation
    raise NetworkUsed(f"network call attempted: {address!r}")


socket.socket.connect = _no_connect  # type: ignore[assignment]
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(NetworkUsed(f"create_connection {a!r}"))  # type: ignore

from dragonfly import guards  # noqa: E402


def _guard_called(*_a, **_k):
    raise AssertionError("engine called a data-fetch load guard; it must not fetch")


guards.before_fetch = _guard_called  # type: ignore[assignment]
guards.preflight = _guard_called  # type: ignore[assignment]

from dragonfly import bars as bars_mod  # noqa: E402


def _fetch_called(*_a, **_k):
    raise AssertionError("engine tried to fetch bars; it must read the cache only")


bars_mod.yahoo_history = _fetch_called  # type: ignore[assignment]
bars_mod.refresh = _fetch_called  # type: ignore[assignment]
bars_mod.ticker_metrics = _fetch_called  # type: ignore[assignment]

from dragonfly import engine_fixtures as fx  # noqa: E402
from dragonfly import market_calendar as mc  # noqa: E402
from dragonfly import risk_math as rm  # noqa: E402
from dragonfly import setup_gates as sg  # noqa: E402
from dragonfly.engine import core  # noqa: E402
from dragonfly.engine.cli import main as cli_main  # noqa: E402
from dragonfly.engine.core import SessionClock  # noqa: E402
from dragonfly.engine.engine import Engine  # noqa: E402
from dragonfly.engine.gitops import PrivateRepo  # noqa: E402
from dragonfly.engine.markers import write_ready  # noqa: E402
from dragonfly.engine.core import EngineError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "docs" / "dragonfly" / "examples"
D = date(2026, 9, 28)  # a Monday
PREV = date(2026, 9, 25)  # previous NYSE session
DS = D.isoformat()
CHECKS = 0
LOG = io.StringIO()
_h = logging.StreamHandler(LOG)
logging.getLogger("dragonfly.engine").addHandler(_h)
logging.getLogger("dragonfly.engine").setLevel(logging.INFO)


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def ct(h, m, s=0, day=D):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=core.tz())


def git(cwd, *args):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} in {cwd}: {proc.stderr}")
    return proc.stdout


# ---------------------------------------------------------------- fixtures
SETUP_PLANS = {
    # setup: (bars builder, trigger, stop, target, reference_level, base_level)
    "catalyst_breakout": (fx.breakout, 84.5, 80.75, 91.0, 84.2, None),
    "momentum_pullback": (fx.pullback, 89.7, 87.5, 94.0, 89.6, 86.0),
    "failed_breakdown": (fx.failed_breakdown, 80.8, 79.0, 84.5, 79.5, None),
    "compression_expansion": (fx.compression, 82.7, 79.1, 89.0, 80.8, None),
}
FLAGS_NONE = {f: False for f in core.WARNING_FLAGS}


class World:
    """Fresh fake dragonfly-private (bare remote + mac clone + agent clone), book and bars cache."""

    def __init__(self, name, book=None, session=D):
        self.session = session
        self.ds = session.isoformat()
        self.base = Path(_TMP) / name
        self.remote = self.base / "remote.git"
        self.mac = self.base / "mac"
        self.agent = self.base / "agent"
        self.state = self.base / "state"
        self.bars_dir = self.state / "cache" / "bars"
        self.watchlist = self.base / "watchlist.json"
        self.prep = {}
        self.base.mkdir(parents=True)
        git(self.base, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        seed = self.base / "seed"
        git(self.base, "init", "--quiet", "-b", "main", str(seed))
        self._ident(seed)
        (seed / "README.md").write_text("fake dragonfly-private\n")
        (seed / "handoff").mkdir()
        (seed / "handoff" / ".gitkeep").write_text("")
        (seed / "inbox").mkdir()
        (seed / "inbox" / ".gitkeep").write_text("")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "seed")
        git(seed, "remote", "add", "origin", str(self.remote))
        git(seed, "push", "--quiet", "origin", "main")
        for clone in (self.mac, self.agent):
            git(self.base, "clone", "--quiet", str(self.remote), str(clone))
            self._ident(clone)
        self.book_path = self.state / "book.json"
        self.bars_dir.mkdir(parents=True)
        if book is None:
            book = json.loads((EXAMPLES / "engine_book.json").read_text())
            book["as_of"] = datetime.combine(mc.previous_session(session), datetime.min.time().replace(hour=15, minute=30),
                                             tzinfo=core.tz()).isoformat()
        self.write_book(book)
        self.now = ct(8, 8, day=session)

    @staticmethod
    def _ident(repo):
        git(repo, "config", "user.name", "test")
        git(repo, "config", "user.email", "test@example.invalid")
        git(repo, "config", "commit.gpgsign", "false")

    def write_book(self, book):
        self.book_path.write_text(json.dumps(book))

    def agent_push(self, rel, obj, raw=None, message="agent"):
        git(self.agent, "pull", "--quiet", "--rebase", "origin", "main")
        path = self.agent / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(raw if raw is not None else json.dumps(obj, indent=1))
        git(self.agent, "add", "-A")
        git(self.agent, "commit", "--quiet", "-m", message)
        git(self.agent, "push", "--quiet", "origin", "main")

    def name(self, ticker, bars, sector, spread=0.04, prep=True, cache=True):
        """Put a ticker's bars in the Mac cache and its sector/spread in the prep file."""
        if cache:
            (self.bars_dir / f"{ticker}.json").write_text(json.dumps({"ticker": ticker, "provisional": True, "bars": bars}))
        if prep:
            self.prep[ticker] = {"ticker": ticker, "sector": sector, "spread": spread, "spread_source": "yahoo",
                                 "provisional": True}
            self.agent_push(f"handoff/{self.ds}/measurements.json", {"as_of": "x", "names": list(self.prep.values())},
                            message="prep")

    def push_draft(self, draft, name=None, raw=None):
        name = name or f"{draft['trade_id']}.draft.json"
        self.agent_push(f"inbox/{self.ds}/{name}", draft, raw=raw, message=f"draft {name}")

    def push_redteam(self, trade_id, flags=None, raw=None, **extra):
        rt = {"schema_version": "1.0.0", "trade_id": trade_id, "as_of": ct(8, 14, day=self.session).isoformat(),
              "flags": dict(FLAGS_NONE, **(flags or {})), "narrative": "Case against the trade."}
        rt.update(extra)
        self.agent_push(f"inbox/{self.ds}/{trade_id}.redteam.json", rt, raw=raw, message=f"redteam {trade_id}")

    def push_regime(self, **over):
        snap = json.loads((EXAMPLES / "regime_snapshot.json").read_text())
        snap["session_date"] = self.ds
        snap.update(over)
        self.agent_push(f"inbox/{self.ds}/regime_snapshot.json", snap, message="regime")

    def trade(self, n, ticker="XYZ", setup="catalyst_breakout", sector=None, bars=None, redteam=True, flags=None,
              **over):
        """Bars + prep + draft (+ red team) for one trade; returns the draft."""
        sector = sector or f"Sector{n}"
        builder = SETUP_PLANS[setup][0]
        bars = bars if bars is not None else builder(mc.previous_session(self.session))
        self.name(ticker, bars, sector)
        d = make_draft(n, ticker, setup, bars, sector, session=self.session, **over)
        self.push_draft(d)
        if redteam:
            self.push_redteam(d["trade_id"], flags=flags)
        return d

    def engine(self, **kw):
        kw.setdefault("clock", SessionClock(self.session))
        return Engine(self.mac, self.session, book_path=self.book_path, state_dir=self.state,
                      now_fn=lambda: self.now, sleep_fn=lambda s: None, bars_dir=self.bars_dir,
                      watchlist_path=self.watchlist, **kw)

    def remote_file(self, rel):
        proc = subprocess.run(["git", "show", f"main:{rel}"], cwd=str(self.remote), capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 else None

    def remote_ls(self, rel_dir):
        out = git(self.remote, "ls-tree", "-r", "--name-only", "main", "--", rel_dir)
        return [line for line in out.splitlines() if line]

    def card(self, key):
        raw = self.remote_file(f"handoff/{self.ds}/cards/{key}.json")
        return json.loads(raw) if raw else None

    def done(self):
        raw = self.remote_file(f"handoff/{self.ds}/cards/DONE")
        return json.loads(raw) if raw else None


def make_draft(n, ticker, setup, bars, sector, session=D, spread=0.04, **over):
    _builder, trigger, stop, target, level, base = SETUP_PLANS[setup]
    prev = mc.previous_session(session)
    latest = sg.bars_through(bars, prev.isoformat())
    mac = sg.core_measurements(latest, latest)
    d = json.loads((EXAMPLES / "trade_draft.json").read_text())
    entry = mc.next_session(prev) if mc.is_session(session) else session
    sessions = mc.sessions_between(entry, entry + timedelta(days=7))
    d.update({
        "trade_id": f"DF-{session.year}-{n:04d}", "ticker": ticker, "setup": setup,
        "entry": {"trigger": "buy_stop", "price": trigger}, "stop": stop,
        "targets": [{"price": target, "fraction": 1}], "invalidation_level": stop,
        "time_stop": {"max_calendar_days": 7, "entry_session_date": entry.isoformat(),
                      "exit_session_date": rm.time_stop_session(entry, sessions).isoformat()},
    })
    d["evidence"] = dict(d["evidence"], relative_volume=round(mac["relative_volume"], 3))
    d["catalyst"] = dict(d["catalyst"], observed_at=ct(17, 5, day=prev).isoformat())
    m = {"price": mac["price"], "atr": round(mac["atr"], 4), "adv_dollars": round(mac["adv_dollars"], 2),
         "spread": spread, "sector": sector, "reference_level": level, "signal_session": prev.isoformat()}
    if base is not None:
        m["base_level"] = base
    d["measurements"] = m
    for k, v in over.items():
        if k == "measurements":
            d["measurements"] = dict(d["measurements"], **v)
        else:
            d[k] = v
    return d


def option_overrides():
    return {"instrument": "call", "entry": {"trigger": "buy_limit", "price": 2.5}, "stop": 1.5,
            "targets": [{"price": 4.0, "fraction": 1}],
            "catalyst": dict(json.loads((EXAMPLES / "trade_draft.json").read_text())["catalyst"], earnings_in_window=True),
            "option": {"contract": "OPT 2026-10-16 85 C", "expiration": "2026-10-16", "bid": 2.45, "ask": 2.55,
                       "open_interest": 1200, "volume": 300, "underlying_stop": 80.75}}


def all_remote_cards_valid(w):
    for rel in w.remote_ls(f"handoff/{w.ds}/cards"):
        if rel.endswith(".json"):
            card = json.loads(w.remote_file(rel))
            errs = core.card_errors(card)
            check(not errs, f"schema-valid card {rel}: {errs}")


def reasons(card):
    return (card.get("risk_decision") or {}).get("reasons") or card["engine"]["reasons"]


# ---------------------------------------------------------------- unit: calendar, gates, freshness
def test_calendar():
    check(not mc.is_session(date(2026, 6, 19)) and mc.holiday_name(date(2026, 6, 19)).startswith("Juneteenth"), "Juneteenth closed")
    check(not mc.is_session(date(2026, 11, 26)) and not mc.is_session(date(2027, 12, 24)), "Thanksgiving / Christmas observed")
    check(mc.is_session(date(2026, 11, 27)) and mc.is_early_close(date(2026, 11, 27)), "day after Thanksgiving is an early close")
    check(mc.session_close(date(2026, 11, 27)).isoformat() == "2026-11-27T12:00:00-06:00", "early close 12:00 CT")
    check(mc.session_close(date(2026, 9, 25)).isoformat() == "2026-09-25T15:00:00-05:00", "regular close 15:00 CT")
    check(mc.previous_session(date(2026, 9, 8)) == date(2026, 9, 4), "Labor Day skipped")
    check(mc.previous_close(date(2026, 9, 28)).isoformat() == "2026-09-25T15:00:00-05:00", "Monday's previous close is Friday")
    check(len(mc.sessions_between(date(2026, 1, 1), date(2026, 12, 31))) == 251, "251 NYSE sessions in 2026")
    # time_stop_session over the static calendar: a Juneteenth deadline moves back a day
    entry = date(2026, 6, 12)
    exit_d = rm.time_stop_session(entry, mc.sessions_between(entry, entry + timedelta(days=7)))
    check(exit_d == date(2026, 6, 18), f"deadline 6/19 is a holiday -> exit Thursday 6/18 ({exit_d})")
    book = json.loads((EXAMPLES / "engine_book.json").read_text())
    good = make_draft(1, "XYZ", "catalyst_breakout", fx.breakout(date(2026, 6, 11)), "S", session=date(2026, 6, 12))
    check(good["time_stop"]["exit_session_date"] == "2026-06-18", "fixture uses the calendar")
    check(core.extra_validation(good, date(2026, 6, 12), book) == [], "exit 6/18 valid")
    bad = copy.deepcopy(good)
    bad["time_stop"]["exit_session_date"] = "2026-06-19"
    check("time_stop_invalid" in core.extra_validation(bad, date(2026, 6, 12), book), "exit on Juneteenth invalid")
    hol = copy.deepcopy(good)
    hol["time_stop"]["entry_session_date"] = "2026-06-19"
    check("time_stop_invalid" in core.extra_validation(hol, date(2026, 6, 12), book), "entry on a holiday invalid")
    try:
        mc.is_session(date(2029, 1, 2))
    except mc.CalendarNotCovered:
        check(True, "outside the tables fails closed")
    else:
        check(False, "2029 must raise CalendarNotCovered")


def test_book_freshness_unit():
    def fresh(as_of, session):
        return core.book_freshness({"as_of": as_of}, session)["fresh"]

    check(fresh("2026-09-25T15:00:00-05:00", D), "marked exactly at Friday's close is fresh")
    check(fresh("2026-09-25T16:00:00-04:00", D), "16:00 ET == 15:00 CT")
    check(not fresh("2026-09-25T14:59:00-05:00", D), "before Friday's close is stale")
    check(not fresh("2026-09-24T15:30:00-05:00", D), "Thursday's mark is stale on Monday")
    check(fresh("2026-09-04T15:30:00-05:00", date(2026, 9, 8)), "after Labor Day, Friday's mark is fresh")
    check(fresh("2026-11-27T12:05:00-06:00", date(2026, 11, 30)), "early close: 12:05 CT is fresh")
    check(not fresh("2026-11-27T11:55:00-06:00", date(2026, 11, 30)), "early close: 11:55 CT is stale")


def _gate(setup, bars, **kw):
    _b, trigger, stop, _t, level, base = SETUP_PLANS[setup]
    args = dict(entry_ref=trigger, level=level, atr_now=bars_mod.atr(bars), stop_underlying=stop, base_level=base)
    args.update(kw)
    return sg.evaluate(setup, bars, **args)[0]


def test_setup_gates_unit():
    E = PREV
    # A. catalyst_breakout
    check(_gate("catalyst_breakout", fx.breakout(E)) == [], "breakout passes")
    check(_gate("catalyst_breakout", fx.breakout(E, rvol=1.7)) == ["breakout_rvol_low"], "rvol 1.7 < 1.8 blocks")
    check(_gate("catalyst_breakout", fx.breakout(E, rvol=1.8)) == [], "rvol exactly 1.8 passes")
    check(_gate("catalyst_breakout", fx.breakout(E), level=84.4, entry_ref=84.5) == ["breakout_not_confirmed"],
          "close below the level: not confirmed")
    check(_gate("catalyst_breakout", fx.breakout(E), entry_ref=88.5) == ["breakout_entry_far"], "entry > 1.0 ATR from level")
    # B. momentum_pullback
    check(_gate("momentum_pullback", fx.pullback(E)) == [], "pullback passes")
    check("pullback_no_momentum" in _gate("momentum_pullback", fx.pullback(E, momentum=False, pull_closes=(84.8, 84.7, 84.6)),
                                          base_level=80.0), "no 8% return and no rising trend")
    check(_gate("momentum_pullback", fx.pullback(E, pull_closes=(90.6, 90.5, 90.4))) == ["pullback_depth_out_of_range"],
          "too shallow (< 0.4 ATR)")
    check(_gate("momentum_pullback", fx.pullback(E, pull_closes=(88.0, 87.0, 86.5))) == ["pullback_depth_out_of_range"],
          "too deep (> 1.5 ATR)")
    check(_gate("momentum_pullback", fx.pullback(E), base_level=89.2) == ["pullback_broke_base"], "closed through the base")
    check(_gate("momentum_pullback", fx.pullback(E, pull_volume=2.5e6)) == ["pullback_volume_not_lower"],
          "pullback volume not below impulse")
    check(_gate("momentum_pullback", fx.pullback(E, formed=False)) == ["pullback_not_formed"], "swing high is the signal bar")
    # C. failed_breakdown
    check(_gate("failed_breakdown", fx.failed_breakdown(E)) == [], "failed breakdown passes")
    check(_gate("failed_breakdown", fx.failed_breakdown(E, window_low=79.6, reversal_low=79.6)) == ["breakdown_not_found"],
          "support never broken")
    check(_gate("failed_breakdown", fx.failed_breakdown(E, reversal_close=79.4)) == ["reclaim_not_confirmed"], "no reclaim")
    check(_gate("failed_breakdown", fx.failed_breakdown(E, reversal_volume=2.9e6)) == ["reversal_rvol_low"], "rvol < 1.5")
    check(_gate("failed_breakdown", fx.failed_breakdown(E), stop_underlying=79.3) == ["stop_not_below_reversal_bar"],
          "stop above the reversal low")
    # D. compression_expansion
    check(_gate("compression_expansion", fx.compression(E)) == [], "compression passes")
    check("no_compression" in _gate("compression_expansion", fx.compression(E, tight_half=3.0, exp_low=76.0, exp_high=86.0,
                                                                          exp_close=85.0), stop_underlying=76.5),
          "no lowest-quartile range")
    check(_gate("compression_expansion", fx.compression(E, exp_low=80.6, exp_high=82.6)) == ["expansion_range_small"],
          "expansion range <= 1.5x")
    check(_gate("compression_expansion", fx.compression(E, exp_volume=2.0e6)) == ["expansion_rvol_low"], "expansion rvol < 1.5")
    check(_gate("compression_expansion", fx.compression(E, exp_close=79.9, exp_low=78.9, exp_high=81.9),
                stop_underlying=78.0) == ["expansion_not_up"], "expansion down")
    check(_gate("compression_expansion", fx.compression(E), stop_underlying=79.5) == ["stop_not_outside_compression"],
          "stop inside the compression range")
    # every gate code is exercised above
    check(len(sg.ALL_GATE_BLOCKS) == 17, "17 gate codes")
    try:
        _gate("compression_expansion", fx.compression(E)[-40:])
    except sg.MeasurementUnavailable:
        check(True, "short history -> unavailable")
    else:
        check(False, "short history must raise")
    check(sg.within("atr", 4.0, 4.19) and not sg.within("atr", 4.0, 4.3), "ATR 5% tolerance")
    check(sg.within("spread", 0.04, 0.05) and not sg.within("spread", 0.04, 0.06), "spread $0.01 tolerance")


# ---------------------------------------------------------------- engine
def test_sized_card():
    w = World("sized")
    w.push_regime()
    w.trade(1)
    w.now = ct(8, 14)
    res = w.engine().run_pass()
    check(res["written"] == ["DF-2026-0001"], f"one card written {res}")
    check(res["done"] is None, "no DONE before cutoff")
    card = w.card("DF-2026-0001")
    check(card["status"] == "pending_human", f"approved card waits on Jared: {reasons(card)}")
    check(card["risk_decision"] == {"decision": "APPROVED", "reasons": [], "risk_mode": "normal", "entries_allowed": True},
          "risk_decision copied from the governor")
    s = card["sizing"]
    check(s["units"] == 171 and s["planned_loss"] == 663.48 and s["heat_contribution"] == 995.22,
          f"canonical size 171 / 663.48 / 995.22: {s}")
    check(s["notional"] == 14471.73 and s["expected_r"] == 1.6418 and s["initial_risk"] == 663.48, "canonical notional/R")
    check(card["entry"]["max_fill"] == 84.63, "max_fill from max_buy_fill")
    check(card["frozen_at"] and card["created_at"].endswith("-05:00"), "frozen, CT-aware timestamps")
    check(card["red_team"] == {"decision": "pass", "hard_blocks": [], "warnings": [], "narrative": "Case against the trade."},
          "red team section from the red team file")
    eng = card["engine"]
    check(eng["outcome"] == "sized" and eng["first_seen_at"] == ct(8, 14).isoformat(), "engine block")
    mv = eng["inputs"]["measurements"]
    check(mv["details"]["sources"]["bars"] == "bars_cache:XYZ.json" and mv["details"]["mismatches"] == [],
          "measurements recomputed from the Mac bars cache")
    check(mv["values"]["price"] == 84.3 and mv["details"]["gates"]["rvol"] == 2.4, "Mac values recorded")
    check(eng["inputs"]["redteam"]["warning_count_source"] == "derived_from_flags", "warning_count derived by the engine")
    check(eng["inputs"]["market_data_network_calls"] == 0, "no market data calls")
    check(not core.card_errors(card), "schema valid")


def test_redteam_gating():
    w = World("redteam")
    w.push_regime()
    d1 = w.trade(1, redteam=False)
    w.now = ct(8, 13)
    eng = w.engine()
    r = eng.run_pass()
    check(r["pending"] == ["DF-2026-0001"] and r["written"] == [] and w.card("DF-2026-0001") is None,
          "no red team file -> not sized, no card yet")
    w.push_redteam(d1["trade_id"])
    w.now = ct(8, 14)
    r = eng.run_pass()
    c1 = w.card("DF-2026-0001")
    check(r["written"] == ["DF-2026-0001"] and c1["engine"]["outcome"] == "sized", "sized a minute after the red team file")
    check(c1["engine"]["inputs"]["redteam"]["first_valid_at"] == ct(8, 14).isoformat(), "red team timing recorded")

    # two warnings -> cautious name caps through caps(warning_count)
    w.trade(2, ticker="TWO", flags={"crowded_options": True, "gap_history": True})
    # red team tries to block and size: ignored for that purpose, logged; claimed count ignored
    w.trade(3, ticker="THR", setup="failed_breakdown", redteam=False)
    LOG.truncate(0)
    LOG.seek(0)
    w.push_redteam("DF-2026-0003", hard_blocks=["i_say_no"], decision="block", sizing={"units": 5}, warning_count=4)
    w.now = ct(8, 16)
    eng.run_pass()
    c2 = w.card("DF-2026-0002")
    s2 = c2["sizing"]
    check(c2["status"] == "pending_human" and s2["name_heat_cap"] == 500 and s2["book_heat_cap"] == 2000,
          f"2 warnings pull the name cap to cautious, book cap unchanged: {s2}")
    check(s2["units"] == 85 and s2["planned_loss"] == 329.8, f"size under cautious name cap: {s2}")
    check(c2["red_team"]["warnings"] == ["crowded_options", "gap_history"] and c2["engine"]["inputs"]["warning_count"] == 2,
          "warnings copied, warning_count 2")
    check(c2["engine"]["inputs"]["warnings_tightened"] is True, "governor reports warnings_tightened")
    c3 = w.card("DF-2026-0003")
    check(c3["status"] == "pending_human" and c3["red_team"]["hard_blocks"] == [] and c3["red_team"]["decision"] == "pass",
          f"red team block ignored: {reasons(c3)}")
    rt3 = c3["engine"]["inputs"]["redteam"]
    check(set(rt3["ignored_fields"]) == {"hard_blocks", "decision", "sizing"} and rt3["warning_count"] == 0
          and rt3["warning_count_claimed"] == 4, "ignored fields and claimed count recorded; derived count used")
    check("tried to set" in LOG.getvalue() and "claims warning_count 4" in LOG.getvalue(), "ignored red team fields logged")
    check(c3["sizing"]["name_heat_cap"] == 1000, "claimed warning_count did not tighten or loosen")

    # a review of a different draft version is stale: the draft waits
    d4 = w.trade(4, ticker="FOU", redteam=False)
    w.push_redteam(d4["trade_id"], draft_sha256="0" * 64)
    w.now = ct(8, 17)
    r = eng.run_pass()
    check("DF-2026-0004" in r["pending"], "red team pinned to another draft sha is not accepted")
    all_remote_cards_valid(w)


def test_late_redteam_and_done_mixed():
    w = World("late")
    w.push_regime()
    w.trade(1)
    w.trade(2, ticker="BLK", catalyst=dict(json.loads((EXAMPLES / "trade_draft.json").read_text())["catalyst"],
                                           quality="absent", source_type="none"))
    d3 = w.trade(3, ticker="LRT", redteam=False)
    w.trade(4, ticker="NRT", redteam=False)
    w.now = ct(8, 19)
    eng = w.engine()
    eng.run_pass()
    w.now = ct(8, 20)  # the cutoff pass is on time and writes no DONE
    r = eng.run_pass()
    check(r["done"] is None and w.done() is None, "no DONE at the cutoff instant")
    check(set(r["pending"]) == {"DF-2026-0003", "DF-2026-0004"}, "two drafts still waiting on red team at 08:20")
    w.push_redteam(d3["trade_id"])  # lands 08:20:30
    w.push_draft(make_draft(5, "LDR", "catalyst_breakout", fx.breakout(PREV), "Energy"))
    w.now = ct(8, 21)
    r = eng.run_pass()
    c3, c4, c5 = w.card("DF-2026-0003"), w.card("DF-2026-0004"), w.card("DF-2026-0005")
    check(c3["engine"]["outcome"] == "late" and c3["engine"]["reasons"] == ["late_redteam"], "late red team -> late card")
    check(c3["risk_decision"] is None and c3["sizing"]["units"] == 0 and c3["status"] == "blocked", "late card unsized")
    check(c4["engine"]["reasons"] == ["late_redteam"], "no red team at all -> late at the first post-cutoff pass")
    check(c5["engine"]["reasons"] == ["late_draft"], "draft first seen after the cutoff -> late")
    done = w.done()
    check(done["counts"] == {"drafts": 5, "sized": 1, "rejected": 1, "late": 3}, f"mixed counts {done['counts']}")
    check(done["trade_ids"] == {"sized": ["DF-2026-0001"], "rejected": ["DF-2026-0002"],
                                "late": ["DF-2026-0003", "DF-2026-0004", "DF-2026-0005"]}, "trade ids by outcome")
    check(done["finalized_by"] == "cutoff" and done["revision"] == 1 and done["as_of"].endswith("-05:00"), "DONE meta")
    check(not core.schema_errors("engine_done.schema.json", done), "DONE schema valid")
    c2 = w.card("DF-2026-0002")
    check(c2["status"] == "blocked" and "catalyst_insufficient" in c2["red_team"]["hard_blocks"]
          and c2["red_team"]["decision"] == "block", "structural block recorded as the engine's hard block")
    w.now = ct(8, 22)
    check(eng.run_pass()["done"] is None, "no DONE rewrite without changes")
    w.push_draft(make_draft(6, "LD2", "catalyst_breakout", fx.breakout(PREV), "Utilities"))
    w.now = ct(8, 23)
    eng.run_pass()
    check(w.done()["revision"] == 2 and w.done()["counts"]["late"] == 4, "DONE revised for a later late card")
    all_remote_cards_valid(w)


def test_rejections():
    w = World("reject")
    w.push_regime()
    ex_card = json.loads((EXAMPLES / "trade_card.json").read_text())
    bars = fx.breakout(PREV)
    w.name("XYZ", bars, "Industrials")
    base = lambda n, **o: make_draft(n, "XYZ", "catalyst_breakout", bars, "Industrials", **o)  # noqa: E731
    w.push_draft(base(3, sizing=ex_card["sizing"]))
    w.push_draft(base(4, risk_decision=ex_card["risk_decision"]))
    d5 = base(5)
    d5["entry"] = {"trigger": "buy_stop", "price": 84.5, "max_fill": 99.0}
    w.push_draft(d5)
    bad = base(6)
    del bad["why_now"]
    w.push_draft(bad)
    w.push_draft(None, name="DF-2026-0007.draft.json", raw="{not json")
    noid = base(8)
    del noid["trade_id"]
    w.push_draft(noid, name="architect-oops.draft.json")
    w.push_draft(base(9, targets=[{"price": 86.0, "fraction": 1}]))
    w.push_redteam("DF-2026-0009")
    w.now = ct(8, 16)
    res = w.engine().run_pass()
    check(len(res["written"]) == 7, f"invalid / pre-sized rejected without waiting for red team {res['written']}")
    c3 = w.card("DF-2026-0003")
    check("draft_carries_sizing" in reasons(c3) and c3["sizing"]["units"] == 0, "pre-sized draft rejected, not copied")
    check(c3["red_team"]["narrative"].startswith("No red team review"), "no red team review on a pre-governor reject")
    check("draft_carries_risk_decision" in reasons(w.card("DF-2026-0004")), "draft risk_decision rejected")
    c5 = w.card("DF-2026-0005")
    check("draft_carries_max_fill" in reasons(c5) and c5["entry"]["max_fill"] == 84.63, "draft max_fill rejected")
    c6 = w.card("DF-2026-0006")
    check(c6["record"] == "engine_reject" and any("why_now" in r for r in reasons(c6)), "invalid draft -> reject record")
    check(reasons(w.card("DF-2026-0007")) == ["draft_not_json_object"], "non-JSON draft")
    unid = w.card("unidentified/architect-oops")
    check(unid and unid["trade_id"] is None and "trade_id_missing" in reasons(unid), "no trade_id -> unidentified/")
    c9 = w.card("DF-2026-0009")
    check(c9["status"] == "risk_rejected" and "reward_risk_below_minimum" in reasons(c9), "governor rejection")
    all_remote_cards_valid(w)
    # a rejected card is never re-sized, even if the draft is fixed later
    w.push_draft(base(3))
    w.now = ct(8, 17)
    res2 = w.engine().run_pass()
    check(res2["written"] == [] and res2["frozen_changed"] == ["DF-2026-0003"], "fixed draft does not re-size")


def test_setup_gates_engine():
    w = World("gates")
    w.push_regime()
    for n, setup in enumerate(("catalyst_breakout", "momentum_pullback", "failed_breakdown", "compression_expansion"), 1):
        w.trade(n, ticker=f"T{n}", setup=setup)
    # failing versions, one per setup
    w.trade(11, ticker="F1", setup="catalyst_breakout", bars=fx.breakout(PREV, rvol=1.5))
    w.trade(12, ticker="F2", setup="momentum_pullback", bars=fx.pullback(PREV, pull_volume=2.5e6))
    w.trade(13, ticker="F3", setup="failed_breakdown", bars=fx.failed_breakdown(PREV, reversal_close=79.4),
            measurements={"price": 79.4})
    w.trade(14, ticker="F4", setup="compression_expansion", bars=fx.compression(PREV), stop=79.5, invalidation_level=79.5)
    w.book_path.write_text(json.dumps(dict(json.loads(w.book_path.read_text()), equity=1000000, cash=1000000)))
    w.now = ct(8, 17)
    w.engine().run_pass()
    for n, setup in enumerate(("catalyst_breakout", "momentum_pullback", "failed_breakdown", "compression_expansion"), 1):
        c = w.card(f"DF-2026-{n:04d}")
        # all four in one book: the 4th may hit book heat (size_zero), but none may carry a gate block
        check(c["red_team"]["hard_blocks"] == [] and c["engine"]["inputs"]["measurements"]["details"]["gates"]
              and (n == 4 or c["engine"]["outcome"] == "sized"),
              f"{setup} passes every gate: {reasons(c)}")
    expect = {11: "breakout_rvol_low", 12: "pullback_volume_not_lower", 13: "reclaim_not_confirmed",
              14: "stop_not_outside_compression"}
    for n, code in expect.items():
        c = w.card(f"DF-2026-{n:04d}")
        check(c["status"] == "blocked" and code in c["red_team"]["hard_blocks"] and code in reasons(c),
              f"gate {code} recorded as a structural block: {reasons(c)}")
    all_remote_cards_valid(w)


def test_measurements():
    w = World("measure")
    w.push_regime()
    bars = fx.breakout(PREV)
    # mismatch: draft ATR 10% off the Mac's
    w.trade(1, ticker="MIS", measurements={"atr": 4.5})
    # unavailable: no bars cache and no prep bars
    w.name("NOB", bars, "Energy", cache=False)
    w.push_draft(make_draft(2, "NOB", "catalyst_breakout", bars, "Energy"))
    w.push_redteam("DF-2026-0002")
    # unavailable: cache stale (ends the session before the previous one)
    w.name("STL", [b for b in bars if b["date"] < PREV.isoformat()], "Industrials")
    w.push_draft(make_draft(3, "STL", "catalyst_breakout", bars, "Industrials"))
    w.push_redteam("DF-2026-0003")
    # unavailable: stock with no spread anywhere
    w.name("NSP", bars, "Materials", spread=None)
    w.push_draft(make_draft(4, "NSP", "catalyst_breakout", bars, "Materials"))
    w.push_redteam("DF-2026-0004")
    # watchlist fallback for sector + spread; prep 'bars' fallback when the cache is missing
    w.watchlist.write_text(json.dumps({"provisional": True, "names": [{"ticker": "WLF", "sector": "Health Care", "spread": 0.03}]}))
    (w.bars_dir / "WLF.json").write_text(json.dumps({"bars": bars}))
    w.push_draft(make_draft(5, "WLF", "catalyst_breakout", bars, "Health Care", spread=0.03))
    w.push_redteam("DF-2026-0005")
    w.prep["PBR"] = {"ticker": "PBR", "sector": "Real Estate", "spread": 0.04, "bars": bars}
    w.agent_push(f"handoff/{DS}/measurements.json", {"names": list(w.prep.values())})
    w.push_draft(make_draft(6, "PBR", "catalyst_breakout", bars, "Real Estate"))
    w.push_redteam("DF-2026-0006")
    # sector lie: draft claims a different sector than the Mac's
    w.trade(7, ticker="SEC", sector="Utilities", measurements={"sector": "Financials"})
    w.now = ct(8, 17)
    w.engine().run_pass()
    c1 = w.card("DF-2026-0001")
    mm = c1["engine"]["inputs"]["measurements"]["details"]["mismatches"]
    check("measurement_mismatch" in reasons(c1) and mm and mm[0]["field"] == "atr", f"ATR mismatch blocks: {mm}")
    check(c1["sizing"]["units"] == 0, "mismatch never sized")
    for n, why in ((2, "no cache"), (3, "cache stale"), (4, "spread")):
        c = w.card(f"DF-2026-{n:04d}")
        check("measurement_unavailable" in reasons(c) and c["sizing"]["units"] == 0, f"measurement_unavailable ({why})")
        check(any(why.split()[0] in u for u in c["engine"]["inputs"]["measurements"]["details"]["unavailable"]),
              f"unavailable detail names {why}")
    c5 = w.card("DF-2026-0005")
    check(c5["engine"]["outcome"] == "sized" and c5["engine"]["inputs"]["measurements"]["details"]["sources"]["sector"]
          == "dragonfly/watchlist.json", f"watchlist fallback: {reasons(c5)}")
    c6 = w.card("DF-2026-0006")
    check(c6["engine"]["outcome"] == "sized" and c6["engine"]["inputs"]["measurements"]["details"]["sources"]["bars"]
          == "prep_bars", f"prep bars fallback: {reasons(c6)}")
    c7 = w.card("DF-2026-0007")
    check("measurement_mismatch" in reasons(c7), "draft sector disagreeing with the Mac blocks")
    all_remote_cards_valid(w)

    book = json.loads((EXAMPLES / "engine_book.json").read_text())
    book.update(book="live", as_of="2026-09-25T15:30:00-05:00")
    w2 = World("live", book=book)
    w2.push_regime()
    w2.trade(2, book="live", measurements={"provisional": False})
    w2.now = ct(8, 15)
    w2.engine().run_pass()
    check("provisional_source_live" in reasons(w2.card("DF-2026-0002")),
          "live book blocks Yahoo bars even when the draft claims provisional=false")


def test_book_stale():
    book = json.loads((EXAMPLES / "engine_book.json").read_text())
    book["as_of"] = "2026-09-25T14:30:00-05:00"  # before Friday's 15:00 CT close
    w = World("stale", book=book)
    w.push_regime()
    w.trade(1)
    w.trade(2, ticker="NRT", redteam=False)
    w.now = ct(8, 14)
    w.engine().run_pass()
    for n in (1, 2):
        c = w.card(f"DF-2026-{n:04d}")
        check(c["status"] == "blocked" and reasons(c) == ["book_stale"] and c["sizing"]["units"] == 0,
              f"book_stale blocks every draft, red team or not ({n})")
        check(c["red_team"]["hard_blocks"] == ["book_stale"], "book_stale is an engine hard block")
    fr = w.card("DF-2026-0001")["engine"]["inputs"]["book_freshness"]
    check(fr["required_at_or_after"] == "2026-09-25T15:00:00-05:00", "requirement recorded")


def test_holiday_engine():
    j = date(2026, 6, 19)
    w = World("holiday", session=j)
    w.agent_push(f"inbox/{j.isoformat()}/DF-2026-0001.draft.json", {"trade_id": "DF-2026-0001"})
    w.now = ct(8, 15, day=j)
    r = w.engine().run_pass()
    check(r["not_session"] and r["written"] == [], "no pass on Juneteenth")
    w.now = ct(8, 8, day=j)
    check(w.engine().run_loop() == 0 and w.done() is None, "holiday loop exits 0 without DONE")


def test_frozen_idempotency():
    w = World("frozen")
    w.push_regime()
    d = w.trade(1)
    w.now = ct(8, 12)
    eng = w.engine()
    eng.run_pass()
    before = w.remote_file(f"handoff/{DS}/cards/DF-2026-0001.json")
    head = git(w.remote, "rev-parse", "main").strip()
    w.now = ct(8, 13)
    r = eng.run_pass()
    check(r["written"] == [] and not r["pushed"], "second poll writes nothing")
    check(git(w.remote, "rev-parse", "main").strip() == head, "no new commit on an idle poll")
    d2 = copy.deepcopy(d)
    d2["stop"] = 82.0
    w.push_draft(d2)
    w.push_redteam("DF-2026-0001", flags={"crowded_options": True, "gap_history": True})
    LOG.truncate(0)
    LOG.seek(0)
    w.now = ct(8, 14)
    r = eng.run_pass()
    check(r["frozen_changed"] == ["DF-2026-0001"] and "is frozen" in LOG.getvalue(), "draft change noticed and logged")
    check(w.remote_file(f"handoff/{DS}/cards/DF-2026-0001.json") == before, "frozen card byte-identical (no v2)")
    w.now = ct(8, 15)
    LOG.truncate(0)
    LOG.seek(0)
    check(eng.run_pass()["frozen_changed"] == [] and "is frozen" not in LOG.getvalue(), "logged once")
    shutil.rmtree(w.state / "engine")
    w.now = ct(8, 21)
    r = w.engine().run_pass()
    check(r["written"] == [] and w.done()["counts"]["sized"] == 1, "state loss does not re-card; DONE")


def test_done_zero_and_finalize():
    w = World("zero")
    w.now = ct(8, 21)
    r = w.engine().run_pass()
    done = w.done()
    check(done and done["counts"] == {"drafts": 0, "sized": 0, "rejected": 0, "late": 0} and r["pushed"], "DONE, zero drafts")
    w2 = World("finalize")
    w2.push_regime()
    w2.trade(1)
    w2.trade(2, ticker="NRT", redteam=False)
    w2.now = ct(8, 15)
    check(w2.engine().run_pass()["done"] is None and w2.done() is None, "no DONE before cutoff")
    w2.now = ct(8, 16)
    w2.engine(finalize=True).run_pass()
    d = w2.done()
    check(d and d["finalized_by"] == "flag" and d["counts"] == {"drafts": 2, "sized": 1, "rejected": 0, "late": 1},
          f"--finalize: DONE early, unreviewed draft late {d and d['counts']}")


def test_regime_pending_then_cutoff():
    w = World("regime")
    w.trade(1)
    w.now = ct(8, 13)
    eng = w.engine()
    r = eng.run_pass()
    check(r["pending"] == ["DF-2026-0001"] and r["written"] == [], "waits for the regime snapshot")
    w.now = ct(8, 21)
    eng.run_pass()
    c = w.card("DF-2026-0001")
    check(c["risk_decision"]["risk_mode"] == "stand_down" and "regime_missing" in reasons(c)
          and "stand_down" in reasons(c), "no regime after cutoff fails closed to stand_down")
    check(w.done()["counts"]["rejected"] == 1, "then DONE")


def test_pending_heat_sector_and_option():
    w = World("heat")
    w.push_regime()
    w.trade(1, sector="Industrials")
    w.trade(2, ticker="ABC", sector="Energy")
    w.trade(3, ticker="DEF", sector="Energy")
    w.trade(4, ticker="GHI", setup="momentum_pullback", sector="Materials")
    w.trade(6, ticker="JKL", setup="failed_breakdown", sector="Utilities")
    w.trade(7, ticker="MNO", sector="Financials")
    w.now = ct(8, 15)
    w.engine().run_pass()
    c2 = w.card("DF-2026-0002")
    check(c2["sizing"]["open_heat_before"] == 995.22 and c2["sizing"]["units"] == 171, "pending heat counts")
    check("sector_occupied" in reasons(w.card("DF-2026-0003")), "pending card occupies its sector")
    c4 = w.card("DF-2026-0004")
    check(c4["sizing"]["open_heat_before"] == 1990.44 and c4["sizing"]["units"] >= 1, f"known Phase 1 crumb {c4['sizing']}")
    c6 = w.card("DF-2026-0006")
    check(c6["status"] == "risk_rejected" and set(reasons(c6)) & {"heat_exhausted", "size_zero"}, f"heat exhausted {reasons(c6)}")
    check("setup_cap" in reasons(w.card("DF-2026-0007")), "two pending breakouts hit the setup cap")

    w2 = World("option")
    w2.push_regime()
    w2.trade(5, ticker="OPT", sector="Health Care", **option_overrides())
    w2.now = ct(8, 15)
    w2.engine().run_pass()
    c = w2.card("DF-2026-0005")
    s = c["sizing"]
    check(c["status"] == "pending_human" and s["units"] == 4 and s["planned_loss"] == 400 and s["heat_contribution"] == 1000,
          f"plan option example: 4 contracts: {s} {reasons(c)}")
    st = c["engine"]["inputs"]["structural"]
    check(st["extension_atr"] == "0.0246" and st["stop_distance_atr"] == "0.8719",
          f"option ATR measured on the underlying (contract): {st['extension_atr']} {st['stop_distance_atr']}")
    all_remote_cards_valid(w)
    all_remote_cards_valid(w2)


def test_window_closed_and_book_errors():
    w = World("closed")
    w.trade(1)
    w.now = ct(8, 15)
    eng = w.engine()
    eng.run_pass()  # pending: no regime
    w.push_regime()
    w.now = ct(9, 5)
    eng.run_pass()
    c = w.card("DF-2026-0001")
    check(reasons(c) == ["engine_window_closed"] and c["sizing"]["units"] == 0, "nothing sized after the window")
    w2 = World("nobook")
    w2.book_path.unlink()
    w2.push_regime()
    w2.trade(1)
    w2.now = ct(8, 15)
    try:
        w2.engine().run_pass()
    except EngineError as exc:
        check("book state not found" in str(exc), "missing book is a loud error")
    else:
        check(False, "missing book must raise")
    check(w2.card("DF-2026-0001") is None, "nothing written without a book")


def test_fail_closed_schema():
    w = World("failclosed")
    w.push_regime()
    w.trade(1)
    w.now = ct(8, 15)
    real = core.card_errors

    def flaky(card):
        if card.get("record") != "engine_reject":
            return ["$: injected schema failure"]
        return real(card)

    core.card_errors = flaky
    try:
        w.engine().run_pass()
    finally:
        core.card_errors = real
    c = w.card("DF-2026-0001")
    check(c["record"] == "engine_reject" and "card_schema_invalid" in reasons(c), "schema-invalid card -> reject record")
    check(not core.card_errors(c), "fallback record is schema valid")


def test_push_retry_and_sync():
    w = World("git")
    repo = PrivateRepo(w.mac, sleep=lambda s: None)
    check(repo.sync() is False, "no pull when the remote ref did not move")
    w.agent_push(f"inbox/{DS}/x.draft.json", {"a": 1})
    check(repo.sync() is True and (w.mac / f"inbox/{DS}/x.draft.json").exists(), "pull when the ref moved")
    p = w.mac / f"handoff/{DS}/cards/X.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}\n")
    w.agent_push(f"inbox/{DS}/y.draft.json", {"a": 2})
    repo.commit_and_push([f"handoff/{DS}/cards"], "test card")
    check(w.remote_file(f"handoff/{DS}/cards/X.json") == "{}\n", "card pushed after rebase")
    check(w.remote_file(f"inbox/{DS}/y.draft.json") is not None, "agent commit preserved")
    check(git(w.remote, "log", "--format=%s", "main").splitlines()[0] == "test card", "rebased on top")


def test_loop_timeline():
    w = World("loop")
    w.push_regime()
    bars = fx.breakout(PREV)
    w.name("XYZ", bars, "Industrials")
    w.name("LTE", bars, "Energy")
    w.name("NRT", bars, "Utilities")
    d1 = make_draft(1, "XYZ", "catalyst_breakout", bars, "Industrials")
    d2 = make_draft(2, "LTE", "catalyst_breakout", bars, "Energy")
    d3 = make_draft(3, "NRT", "catalyst_breakout", bars, "Utilities")
    w.now = ct(8, 8)
    passes = []
    events = {ct(8, 11, 30): lambda: w.push_draft(d1),
              ct(8, 12, 10): lambda: w.push_draft(d2),
              ct(8, 13, 20): lambda: w.push_draft(d3),
              ct(8, 14, 10): lambda: w.push_redteam(d1["trade_id"]),
              ct(8, 20, 30): lambda: w.push_redteam(d2["trade_id"])}

    def sleep(seconds):
        target = w.now + timedelta(seconds=seconds)
        for at in sorted(events):
            if w.now < at <= target:
                w.now = at
                events.pop(at)()
        w.now = target

    eng = Engine(w.mac, D, book_path=w.book_path, state_dir=w.state, now_fn=lambda: w.now, sleep_fn=sleep,
                 bars_dir=w.bars_dir, watchlist_path=w.watchlist)
    real_pass = eng.run_pass

    def spy(tick=None):
        passes.append(tick)
        return real_pass(tick)

    eng.run_pass = spy
    check(eng.run_loop() == 0, "loop exits 0 with DONE")
    check(passes[0] == ct(8, 8) and passes[-1] == ct(8, 24) and ct(8, 20) in passes and len(passes) == 17,
          f"polls 08:08-08:24 every 60 s incl. the 08:20 cutoff ({len(passes)})")
    c1, c2, c3 = (w.card(f"DF-2026-000{i}") for i in (1, 2, 3))
    check(c1["engine"]["outcome"] == "sized" and c1["engine"]["carded_at"] == ct(8, 15).isoformat(),
          "sized about a minute after its red team file (08:14:10 -> 08:15)")
    check(c2["engine"]["reasons"] == ["late_redteam"] and c2["engine"]["carded_at"] == ct(8, 21).isoformat(),
          "red team at 08:20:30 -> late")
    check(c3["engine"]["reasons"] == ["late_redteam"], "never reviewed -> late")
    done = w.done()
    check(done["counts"] == {"drafts": 3, "sized": 1, "rejected": 0, "late": 2}, "DONE from the loop")
    check(core.parse_iso(done["as_of"]) <= ct(8, 24), "DONE landed by 08:24")
    w2 = World("loop2")
    w2.now = ct(8, 1)
    eng2 = Engine(w2.mac, D, book_path=w2.book_path, state_dir=w2.state, now_fn=lambda: w2.now,
                  sleep_fn=lambda s: setattr(w2, "now", w2.now + timedelta(seconds=s)), bars_dir=w2.bars_dir)
    check(eng2.run_loop() == 0 and w2.done()["counts"]["drafts"] == 0, "zero-draft loop writes DONE")


def test_ready_marker():
    w = World("ready")
    w.agent_push(f"handoff/{DS}/manifest.json", {"as_of": "x"})
    git(w.mac, "pull", "--quiet", "--rebase", "origin", "main")
    (w.mac / f"handoff/{DS}/regime_inputs.json").write_text("{}\n")
    try:
        write_ready(w.mac, D, now=ct(8, 6))
    except EngineError as exc:
        check("not committed" in str(exc), "READY refuses while handoff files are uncommitted")
    else:
        check(False, "READY must refuse a dirty handoff")
    check(w.remote_file(f"handoff/{DS}/READY") is None, "no READY pushed")
    git(w.mac, "add", "-A")
    git(w.mac, "commit", "--quiet", "-m", "prep")
    doc = write_ready(w.mac, D, now=ct(8, 6, 30))
    ready = json.loads(w.remote_file(f"handoff/{DS}/READY"))
    check(ready == doc and ready["as_of"] == "2026-09-28T08:06:30-05:00", "READY pushed")
    check([f["path"] for f in ready["files"]] == ["manifest.json", "regime_inputs.json"], "READY lists handoff files")
    check(all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in ready["files"]), "file hashes and sizes")
    log = git(w.remote, "log", "--format=%s", "main").splitlines()
    check(log[0].startswith("pre-open") and log[1] == "prep", "READY is the last commit")
    check(not core.schema_errors("engine_ready.schema.json", ready), "READY schema valid")
    w2 = World("ready-empty")
    (w2.mac / f"handoff/{DS}").mkdir(parents=True)
    try:
        write_ready(w2.mac, D, now=ct(8, 6))
    except EngineError as exc:
        check("no files" in str(exc), "READY refuses an empty handoff")


def _quiet_cli(argv):
    buf = io.StringIO()
    old = sys.stdout
    logger = logging.getLogger("dragonfly.engine")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    old_err = sys.stderr
    sys.stdout, sys.stderr = buf, io.StringIO()
    try:
        rc = cli_main(argv)
    finally:
        sys.stdout, sys.stderr = old, old_err
        logger.handlers[:], logger.level, logger.propagate = saved[0], saved[1], saved[2]
    return rc, buf.getvalue()


def test_cli_once():
    w = World("cli")
    w.push_regime()
    w.trade(1)
    rc, out = _quiet_cli(["run", "--once", "--repo", str(w.mac), "--date", DS, "--book", str(w.book_path),
                          "--state-dir", str(w.state), "--bars-dir", str(w.bars_dir), "--now", ct(8, 22).isoformat()])
    out = json.loads(out)
    check(rc == 0 and out["written"] == ["DF-2026-0001"] and out["done"] is True, f"CLI --once {out}")
    check(w.card("DF-2026-0001")["engine"]["outcome"] == "late", "first seen after cutoff -> late")
    w2 = World("cli-dry")
    w2.push_regime()
    w2.trade(2)
    head = git(w2.remote, "rev-parse", "main").strip()
    common = ["run", "--once", "--no-push", "--repo", str(w2.mac), "--date", DS, "--book", str(w2.book_path),
              "--state-dir", str(w2.state), "--bars-dir", str(w2.bars_dir)]
    rc, _ = _quiet_cli(common + ["--now", ct(8, 15).isoformat()])
    rc2, _ = _quiet_cli(common + ["--now", ct(8, 21).isoformat()])
    check(rc == 0 and rc2 == 0, "dry-run passes succeed")
    card = json.loads((w2.mac / f"handoff/{DS}/cards/DF-2026-0002.json").read_text())
    check(card["engine"]["outcome"] == "sized" and (w2.mac / f"handoff/{DS}/cards/DONE").exists(), "dry run writes locally")
    check(git(w2.remote, "rev-parse", "main").strip() == head and git(w2.mac, "rev-parse", "HEAD").strip() == head,
          "dry run commits and pushes nothing")


def test_guards_and_network():
    check(guards.pipeline_busy() is not None, "pipeline lock is held for this test")
    w = World("guards")
    w.push_regime()
    w.trade(1)
    w.now = ct(7, 30)  # inside the 05:00-07:59 daemon window
    w.engine(finalize=True).run_pass()
    check(w.card("DF-2026-0001")["engine"]["outcome"] == "sized", "engine ran under a held lock in a daemon window")
    for mod in ("yfinance", "dragonfly.chains", "dragonfly.build_watchlist", "requests", "urllib3"):
        check(mod not in sys.modules, f"{mod} never imported")
    pat = re.compile(r"^\s*(?:from|import)\s+(yfinance|requests|urllib|http|socket|"
                     r"dragonfly\.(?:chains|build_watchlist|guards))\b|from dragonfly import .*\b(chains|build_watchlist|guards)\b"
                     r"|yahoo_history|ticker_metrics|\brefresh\(|save_cache", re.M)
    srcs = sorted((ROOT / "dragonfly" / "engine").glob("*.py")) + [ROOT / "dragonfly" / "setup_gates.py",
                                                                   ROOT / "dragonfly" / "market_calendar.py"]
    for src in srcs:
        check(not pat.search(src.read_text()), f"{src.name}: no network, no fetchers, no cache writes")


def test_ops_templates():
    import plistlib

    ops = ROOT / "dragonfly" / "ops"
    plist = (ops / "com.dragonfly.engine.plist.template").read_text()
    parsed = plistlib.loads(plist.replace("__REPO__", "/tmp/x").replace("__HOME__", "/tmp").encode())
    times = parsed["StartCalendarInterval"]
    check(sorted(t["Weekday"] for t in times) == [1, 2, 3, 4, 5] and all((t["Hour"], t["Minute"]) == (8, 8) for t in times),
          "plist: 08:08 Mon-Fri")
    check(parsed["RunAtLoad"] is False, "not at load")
    wrapper = (ops / "run_engine.sh.template").read_text()
    check("-m dragonfly.engine run" in wrapper and "/usr/bin/python3" in wrapper, "wrapper runs the engine loop")


def test_examples_validate():
    import jsonschema

    pairs = {"trade_draft": "trade_draft.json", "engine_book": "engine_book.json", "trade_card": "trade_card.json",
             "trade_redteam": "trade_redteam.json"}
    for schema, example in pairs.items():
        errs = core.schema_errors(f"{schema}.schema.json", json.loads((EXAMPLES / example).read_text()))
        check(not errs, f"example {example} validates: {errs}")
    for name in ("trade_card", "trade_draft", "trade_redteam", "engine_reject_record", "engine_book", "engine_done",
                 "engine_ready"):
        schema = json.loads((ROOT / "docs" / "dragonfly" / "schemas" / f"{name}.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        check(True, f"{name} schema is a valid 2020-12 schema")
    card = json.loads((EXAMPLES / "trade_card.json").read_text())
    card["red_team"]["decision"] = "pending"
    check(core.schema_errors("trade_card.schema.json", card), "red_team.decision 'pending' removed")
    rt = json.loads((EXAMPLES / "trade_redteam.json").read_text())
    rt["hard_blocks"] = ["x"]
    check(core.schema_errors("trade_redteam.schema.json", rt), "schema has no hard_blocks field for red team")


def test_gap_history_mac_measured():
    """The Mac measures gap_history from its bars; a red team that misses it gets it added (never removed)."""
    w = World("gaphist")
    w.push_regime()
    bars = fx.breakout(PREV)
    bars[-30] = dict(bars[-30], open=90.0)   # a 10.0 gap vs stop distance 3.88 -> > 1.5x
    w.trade(1, ticker="GAP", bars=bars, flags={"sector_lagging": True})
    w.trade(2, ticker="CLN", sector="Energy")   # clean bars, no flags
    w.now = ct(8, 16)
    w.engine().run_pass()
    c1, c2 = w.card("DF-2026-0001"), w.card("DF-2026-0002")
    gi = c1["engine"]["inputs"]
    check(c1["engine"]["outcome"] == "sized" and c1["red_team"]["warnings"] == ["sector_lagging", "gap_history"]
          and gi["warning_count"] == 2 and gi["warnings_added_by_engine"] == ["gap_history"],
          f"Mac-measured gap_history added to the red team's flags: {c1['red_team']} {gi['warning_count']}")
    check(c1["sizing"]["name_heat_cap"] == 500 and gi["warnings_tightened"] is True,
          f"red team flag + Mac gap_history = 2 warnings -> cautious name cap: {c1['sizing']}")
    gd = gi["measurements"]["details"]["gap_history"]
    check(gd["flag"] is True and gd["max_gap"] == 10.0 and gd["threshold"] == 5.82, f"gap detail recorded: {gd}")
    check(c2["red_team"]["warnings"] == [] and c2["engine"]["inputs"]["warnings_added_by_engine"] == []
          and c2["engine"]["inputs"]["measurements"]["details"]["gap_history"]["flag"] is False,
          "clean bars: no warning added")
    all_remote_cards_valid(w)


def test_catalyst_record():
    ex = json.loads((EXAMPLES / "trade_draft.json").read_text())["catalyst"]
    cat = lambda **o: dict(ex, **o)  # noqa: E731
    cc = lambda c: sg.catalyst_checks(c, D)[0]  # noqa: E731
    # D = Mon 2026-09-28; the 5 sessions before it start Mon 2026-09-21
    check(cc(cat(observed_at="2026-09-21T09:00:00-05:00")) == [], "primary 5 sessions back passes")
    check(cc(cat(observed_at="2026-09-18T15:00:00-05:00")) == ["catalyst_stale"], "primary 6 sessions back is stale")
    check(cc(cat(observed_at="2026-09-28T07:30:00-05:00")) == [], "primary this morning passes")
    check(cc(cat(observed_at="2026-09-29T07:30:00-05:00")) == ["catalyst_date_invalid"], "future-dated catalyst blocks")
    check(cc(cat(observed_at=None)) == ["catalyst_unsourced"], "undated primary blocks")
    check(cc(cat(source_url=" ")) == ["catalyst_unsourced"], "no source URL blocks")
    check(cc(cat(source_type="none")) == ["catalyst_unsourced"], "source_type none blocks")
    check(cc(cat(quality="secondary", observed_at="2026-08-01T09:00:00-05:00")) == [], "secondary has no recency rule")
    check(cc(cat(quality="absent", source_url="", source_type="none", observed_at=None)) == [], "absent is not checked here")
    check(cc(cat(observed_at="2026-09-21T13:30:00Z")) == [], "UTC timestamps are converted to CT")
    # through the engine: a stale primary is a structural block on the card
    w = World("catalyst")
    w.push_regime()
    w.trade(1, ticker="OLD", catalyst=cat(observed_at="2026-09-10T08:00:00-05:00"))
    w.now = ct(8, 16)
    w.engine().run_pass()
    c = w.card("DF-2026-0001")
    check(c["status"] == "blocked" and "catalyst_stale" in c["red_team"]["hard_blocks"] and c["sizing"]["units"] == 0,
          f"stale primary catalyst blocks: {reasons(c)}")
    check(c["engine"]["inputs"]["measurements"]["details"]["catalyst"]["primary_window_start"] == "2026-09-21",
          "catalyst detail recorded")
    all_remote_cards_valid(w)


def test_signal_age_and_calendar_coverage():
    w = World("sigage")
    w.push_regime()
    old_signal = mc.previous_sessions(D, 6)[0]   # 6 sessions back: outside the 5-session window
    ok_signal = mc.previous_sessions(D, 5)[0]
    w.trade(1, ticker="OLD", measurements={"signal_session": old_signal.isoformat()})
    w.trade(2, ticker="OK5", sector="Energy", measurements={"signal_session": ok_signal.isoformat()})
    w.trade(3, ticker="CAL", sector="Utilities",
            time_stop={"max_calendar_days": 7, "entry_session_date": "2029-01-03", "exit_session_date": "2029-01-10"})
    w.now = ct(8, 16)
    w.engine().run_pass()
    c1, c2, c3 = (w.card(f"DF-2026-{n:04d}") for n in (1, 2, 3))
    check("signal_session_stale" in reasons(c1) and c1["sizing"]["units"] == 0, f"signal 6 sessions old blocks: {reasons(c1)}")
    check("signal_session_stale" not in reasons(c2), f"signal 5 sessions old is inside the window: {reasons(c2)}")
    check("calendar_not_covered" in reasons(c3) and c3["status"] == "blocked",
          f"dates outside the calendar tables fail closed: {reasons(c3)}")
    all_remote_cards_valid(w)


def main():
    tests = [
        test_examples_validate,
        test_calendar,
        test_book_freshness_unit,
        test_setup_gates_unit,
        test_sized_card,
        test_redteam_gating,
        test_gap_history_mac_measured,
        test_late_redteam_and_done_mixed,
        test_rejections,
        test_setup_gates_engine,
        test_catalyst_record,
        test_signal_age_and_calendar_coverage,
        test_measurements,
        test_book_stale,
        test_holiday_engine,
        test_frozen_idempotency,
        test_done_zero_and_finalize,
        test_regime_pending_then_cutoff,
        test_pending_heat_sector_and_option,
        test_window_closed_and_book_errors,
        test_fail_closed_schema,
        test_push_retry_and_sync,
        test_loop_timeline,
        test_ready_marker,
        test_cli_once,
        test_guards_and_network,
        test_ops_templates,
    ]
    for t in tests:
        t()
    print(f"dragonfly engine: all {CHECKS} checks passed in {len(tests)} tests (offline)")


if __name__ == "__main__":
    main()
