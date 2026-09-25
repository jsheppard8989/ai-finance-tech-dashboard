"""Offline tests for the pre-open engine, READY/DONE markers and ops templates.

A temp bare git repo stands in for dragonfly-private, with two clones: the
Mac's engine checkout and a box agent that pushes drafts. A fake book lives
in a temp state dir. No network: sockets are patched to fail, the load guards
are patched to fail if called, and no market-data module may be imported.

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

from dragonfly import risk_math as rm  # noqa: E402
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
class World:
    """Fresh fake dragonfly-private (bare remote + mac clone + agent clone) and book."""

    def __init__(self, name, book=None):
        self.base = Path(_TMP) / name
        self.remote = self.base / "remote.git"
        self.mac = self.base / "mac"
        self.agent = self.base / "agent"
        self.state = self.base / "state"
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
        self.state.mkdir()
        self.write_book(book or json.loads((EXAMPLES / "engine_book.json").read_text()))
        self.now = ct(8, 8)

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

    def push_draft(self, draft, name=None, raw=None):
        name = name or f"{draft['trade_id']}.draft.json"
        self.agent_push(f"inbox/{DS}/{name}", draft, raw=raw, message=f"draft {name}")

    def push_regime(self, **over):
        snap = json.loads((EXAMPLES / "regime_snapshot.json").read_text())
        snap["session_date"] = DS
        snap.update(over)
        self.agent_push(f"inbox/{DS}/regime_snapshot.json", snap, message="regime")

    def engine(self, **kw):
        kw.setdefault("clock", SessionClock(D))
        return Engine(self.mac, D, book_path=self.book_path, state_dir=self.state,
                      now_fn=lambda: self.now, sleep_fn=lambda s: None, **kw)

    def remote_file(self, rel):
        proc = subprocess.run(["git", "show", f"main:{rel}"], cwd=str(self.remote), capture_output=True, text=True)
        return proc.stdout if proc.returncode == 0 else None

    def remote_ls(self, rel_dir):
        out = git(self.remote, "ls-tree", "-r", "--name-only", "main", "--", rel_dir)
        return [line for line in out.splitlines() if line]

    def card(self, key):
        raw = self.remote_file(f"handoff/{DS}/cards/{key}.json")
        return json.loads(raw) if raw else None

    def done(self):
        raw = self.remote_file(f"handoff/{DS}/cards/DONE")
        return json.loads(raw) if raw else None


def draft(n=1, **over):
    d = json.loads((EXAMPLES / "trade_draft.json").read_text())
    d["trade_id"] = f"DF-2026-{n:04d}"
    d["time_stop"] = {"max_calendar_days": 7, "entry_session_date": DS, "exit_session_date": "2026-10-05"}
    for k, v in over.items():
        d[k] = v
    return d


def option_draft(n):
    d = draft(n, instrument="call")
    d["entry"] = {"trigger": "buy_limit", "price": 2.5}
    d["stop"] = 1.5
    d["targets"] = [{"price": 4.0, "fraction": 1}]
    d["measurements"] = dict(d["measurements"], sector="Health Care")
    d["catalyst"] = dict(d["catalyst"], earnings_in_window=True)
    d["option"] = {"contract": "XYZ 2026-10-16 85 C", "expiration": "2026-10-16", "bid": 2.45, "ask": 2.55,
                   "open_interest": 1200, "volume": 300, "underlying_stop": 80.75}
    return d


def all_remote_cards_valid(w):
    for rel in w.remote_ls(f"handoff/{DS}/cards"):
        if rel.endswith(".json"):
            card = json.loads(w.remote_file(rel))
            errs = core.card_errors(card)
            check(not errs, f"schema-valid card {rel}: {errs}")


# ---------------------------------------------------------------- tests
def test_sized_card():
    w = World("sized")
    w.push_regime()
    w.push_draft(draft(1))
    w.now = ct(8, 14)
    res = w.engine().run_pass()
    check(res["written"] == ["DF-2026-0001"], f"one card written {res}")
    check(res["done"] is None, "no DONE before cutoff")
    card = w.card("DF-2026-0001")
    check(card is not None, "card pushed to the remote")
    check(card["status"] == "pending_human", "approved card waits on Jared")
    check(card["risk_decision"] == {"decision": "APPROVED", "reasons": [], "risk_mode": "normal", "entries_allowed": True},
          "risk_decision copied from the governor")
    s = card["sizing"]
    check(s["units"] == 171 and s["planned_loss"] == 663.48 and s["heat_contribution"] == 995.22,
          f"canonical size 171 / 663.48 / 995.22: {s}")
    check(s["notional"] == 14471.73 and s["expected_r"] == 1.6418 and s["initial_risk"] == 663.48, "canonical notional/R")
    check(card["entry"]["max_fill"] == 84.63, "max_fill from max_buy_fill")
    check(card["frozen_at"] and card["created_at"].endswith("-05:00"), "frozen, CT-aware timestamps")
    check(card["red_team"]["decision"] == "pending", "red team marked pending")
    eng = card["engine"]
    check(eng["outcome"] == "sized" and eng["first_seen_at"] == ct(8, 14).isoformat(), "engine block")
    check(eng["inputs"]["measurements"]["measurements_source"] == "draft", "price source recorded (draft)")
    check(eng["inputs"]["market_data_network_calls"] == 0, "no market data calls")
    check(not core.card_errors(card), "schema valid")
    check(not (w.mac / f"handoff/{DS}/cards/DONE").exists(), "no DONE file before cutoff")


def test_rejections():
    w = World("reject")
    w.push_regime()
    # structural block: catalyst_breakout needs a primary catalyst
    w.push_draft(draft(2, catalyst=dict(draft(2)["catalyst"], quality="absent", source_type="none")))
    # pre-sized drafts
    ex_card = json.loads((EXAMPLES / "trade_card.json").read_text())
    w.push_draft(draft(3, sizing=ex_card["sizing"]))
    w.push_draft(draft(4, risk_decision=ex_card["risk_decision"]))
    d5 = draft(5)
    d5["entry"] = {"trigger": "buy_stop", "price": 84.5, "max_fill": 99.0}
    w.push_draft(d5)
    # invalid drafts
    bad = draft(6)
    del bad["why_now"]
    w.push_draft(bad)
    w.push_draft(None, name="DF-2026-0007.draft.json", raw="{not json")
    noid = draft(8)
    del noid["trade_id"]
    w.push_draft(noid, name="architect-oops.draft.json")
    # governor (size_stock) rejection: reward/risk under 1.5
    w.push_draft(draft(9, targets=[{"price": 86.0, "fraction": 1}]))
    w.now = ct(8, 16)
    res = w.engine().run_pass()
    check(len(res["written"]) == 8, f"eight cards/records {res['written']}")

    c2 = w.card("DF-2026-0002")
    check(c2["status"] == "blocked" and "catalyst_insufficient" in c2["risk_decision"]["reasons"], "structural block")
    check(c2["red_team"]["hard_blocks"] == ["catalyst_insufficient"], "hard blocks match the engine")
    check(c2["sizing"]["units"] == 0 and c2["engine"]["outcome"] == "rejected", "blocked card not sized")

    c3 = w.card("DF-2026-0003")
    check(c3["risk_decision"]["decision"] == "REJECTED" and "draft_carries_sizing" in c3["risk_decision"]["reasons"],
          "pre-sized draft rejected")
    check(c3["sizing"]["units"] == 0 and c3["sizing"]["planned_loss"] == 0, "model sizing never copied")
    c4 = w.card("DF-2026-0004")
    check("draft_carries_risk_decision" in c4["risk_decision"]["reasons"], "draft carrying risk_decision rejected")
    c5 = w.card("DF-2026-0005")
    check("draft_carries_max_fill" in c5["risk_decision"]["reasons"] and c5["entry"]["max_fill"] == 84.63,
          "draft max_fill rejected; card shows the engine's")

    c6 = w.card("DF-2026-0006")
    check(c6["record"] == "engine_reject" and c6["status"] == "blocked", "invalid draft -> reject record")
    check(any("why_now" in r for r in c6["risk_decision"]["reasons"]), "schema reason recorded")
    c7 = w.card("DF-2026-0007")
    check(c7["risk_decision"]["reasons"] == ["draft_not_json_object"], "non-JSON draft rejected under filename id")
    unid = w.card("unidentified/architect-oops")
    check(unid and unid["trade_id"] is None and "trade_id_missing" in unid["risk_decision"]["reasons"],
          "draft with no trade_id carded under unidentified/")

    c9 = w.card("DF-2026-0009")
    check(c9["status"] == "risk_rejected" and "reward_risk_below_minimum" in c9["risk_decision"]["reasons"],
          "governor rejection")
    all_remote_cards_valid(w)

    # a rejected card is never re-sized, even if the draft is fixed later
    fixed = draft(2)
    w.push_draft(fixed)
    w.now = ct(8, 17)
    res2 = w.engine().run_pass()
    check(res2["written"] == [] and res2["frozen_changed"] == ["DF-2026-0002"], "fixed draft does not re-size")
    check(w.card("DF-2026-0002") == c2, "rejected card unchanged")


def test_late_and_done_mixed():
    w = World("late")
    w.push_regime()
    w.push_draft(draft(1))
    w.push_draft(draft(2, catalyst=dict(draft(2)["catalyst"], quality="absent", source_type="none")))
    w.now = ct(8, 19)
    eng = w.engine()
    eng.run_pass()
    w.now = ct(8, 20)  # the cutoff pass itself is on time, and does not write DONE
    r = eng.run_pass()
    check(r["done"] is None and w.done() is None, "no DONE at the cutoff instant")
    w.push_draft(draft(3, measurements=dict(draft(3)["measurements"], sector="Energy")))
    w.now = ct(8, 21)
    r = eng.run_pass()
    check(r["written"] == ["DF-2026-0003"], "late draft carded")
    c3 = w.card("DF-2026-0003")
    check(c3["engine"]["outcome"] == "late" and c3["engine"]["reasons"] == ["late_draft"], "marked late")
    check(c3["risk_decision"] is None and c3["sizing"]["units"] == 0, "late draft not sized, no risk_decision")
    check(c3["status"] == "blocked", "late status blocked")
    done = w.done()
    check(done is not None, "DONE after cutoff")
    check(done["counts"] == {"drafts": 3, "sized": 1, "rejected": 1, "late": 1}, f"mixed counts {done['counts']}")
    check(done["trade_ids"] == {"sized": ["DF-2026-0001"], "rejected": ["DF-2026-0002"], "late": ["DF-2026-0003"]},
          "trade ids by outcome")
    check(done["finalized_by"] == "cutoff" and done["revision"] == 1, "finalized by cutoff")
    check(done["as_of"].endswith("-05:00"), "as_of is CT-aware")
    check(not core.schema_errors("engine_done.schema.json", done), "DONE schema valid")
    # a later late draft revises DONE; an unchanged pass does not
    w.now = ct(8, 22)
    check(eng.run_pass()["done"] is None, "no DONE rewrite without changes")
    w.push_draft(draft(4, measurements=dict(draft(4)["measurements"], sector="Utilities")))
    w.now = ct(8, 23)
    eng.run_pass()
    done2 = w.done()
    check(done2["revision"] == 2 and done2["counts"]["late"] == 2, "DONE revised for a later late card")
    all_remote_cards_valid(w)


def test_frozen_idempotency():
    w = World("frozen")
    w.push_regime()
    d = draft(1)
    w.push_draft(d)
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
    LOG.truncate(0)
    LOG.seek(0)
    w.now = ct(8, 14)
    r = eng.run_pass()
    check(r["frozen_changed"] == ["DF-2026-0001"], "draft change noticed")
    check("is frozen" in LOG.getvalue(), "draft change logged")
    check(w.remote_file(f"handoff/{DS}/cards/DF-2026-0001.json") == before, "frozen card byte-identical")
    w.now = ct(8, 15)
    LOG.truncate(0)
    LOG.seek(0)
    r = eng.run_pass()
    check(r["frozen_changed"] == [] and "is frozen" not in LOG.getvalue(), "change logged once, not every poll")
    # a fresh engine process (same state dir) also leaves it frozen
    w.now = ct(8, 16)
    check(w.engine().run_pass()["written"] == [], "restart keeps the card frozen")
    # even with the local engine state lost, the card on disk is authoritative
    shutil.rmtree(w.state / "engine")
    w.now = ct(8, 21)
    r = w.engine().run_pass()
    check(r["written"] == [] and w.card("DF-2026-0001")["engine"]["outcome"] == "sized", "state loss does not re-card")
    check(w.done()["counts"]["sized"] == 1, "DONE after restart")


def test_done_zero_and_finalize():
    w = World("zero")
    w.now = ct(8, 21)
    r = w.engine().run_pass()
    done = w.done()
    check(done is not None and done["counts"] == {"drafts": 0, "sized": 0, "rejected": 0, "late": 0}, "DONE with zero drafts")
    check(done["trade_ids"] == {"sized": [], "rejected": [], "late": []} and r["pushed"], "empty ids, pushed")

    w2 = World("finalize")
    w2.push_regime()
    w2.push_draft(draft(1))
    w2.now = ct(8, 15)
    check(w2.engine().run_pass()["done"] is None and w2.done() is None, "no DONE before cutoff")
    w2.now = ct(8, 16)
    w2.engine(finalize=True).run_pass()
    d = w2.done()
    check(d and d["finalized_by"] == "flag" and d["counts"]["sized"] == 1, "--finalize writes DONE early")


def test_regime_pending_then_cutoff():
    w = World("regime")
    w.push_draft(draft(1))
    w.now = ct(8, 13)
    eng = w.engine()
    r = eng.run_pass()
    check(r["pending"] == ["DF-2026-0001"] and r["written"] == [], "waits for the regime snapshot")
    w.now = ct(8, 21)
    r = eng.run_pass()
    c = w.card("DF-2026-0001")
    check(c["risk_decision"]["risk_mode"] == "stand_down" and c["risk_decision"]["entries_allowed"] is False,
          "no regime after cutoff fails closed to stand_down")
    check("regime_missing" in c["risk_decision"]["reasons"] and "stand_down" in c["risk_decision"]["reasons"],
          "regime_missing recorded")
    check(c["engine"]["outcome"] == "rejected" and w.done()["counts"]["rejected"] == 1, "then DONE")


def test_pending_heat_sector_and_option():
    w = World("heat")
    w.push_regime()
    w.push_draft(draft(1))
    w.push_draft(draft(2, ticker="ABC", measurements=dict(draft(2)["measurements"], sector="Energy")))
    w.push_draft(draft(3, ticker="DEF", measurements=dict(draft(3)["measurements"], sector="Energy")))
    w.push_draft(draft(4, ticker="GHI", setup="momentum_pullback",
                       measurements=dict(draft(4)["measurements"], sector="Materials")))
    w.push_draft(draft(6, ticker="JKL", setup="failed_breakdown",
                       measurements=dict(draft(6)["measurements"], sector="Utilities")))
    w.push_draft(draft(7, ticker="MNO", measurements=dict(draft(7)["measurements"], sector="Financials")))
    w.now = ct(8, 15)
    w.engine().run_pass()
    c2 = w.card("DF-2026-0002")
    check(c2["sizing"]["open_heat_before"] == 995.22, "pending approved heat counts against the next draft")
    check(c2["sizing"]["units"] == 171, "second name still fits under the 2% book cap")
    c3 = w.card("DF-2026-0003")
    check("sector_occupied" in c3["risk_decision"]["reasons"], "pending card occupies its sector")
    c4 = w.card("DF-2026-0004")
    # The governor sizes the last $9.56 of book heat into a 1-share crumb (risk_math has no minimum size).
    check(c4["sizing"]["open_heat_before"] == 1990.44 and c4["sizing"]["units"] == 1, f"crumb size {c4['sizing']}")
    c6 = w.card("DF-2026-0006")
    check(c6["status"] == "risk_rejected" and c6["sizing"]["open_heat_before"] == 1996.26
          and set(c6["risk_decision"]["reasons"]) & {"heat_exhausted", "size_zero"}, "book heat exhausted")
    c7 = w.card("DF-2026-0007")
    check(c7["status"] == "blocked" and "setup_cap" in c7["risk_decision"]["reasons"], "two pending breakouts hit the setup cap")

    w2 = World("option")
    w2.push_regime()
    w2.push_draft(option_draft(5))
    w2.now = ct(8, 15)
    w2.engine().run_pass()
    c = w2.card("DF-2026-0005")
    s = c["sizing"]
    check(c["status"] == "pending_human" and s["units"] == 4 and s["planned_loss"] == 400 and s["heat_contribution"] == 1000,
          f"plan option example: 4 contracts, $400 planned, $1,000 heat: {s}")
    check(s["gap_multiplier"] == 1 and c["engine"]["inputs"]["option"]["contract"].startswith("XYZ"), "option inputs kept")
    all_remote_cards_valid(w)
    all_remote_cards_valid(w2)


def test_prep_measurements_and_live_book():
    w = World("prep")
    w.push_regime()
    prep = {"as_of": "2026-09-25T15:30:00-05:00", "names": [{"ticker": "XYZ", "price": 84.3, "atr": 1.0,
                                                               "adv20_dollars": 150000000, "spread": 0.04,
                                                               "provisional": True, "sector": "Industrials"}]}
    w.agent_push(f"handoff/{DS}/measurements.json", prep)
    w.push_draft(draft(1))
    w.now = ct(8, 15)
    w.engine().run_pass()
    c = w.card("DF-2026-0001")
    check(c["engine"]["inputs"]["measurements"]["measurements_source"] == f"handoff/{DS}/measurements.json",
          "prep measurements beat the draft's copy")
    check("stop_distance_atr" in c["risk_decision"]["reasons"], "prep ATR drove the structural block")

    book = json.loads((EXAMPLES / "engine_book.json").read_text())
    book["book"] = "live"
    w2 = World("live", book=book)
    w2.push_regime()
    w2.push_draft(draft(2, book="live"))
    w2.now = ct(8, 15)
    w2.engine().run_pass()
    c2 = w2.card("DF-2026-0002")
    check("provisional_source_live" in c2["risk_decision"]["reasons"], "live book blocks provisional data")


def test_window_closed_and_book_errors():
    w = World("closed")
    w.push_draft(draft(1))
    w.now = ct(8, 15)
    eng = w.engine()
    eng.run_pass()  # pending: no regime
    w.push_regime()
    w.now = ct(9, 5)
    eng.run_pass()
    c = w.card("DF-2026-0001")
    check(c["risk_decision"]["reasons"] == ["engine_window_closed"] and c["sizing"]["units"] == 0,
          "nothing is sized after the window closes")

    w2 = World("nobook")
    w2.book_path.unlink()
    w2.push_regime()
    w2.push_draft(draft(1))
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
    w.push_draft(draft(1))
    w.now = ct(8, 15)
    real = core.card_errors
    calls = {"n": 0}

    def flaky(card):
        calls["n"] += 1
        if card.get("record") != "engine_reject":
            return ["$: injected schema failure"]
        return real(card)

    core.card_errors = flaky
    try:
        w.engine().run_pass()
    finally:
        core.card_errors = real
    c = w.card("DF-2026-0001")
    check(c["record"] == "engine_reject" and "card_schema_invalid" in c["risk_decision"]["reasons"],
          "schema-invalid sized card is written as a reject record, never as sized")
    check(not core.card_errors(c), "fallback record is schema valid")


def test_push_retry_and_sync():
    w = World("git")
    repo = PrivateRepo(w.mac, sleep=lambda s: None)
    check(repo.sync() is False, "no pull when the remote ref did not move")
    w.push_draft(draft(1))
    check(repo.sync() is True, "pull when the ref moved")
    check((w.mac / f"inbox/{DS}/DF-2026-0001.draft.json").exists(), "draft arrived")
    # engine writes a card; meanwhile an agent pushes -> non-fast-forward -> rebase + retry
    p = w.mac / f"handoff/{DS}/cards/X.json"
    p.parent.mkdir(parents=True)
    p.write_text("{}\n")
    w.push_draft(draft(2))
    repo.commit_and_push([f"handoff/{DS}/cards"], "test card")
    check(w.remote_file(f"handoff/{DS}/cards/X.json") == "{}\n", "card pushed after rebase")
    check(w.remote_file(f"inbox/{DS}/DF-2026-0002.draft.json") is not None, "agent commit preserved")
    log = git(w.remote, "log", "--format=%s", "main")
    check(log.splitlines()[0] == "test card", "rebased on top of the agent commit")


def test_loop_timeline():
    w = World("loop")
    w.push_regime()
    w.now = ct(8, 8)
    passes = []
    events = {ct(8, 15, 10): lambda: w.push_draft(draft(1)),
              ct(8, 20, 30): lambda: w.push_draft(draft(2, ticker="LTE", measurements=dict(draft(2)["measurements"], sector="Energy")))}

    def sleep(seconds):
        target = w.now + timedelta(seconds=seconds)
        for at in sorted(events):
            if w.now < at <= target:
                w.now = at
                events.pop(at)()
        w.now = target

    eng = Engine(w.mac, D, book_path=w.book_path, state_dir=w.state, now_fn=lambda: w.now, sleep_fn=sleep)
    real_pass = eng.run_pass

    def spy(tick=None):
        passes.append(tick)
        return real_pass(tick)

    eng.run_pass = spy
    rc = eng.run_loop()
    check(rc == 0, "loop exits 0 with DONE")
    check(passes[0] == ct(8, 8) and passes[-1] == ct(8, 24), "polls 08:08 through 08:24")
    check(ct(8, 20) in passes and len(passes) == 17, f"every 60 s including the 08:20 cutoff pass ({len(passes)})")
    c1, c2 = w.card("DF-2026-0001"), w.card("DF-2026-0002")
    check(c1["engine"]["outcome"] == "sized" and c1["engine"]["first_seen_at"] == ct(8, 16).isoformat(), "on-time draft sized")
    check(c2["engine"]["outcome"] == "late" and c2["engine"]["first_seen_at"] == ct(8, 21).isoformat(), "08:20:30 draft is late")
    done = w.done()
    check(done["counts"] == {"drafts": 2, "sized": 1, "rejected": 0, "late": 1}, "DONE from the loop")
    check(core.parse_iso(done["as_of"]) <= ct(8, 24), "DONE landed by 08:24")

    # a loop started before 08:08 waits; a run with no drafts still ends with DONE
    w2 = World("loop2")
    w2.now = ct(8, 1)
    eng2 = Engine(w2.mac, D, book_path=w2.book_path, state_dir=w2.state, now_fn=lambda: w2.now,
                  sleep_fn=lambda s: setattr(w2, "now", w2.now + timedelta(seconds=s)))
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
    check(ready == doc and ready["marker"] == "READY" and ready["as_of"] == "2026-09-28T08:06:30-05:00", "READY pushed")
    check([f["path"] for f in ready["files"]] == ["manifest.json", "regime_inputs.json"], "READY lists handoff files")
    check(all(len(f["sha256"]) == 64 and f["bytes"] > 0 for f in ready["files"]), "file hashes and sizes")
    check(w.remote_file(f"handoff/{DS}/regime_inputs.json") == "{}\n", "files pushed with READY")
    log = git(w.remote, "log", "--format=%s", "main").splitlines()
    check(log[0].startswith("pre-open") and log[1] == "prep", "READY is the last commit")
    check(not core.schema_errors("engine_ready.schema.json", ready), "READY schema valid")

    w2 = World("ready-empty")
    (w2.mac / f"handoff/{DS}").mkdir(parents=True)
    try:
        write_ready(w2.mac, D, now=ct(8, 6))
    except EngineError as exc:
        check("no files" in str(exc), "READY refuses an empty handoff")


def test_cli_once():
    w = World("cli")
    w.push_regime()
    w.push_draft(draft(1))
    buf = io.StringIO()
    old = sys.stdout
    logger = logging.getLogger("dragonfly.engine")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    sys.stdout = buf
    try:
        rc = cli_main(["run", "--once", "--repo", str(w.mac), "--date", DS, "--book", str(w.book_path),
                       "--state-dir", str(w.state), "--now", ct(8, 22).isoformat()])
    finally:
        sys.stdout = old
        logger.handlers[:], logger.level, logger.propagate = saved[0], saved[1], saved[2]
    out = json.loads(buf.getvalue())
    check(rc == 0 and out["written"] == ["DF-2026-0001"] and out["done"] is True, f"CLI --once {out}")
    check(w.card("DF-2026-0001")["engine"]["outcome"] == "late", "CLI after cutoff -> late")

    # dry-run shape: --no-push writes files in the checkout, commits and pushes nothing
    w2 = World("cli-dry")
    w2.push_regime()
    w2.push_draft(draft(2))
    head = git(w2.remote, "rev-parse", "main").strip()
    sys.stdout = io.StringIO()
    try:
        rc = cli_main(["run", "--once", "--no-push", "--repo", str(w2.mac), "--date", DS,
                       "--book", str(EXAMPLES / "engine_book.json"), "--state-dir", str(w2.state),
                       "--now", ct(8, 15).isoformat()])
        rc2 = cli_main(["run", "--once", "--no-push", "--repo", str(w2.mac), "--date", DS,
                        "--book", str(EXAMPLES / "engine_book.json"), "--state-dir", str(w2.state),
                        "--now", ct(8, 21).isoformat()])
    finally:
        sys.stdout = old
        logger.handlers[:], logger.level, logger.propagate = saved[0], saved[1], saved[2]
    check(rc == 0 and rc2 == 0, "dry-run passes succeed")
    check((w2.mac / f"handoff/{DS}/cards/DF-2026-0002.json").exists() and (w2.mac / f"handoff/{DS}/cards/DONE").exists(),
          "dry run writes card and DONE locally")
    check(git(w2.remote, "rev-parse", "main").strip() == head, "dry run pushes nothing")
    check(git(w2.mac, "status", "--porcelain").strip() != "" and git(w2.mac, "rev-parse", "HEAD").strip() == head,
          "dry run commits nothing")


def test_guards_and_network():
    # A guard-blocked moment (pipeline lock held AND inside a daemon window) does not stop the engine.
    check(guards.pipeline_busy() is not None, "pipeline lock is held for this test")
    w = World("guards")
    w.push_regime()
    w.push_draft(draft(1))
    w.now = ct(7, 30)  # inside the 05:00-07:59 daemon window
    w.engine(finalize=True).run_pass()
    check(w.card("DF-2026-0001")["engine"]["outcome"] == "sized", "engine ran under a held lock in a daemon window")
    for mod in ("yfinance", "dragonfly.bars", "dragonfly.chains", "dragonfly.build_watchlist", "requests", "urllib3"):
        check(mod not in sys.modules, f"{mod} never imported")
    pat = re.compile(r"^\s*(?:from|import)\s+(yfinance|requests|urllib|http|socket|dragonfly\.(?:bars|chains|build_watchlist|guards))\b|"
                     r"from dragonfly import .*\b(bars|chains|build_watchlist|guards)\b", re.M)
    for src in sorted((ROOT / "dragonfly" / "engine").glob("*.py")):
        check(not pat.search(src.read_text()), f"{src.name} imports no market-data or network module")


def test_ops_templates():
    ops = ROOT / "dragonfly" / "ops"
    plist = (ops / "com.dragonfly.engine.plist.template").read_text()
    check("<key>Weekday</key>" in plist and "<integer>8</integer>" in plist and "<integer>8</integer>" in plist, "08:08 weekdays")
    check(plist.count("<key>Weekday</key>") == 5 and "<key>RunAtLoad</key>\n  <false/>" in plist, "Mon-Fri, not at load")
    wrapper = (ops / "run_engine.sh.template").read_text()
    check("-m dragonfly.engine run" in wrapper and "/usr/bin/python3" in wrapper, "wrapper runs the engine loop")
    import plistlib

    parsed = plistlib.loads(plist.replace("__REPO__", "/tmp/x").replace("__HOME__", "/tmp").encode())
    times = parsed["StartCalendarInterval"]
    check(sorted(t["Weekday"] for t in times) == [1, 2, 3, 4, 5] and all((t["Hour"], t["Minute"]) == (8, 8) for t in times),
          "plist parses: 08:08 Mon-Fri")


def test_examples_validate():
    check(not core.schema_errors("trade_draft.schema.json", json.loads((EXAMPLES / "trade_draft.json").read_text())),
          "example draft validates")
    check(not core.schema_errors("engine_book.schema.json", json.loads((EXAMPLES / "engine_book.json").read_text())),
          "example book validates")
    check(not core.schema_errors("trade_card.schema.json", json.loads((EXAMPLES / "trade_card.json").read_text())),
          "example card (no engine block) still validates")
    for name in ("trade_card", "trade_draft", "engine_reject_record", "engine_book", "engine_done", "engine_ready"):
        schema = json.loads((ROOT / "docs" / "dragonfly" / "schemas" / f"{name}.schema.json").read_text())
        import jsonschema

        jsonschema.Draft202012Validator.check_schema(schema)
        check(True, f"{name} schema is a valid 2020-12 schema")


def main():
    tests = [
        test_examples_validate,
        test_sized_card,
        test_rejections,
        test_late_and_done_mixed,
        test_frozen_idempotency,
        test_done_zero_and_finalize,
        test_regime_pending_then_cutoff,
        test_pending_heat_sector_and_option,
        test_prep_measurements_and_live_book,
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
