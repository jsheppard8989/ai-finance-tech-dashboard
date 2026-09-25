"""Offline tests for the prep (15:30 CT) and pre-open (08:05 CT) jobs.

A temp bare git repo stands in for dragonfly-private (with a Mac clone). The
watchlist build, the bars fetcher and the quote fetcher are fakes; sockets are
patched to fail and yfinance is never imported.

Run: python3 dragonfly/test_jobs.py
"""

from __future__ import annotations

import atexit
import io
import json
import logging
import os
import plistlib
import shutil
import socket
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="dragonfly-jobs-test-")
atexit.register(shutil.rmtree, _TMP, True)
os.environ["DRAGONFLY_STATE_DIR"] = str(Path(_TMP) / "state-default")
os.environ.pop("DRAGONFLY_ALLOW_DAEMON_WINDOW", None)
os.environ.pop("DRAGONFLY_HANDOFF_ROOT", None)
os.environ.pop("DRAGONFLY_INBOX_ROOT", None)
for var in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    os.environ.pop(var, None)


class NetworkUsed(AssertionError):
    pass


def _no_connect(self, address):  # pragma: no cover
    raise NetworkUsed(f"network call attempted: {address!r}")


socket.socket.connect = _no_connect  # type: ignore[assignment]
socket.create_connection = lambda *a, **k: (_ for _ in ()).throw(NetworkUsed(f"create_connection {a!r}"))  # type: ignore

from dragonfly import guards  # noqa: E402

PREFLIGHTS = []


def _fake_preflight(*_a, **_k):
    PREFLIGHTS.append(1)


def _no_fetch(*_a, **_k):
    raise AssertionError("a real data fetch guard was reached in an offline test")


guards.preflight = _fake_preflight  # type: ignore[assignment]
guards.before_fetch = _no_fetch  # type: ignore[assignment]

from dragonfly import bars as bars_mod  # noqa: E402

bars_mod.yahoo_history = _no_fetch  # type: ignore[assignment]

from dragonfly import engine_fixtures as fx  # noqa: E402
from dragonfly import market_calendar as mc  # noqa: E402
from dragonfly.engine import core  # noqa: E402
from dragonfly.engine import measure  # noqa: E402
from dragonfly.jobs import cli as jobs_cli  # noqa: E402
from dragonfly.jobs import preopen as po  # noqa: E402
from dragonfly.jobs import prep as pr  # noqa: E402
from dragonfly.jobs.common import JobError, job_lock  # noqa: E402

po.yahoo_preopen_quote = _no_fetch  # type: ignore[assignment]
pr._default_build = _no_fetch  # type: ignore[assignment]
pr._default_refresh = _no_fetch  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
D = date(2026, 9, 28)      # Monday
PREV = date(2026, 9, 25)   # Friday
DS = D.isoformat()
CHECKS = 0
LOG = io.StringIO()
for _name in ("dragonfly.jobs", "dragonfly.engine"):
    logging.getLogger(_name).addHandler(logging.StreamHandler(LOG))
    logging.getLogger(_name).setLevel(logging.INFO)


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def ct(day, h, m, s=0):
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=core.tz())


def git(cwd, *args):
    proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git {args} in {cwd}: {proc.stderr}")
    return proc.stdout


def raises(fn, exc=JobError, contains=None):
    try:
        fn()
    except exc as e:
        return contains is None or contains in str(e)
    return False


TICKERS = {"AAA": "Technology", "BBB": "Health Care", "CCC": "Industrials"}


class World:
    def __init__(self, name, session=D, book_as_of=None, positions=None):
        self.session = session
        self.ds = session.isoformat()
        self.prev = mc.previous_session(session)
        self.base = Path(_TMP) / name
        self.remote = self.base / "remote.git"
        self.mac = self.base / "mac"
        self.state = self.base / "state"
        self.base.mkdir(parents=True)
        git(self.base, "init", "--quiet", "--bare", "-b", "main", str(self.remote))
        seed = self.base / "seed"
        git(self.base, "init", "--quiet", "-b", "main", str(seed))
        self._ident(seed)
        (seed / "README.md").write_text("fake dragonfly-private\n")
        for d in ("handoff", "inbox"):
            (seed / d).mkdir()
            (seed / d / ".gitkeep").write_text("")
        git(seed, "add", "-A")
        git(seed, "commit", "--quiet", "-m", "seed")
        git(seed, "remote", "add", "origin", str(self.remote))
        git(seed, "push", "--quiet", "origin", "main")
        git(self.base, "clone", "--quiet", str(self.remote), str(self.mac))
        self._ident(self.mac)
        self.state.mkdir()
        shutil.copyfile(ROOT / "dragonfly" / "universe.json", self.state / "universe.json")
        self.book_path = self.state / "book.json"
        close = mc.session_close(self.prev)
        self.book = {
            "book": "paper", "as_of": core.iso(book_as_of or close + timedelta(minutes=30)),
            "equity": 100000, "cash": 100000, "open_heat": 0, "gross_long": 0,
            "positions": positions or [], "day_pnl_pct": 0, "week_pnl_pct": 0, "drawdown_pct": 0,
            "consecutive_full_losses": 0,
        }
        self.book_path.write_text(json.dumps(self.book))
        self.bars = {t: fx.breakout(self.prev) for t in TICKERS}
        self.refreshed = []
        self.quote_calls = []
        self.builds = []

    @staticmethod
    def _ident(repo):
        git(repo, "config", "user.name", "test")
        git(repo, "config", "user.email", "test@example.invalid")
        git(repo, "config", "commit.gpgsign", "false")

    # ---- fakes
    def build_fn(self, out, universe_path):
        self.builds.append((out, universe_path))
        names = [{"ticker": t, "rank": i + 1, "sector": s, "sector_rank": 1, "market_cap": 1e11,
                  "origin": ["ndx_top5"], "price": 84.3, "adv20_dollars": 1.3e8, "bid": 84.275, "ask": 84.325,
                  "mid": 84.3, "spread": 0.05, "spread_source": "modeled_mid_0.05", "mid_source": "quote_mid",
                  "provisional": True, "last_trade": 84.3, "quote_time": 1790366400}
                 for i, (t, s) in enumerate(TICKERS.items())]
        doc = {"schema": "dragonfly.watchlist/2", "as_of": "x", "universe": {"as_of_date": "2026-09-25"},
               "funnel": {"admitted": len(names)}, "excluded_summary": {}, "names": names, "excluded": {}}
        out.write_text(json.dumps(doc))
        return doc

    def load_fn(self, t):
        return {"ticker": t, "fetched_at": "2026-09-25T09:00:00-05:00", "bars": self.bars[t]}  # before the close

    def refresh_fn(self, t):
        self.refreshed.append(t)
        return {"ticker": t, "fetched_at": core.iso(mc.session_close(self.prev) + timedelta(minutes=31)),
                "bars": self.bars[t]}

    def quote_fn(self, t):
        self.quote_calls.append(t)
        return {"bid": 85.10, "ask": 85.14, "last": 85.12, "last_source": "pre_market",
                "quote_time": ct(self.session, 8, 4).timestamp(), "previous_close": 84.3,
                "market_state": "PRE", "halted": None}

    # ---- runs
    def prep(self, root="handoff", real=None, **kw):
        real = real or (mc.session_close(self.prev) + timedelta(minutes=30))
        return pr.run_prep(self.mac, now=real, date_arg=kw.pop("date_arg", self.ds), handoff_root=root,
                           state=self.state, book_path=self.book_path, preflight=_fake_preflight,
                           build_fn=self.build_fn, load_fn=self.load_fn, refresh_fn=self.refresh_fn,
                           real_now=lambda: real, **kw)

    def preopen(self, root="handoff", at=None, **kw):
        at = at or ct(self.session, 8, 5)
        return po.run_preopen(self.mac, now_fn=lambda: at, date_arg=self.ds, simulated=True, handoff_root=root,
                              state=self.state, book_path=self.book_path, preflight=_fake_preflight,
                              quote_fn=kw.pop("quote_fn", self.quote_fn), real_now=lambda: at, **kw)

    def remote_files(self, prefix=""):
        out = git(self.remote, "ls-tree", "-r", "--name-only", "main")
        return [p for p in out.splitlines() if p.startswith(prefix)]

    def remote_json(self, rel):
        return json.loads(git(self.remote, "show", f"main:{rel}"))


# ---------------------------------------------------------------- tests
def test_next_session():
    check(pr.target_session(ct(PREV, 15, 30), None) == D, "Fri 15:30 -> Mon")
    check(pr.target_session(ct(date(2026, 11, 25), 15, 30), None) == date(2026, 11, 27), "Wed before Thanksgiving -> Fri")
    check(pr.target_session(ct(date(2026, 12, 31), 15, 30), None) == date(2027, 1, 4), "New Year's Day skipped")
    check(pr.target_session(ct(date(2026, 7, 2), 15, 30), None) == date(2026, 7, 6), "Independence Day (observed Fri 7/3) skipped")
    check(pr.target_session(ct(PREV, 15, 30), "2026-09-28") == D, "--date honoured")
    check(raises(lambda: pr.target_session(ct(PREV, 15, 30), "2026-11-26"), contains="not an NYSE session"),
          "--date on Thanksgiving refused")
    check(raises(lambda: pr.target_session(ct(PREV, 15, 30), "2026-09-27")), "--date on a Sunday refused")
    # the Monday after Thanksgiving week uses Friday's 12:00 CT early close
    check(mc.session_close(mc.previous_session(date(2026, 11, 30))) == ct(date(2026, 11, 27), 12, 0), "early close")


def test_prep_writes_contract():
    w = World("prep")
    out = w.prep()
    rel = f"handoff/{DS}"
    check(sorted(out["files"]) == [f"{rel}/measurements.json", f"{rel}/prep.json"], "prep files")
    check(set(w.remote_files(rel)) == {f"{rel}/measurements.json", f"{rel}/prep.json"}, "pushed to the remote")
    check(sorted(w.refreshed) == sorted(TICKERS), "cache fetched before the close is refreshed for admitted names")
    check(w.builds and w.builds[0][1] == w.state / "universe.json", "universe works on the state copy")
    prep = w.remote_json(f"{rel}/prep.json")
    check(prep["session_date"] == DS and prep["previous_session"] == "2026-09-25" and prep["as_of"], "prep.json dates")
    check(prep["tickers"] == list(TICKERS) and prep["watchlist"]["names"][0]["ticker"] == "AAA", "watchlist snapshot")
    meas = w.remote_json(f"{rel}/measurements.json")
    row = meas["names"][0]
    for k in ("ticker", "sector", "spread", "spread_source", "provisional", "bars", "price", "atr", "adv_dollars",
              "relative_volume", "bar_date"):
        check(k in row, f"measurement row has {k}")
    check(row["bar_date"] == "2026-09-25" and row["bars"][-1]["date"] == "2026-09-25", "bars end at the previous session")
    check(row["provisional"] is True and row["spread"] == 0.05, "provisional, spread as float")
    # the engine reads it through its own contract loader
    loaded, prel = measure.load_prep(w.mac, D)
    check(set(loaded) == set(TICKERS) and prel == f"{rel}/measurements.json", "engine load_prep reads it")
    check(out["book_mark"]["marked"] is True, "flat book marked on a real run")
    check(json.loads(w.book_path.read_text())["as_of"] == core.iso(mc.session_close(PREV) + timedelta(minutes=30)),
          "book as_of re-stamped to now")
    # a second prep with a fresh cache does not refetch
    w.load_fn = lambda t: {"ticker": t, "fetched_at": "2026-09-25T15:40:00-05:00", "bars": w.bars[t]}
    w.refreshed.clear()
    w.prep()
    check(w.refreshed == [], "fresh post-close cache is reused (cache-first)")


def test_prep_guards():
    w = World("prep-guards")
    check(raises(lambda: w.prep(real=ct(PREV, 14, 0)), contains="needs 2026-09-25's close"), "prep before the close refused")
    n = len(PREFLIGHTS)
    w.prep()
    check(len(PREFLIGHTS) == n + 1, "prep calls the load-guard preflight")
    blocked = []

    def block():
        blocked.append(1)
        raise guards.GuardBlocked("daemon_window", "test")

    w2 = World("prep-guard-block")
    check(raises(lambda: pr.run_prep(w2.mac, now=ct(PREV, 15, 30), date_arg=DS, state=w2.state, preflight=block,
                                     build_fn=w2.build_fn, load_fn=w2.load_fn, refresh_fn=w2.refresh_fn,
                                     real_now=lambda: ct(PREV, 15, 30)), exc=guards.GuardBlocked),
          "guard block stops prep")
    check(w2.remote_files(f"handoff/{DS}") == [] and not w2.builds, "nothing built or written after a guard block")
    # READY already present -> prep refuses
    w.preopen()
    check(raises(lambda: w.prep(), contains="READY already exists"), "prep after READY refused")
    # one prep at a time
    w3 = World("prep-lock")
    with job_lock("prep", w3.state):
        check(raises(lambda: w3.prep(), contains="another prep job"), "job lock")
    # no usable bars anywhere -> no prep
    w4 = World("prep-nobars")
    w4.refresh_fn = lambda t: (_ for _ in ()).throw(bars_mod.BarsUnavailable(t, "fetch_failed"))
    check(raises(lambda: w4.prep(), contains="no admitted name has usable bars"), "all bars unavailable")
    check(w4.remote_files(f"handoff/{DS}") == [], "nothing written")


def test_book_mark_rules():
    w = World("mark-pos", positions=[{"trade_id": "DF-2026-0001", "ticker": "AAA", "sector": "Technology",
                                      "setup": "catalyst_breakout", "instrument": "stock", "heat": 900, "notional": 20000}],
              book_as_of=ct(date(2026, 9, 24), 15, 30))
    out = w.prep()
    check(out["book_mark"] == {**out["book_mark"], "marked": False, "reason": "open_positions_not_marked"},
          "a book with positions is never auto-marked")
    check(json.loads(w.book_path.read_text())["as_of"] == core.iso(ct(date(2026, 9, 24), 15, 30)), "as_of unchanged")
    w2 = World("mark-dry", book_as_of=ct(date(2026, 9, 24), 15, 30))
    out = w2.prep(root="handoff-dryrun")
    check(out["book_mark"]["reason"] == "dry_run", "dry run never marks the book")


def test_preopen_requires_prep():
    w = World("no-prep")
    check(raises(lambda: w.preopen(), contains="PREP MISSING"), "missing prep fails loudly")
    check(w.remote_files(f"handoff/{DS}") == [], "no READY, nothing written")
    check(w.quote_calls == [], "no quotes fetched without prep")
    # a prep whose session_date is another day does not count
    w.prep()
    p = w.mac / "handoff" / DS / "prep.json"
    doc = json.loads(p.read_text())
    doc["session_date"] = "2026-09-29"
    p.write_text(json.dumps(doc))
    git(w.mac, "commit", "--quiet", "-am", "wrong prep")
    git(w.mac, "push", "--quiet", "origin", "main")
    check(raises(lambda: w.preopen(), contains="is not for 2026-09-28"), "prep for another date does not satisfy today")
    check(not any(p.endswith("READY") for p in w.remote_files()), "still no READY")


def test_preopen_book_stale():
    w = World("stale", book_as_of=ct(PREV, 14, 59))
    w.prep(mark_book=False)
    check(raises(lambda: w.preopen(), contains="BOOK STALE"), "book marked before Friday's close fails")
    check(not any(p.endswith("READY") for p in w.remote_files()), "no READY when stale")
    check(w.quote_calls == [], "no quotes fetched when stale")
    w.book_path.write_text("{}")
    check(raises(lambda: w.preopen(), exc=core.EngineError, contains="book state invalid"), "invalid book fails")
    w.book_path.unlink()
    check(raises(lambda: w.preopen(), exc=core.EngineError, contains="not found"), "missing book fails")


def test_ready_last():
    w = World("ready")
    w.prep()
    order = []
    from dragonfly.engine.markers import write_ready

    def ready_spy(repo, session, **kw):
        # at READY time every other handoff file is already committed AND pushed
        files = w.remote_files(f"handoff/{DS}")
        order.append(sorted(files))
        return write_ready(repo, session, **kw)

    out = w.preopen(ready_fn=ready_spy)
    rel = f"handoff/{DS}"
    check(order and set(order[0]) == {f"{rel}/{n}" for n in ("prep.json", "measurements.json", "quotes.json", "book.json")},
          "quotes/book/prep pushed before READY is written")
    last = git(w.remote, "log", "-1", "--name-only", "--format=%s", "main").split()
    check(last[-1] == f"{rel}/READY" and len([x for x in last if x.startswith("handoff/")]) == 1,
          "the last remote commit is READY alone")
    ready = w.remote_json(f"{rel}/READY")
    check(sorted(f["path"] for f in ready["files"]) == ["book.json", "measurements.json", "prep.json", "quotes.json"],
          "READY lists every handoff file")
    check(ready["as_of"] == core.iso(ct(D, 8, 5)), "READY as_of on the job clock")
    q = w.remote_json(f"{rel}/quotes.json")
    check(q["counts"] == {"names": 3, "usable": 3, "cache_hits": 0}, "quotes for admitted names only")
    check(sorted(w.quote_calls) == sorted(list(TICKERS) + list(po.MARKET_CONTEXT)), "admitted names + market context only")
    row = q["names"][0]
    check(row["spread_source"] == "yahoo" and row["mid"] == 85.12 and row["gap_pct"] == round(85.12 / 84.3 - 1, 6),
          "quote resolved with resolve_quote; gap vs prep close")
    b = w.remote_json(f"{rel}/book.json")
    check(b["freshness"]["fresh"] is True and b["book"]["equity"] == 100000 and b["summary"]["positions"] == 0,
          "book snapshot for agents")
    check(out["ready"] == f"{rel}/READY", "result names READY")
    check(raises(lambda: w.preopen(), contains="READY already exists"), "a second pre-open refuses")


def test_quotes_modeled_cache_and_failures():
    w = World("quotes")
    w.prep()

    def junk(t):
        w.quote_calls.append(t)
        if t == "BBB":
            raise RuntimeError("HTTP 429")
        return {"bid": 70.0, "ask": 99.0, "last": 85.0, "last_source": "post_market",
                "quote_time": ct(PREV, 18, 0).timestamp(), "market_state": "POST", "halted": None}

    w.preopen(quote_fn=junk)
    q = w.remote_json(f"handoff/{DS}/quotes.json")
    rows = {r["ticker"]: r for r in q["names"]}
    check(rows["AAA"]["spread_source"] == "modeled_last_0.05" and rows["AAA"]["spread"] == 0.05, "junk quote -> modeled")
    check(rows["BBB"]["usable"] is False and rows["BBB"]["reason"] == "quote_fetch_failed", "fetch failure recorded")
    check(q["counts"]["usable"] == 2, "usable count")
    # cache-first: a second fetch inside 10 minutes reuses the cache
    cache = po.QuoteCache(w.state / "cache" / "quotes" / f"{DS}.json")
    calls = []
    got = po.fetch_quotes(["AAA", "CCC"], lambda t: calls.append(t) or {}, cache, lambda: ct(D, 8, 9))
    check(calls == [] and got["AAA"]["cache_hit"] is True, "quote cache hit within 10 minutes")
    po.fetch_quotes(["AAA"], lambda t: calls.append(t) or {"bid": 1}, cache, lambda: ct(D, 8, 20))
    check(calls == ["AAA"], "stale quote cache refetched")
    # zero usable quotes -> no READY
    w2 = World("quotes-dead")
    w2.prep()
    check(raises(lambda: w2.preopen(quote_fn=lambda t: (_ for _ in ()).throw(RuntimeError("down"))),
                 contains="no usable pre-market quote"), "all quotes failed")
    check(not any(p.endswith("READY") for p in w2.remote_files()), "no READY without quotes")


def test_dry_run_roots():
    w = World("dry")
    before = git(w.remote, "rev-parse", "main").strip()
    w.prep(root="handoff-dryrun")
    w.preopen(root="handoff-dryrun")
    files = w.remote_files()
    check(all(not p.startswith("handoff/") or p == "handoff/.gitkeep" for p in files), "handoff/ untouched")
    check(all(not p.startswith("inbox/") or p == "inbox/.gitkeep" for p in files), "inbox/ untouched")
    dry = set(w.remote_files(f"handoff-dryrun/{DS}"))
    check(dry == {f"handoff-dryrun/{DS}/{n}" for n in ("prep.json", "measurements.json", "quotes.json", "book.json", "READY")},
          "dry-run handoff complete")
    changed = git(w.remote, "diff", "--name-only", before, "main").split()
    check(changed and all(p.startswith("handoff-dryrun/") for p in changed), "every change is under handoff-dryrun/")
    check(not (w.state / "cache" / "quotes" / f"{DS}.json").exists() and
          (w.state / "cache" / "quotes" / f"{DS}.handoff-dryrun.json").exists(), "separate quote cache for the dry run")
    # the engine reads the dry-run measurements
    loaded, prel = measure.load_prep(w.mac, D, "handoff-dryrun")
    check(prel == f"handoff-dryrun/{DS}/measurements.json" and len(loaded) == 3, "engine reads dry-run prep")
    # the real handoff still needs its own prep
    check(raises(lambda: w.preopen(), contains="PREP MISSING"), "dry-run prep does not satisfy the real pre-open")


def test_preopen_calendar_and_clock():
    w = World("cal")
    sat = datetime(2026, 9, 26, 8, 5, tzinfo=core.tz())
    out = po.run_preopen(w.mac, now_fn=lambda: sat, state=w.state, book_path=w.book_path, preflight=_fake_preflight,
                         quote_fn=w.quote_fn)
    check(out.get("not_session") is True and w.remote_files("handoff/2026") == [], "weekend: exit ok, nothing written")
    tg = datetime(2026, 11, 26, 8, 5, tzinfo=core.tz())
    out = po.run_preopen(w.mac, now_fn=lambda: tg, state=w.state, book_path=w.book_path, preflight=_fake_preflight,
                         quote_fn=w.quote_fn)
    check(out.get("not_session") is True, "Thanksgiving: exit ok")
    check(raises(lambda: po.run_preopen(w.mac, now_fn=lambda: ct(PREV, 19, 0), date_arg=DS, state=w.state,
                                        preflight=_fake_preflight), contains="is not today"),
          "--date not today needs --now")


def test_cli():
    w = World("cli")
    buf = io.StringIO()
    old = sys.stdout
    # prep through the CLI with the fakes wired in
    pr._default_build, pr._default_load, pr._default_refresh = w.build_fn, w.load_fn, w.refresh_fn
    po.yahoo_preopen_quote = w.quote_fn
    real_now = core.now_ct
    try:
        sys.stdout = buf
        rc = jobs_cli.main(["prep", "--repo", str(w.mac), "--date", DS, "--dry-run-roots", "--state-dir", str(w.state),
                            "--book", str(w.book_path)])
        check(rc == 0, f"cli prep rc {rc}: {LOG.getvalue()[-400:]}")
        rc = jobs_cli.main(["preopen", "--repo", str(w.mac), "--date", DS, "--dry-run-roots", "--state-dir",
                            str(w.state), "--book", str(w.book_path), "--now", "2026-09-28T08:05:00-05:00"])
        check(rc == 0, f"cli preopen rc {rc}: {LOG.getvalue()[-400:]}")
        rc = jobs_cli.main(["preopen", "--repo", str(w.mac), "--date", DS, "--state-dir", str(w.state),
                            "--book", str(w.book_path), "--now", "2026-09-28T08:05:00-05:00"])
        check(rc == 2, "cli preopen without prep exits 2")
    finally:
        sys.stdout = old
        core.now_ct = real_now
        pr._default_build = pr._default_refresh = _no_fetch
        po.yahoo_preopen_quote = _no_fetch
    check(f"handoff-dryrun/{DS}/READY" in w.remote_files(), "cli dry run wrote READY in handoff-dryrun/")
    check(w.remote_files(f"handoff/{DS}") == [], "cli never touched handoff/")


def test_ops_templates():
    ops = ROOT / "dragonfly" / "ops"
    for job, (h, m), wrapper, needle in (("prep", (15, 30), "run_prep.sh.template", "-m dragonfly.jobs prep"),
                                         ("preopen", (8, 5), "run_preopen.sh.template", "-m dragonfly.jobs preopen")):
        text = (ops / f"com.dragonfly.{job}.plist.template").read_text()
        parsed = plistlib.loads(text.replace("__REPO__", "/tmp/x").replace("__HOME__", "/tmp").encode())
        times = parsed["StartCalendarInterval"]
        check(sorted(t["Weekday"] for t in times) == [1, 2, 3, 4, 5] and all((t["Hour"], t["Minute"]) == (h, m) for t in times),
              f"{job}: {h:02d}:{m:02d} Mon-Fri")
        check(parsed["RunAtLoad"] is False, f"{job}: not at load")
        check(parsed["ProgramArguments"][1].endswith(wrapper.replace(".template", "")), f"{job}: runs its wrapper")
        sh = (ops / wrapper).read_text()
        check(needle in sh and "/usr/bin/python3" in sh, f"{job}: wrapper runs the job")
        check("pull --ff-only" in sh and "ai-finance-tech-dashboard" in sh, f"{job}: ff-only pull, refuses the pipeline checkout")
        check("now_hm" in sh and "exit 0" in sh, f"{job}: wake guard")
        r = subprocess.run(["bash", "-n", str(ops / wrapper)], capture_output=True, text=True)
        check(r.returncode == 0, f"{job}: wrapper parses ({r.stderr})")


def main():
    tests = [
        test_next_session,
        test_prep_writes_contract,
        test_prep_guards,
        test_book_mark_rules,
        test_preopen_requires_prep,
        test_preopen_book_stale,
        test_ready_last,
        test_quotes_modeled_cache_and_failures,
        test_dry_run_roots,
        test_preopen_calendar_and_clock,
        test_cli,
        test_ops_templates,
    ]
    for t in tests:
        t()
    print(f"dragonfly jobs: all {CHECKS} checks passed in {len(tests)} tests (offline)")


if __name__ == "__main__":
    main()
