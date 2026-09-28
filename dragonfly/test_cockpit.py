"""Offline tests for the Dragonfly cockpit (python3 dragonfly/test_cockpit.py) and weekly_review.schema.json."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dragonfly import cockpit  # noqa: E402

EXAMPLES = ROOT / "docs" / "dragonfly" / "examples"
SCHEMAS = ROOT / "docs" / "dragonfly" / "schemas"
CHECKS = 0
TMP = Path(tempfile.mkdtemp(prefix="df-cockpit-"))
GEN = datetime.fromisoformat("2026-09-28T08:30:00-05:00")


def check(cond, label):
    global CHECKS
    CHECKS += 1
    assert cond, label


def w(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=1))


def no_external(page: str, label: str) -> None:
    check("<script" not in page.lower(), f"{label}: no JS")
    check(not re.search(r'(src|href)\s*=\s*"(https?:)?//', page), f"{label}: no external src/href")
    check("@import" not in page and "url(http" not in page, f"{label}: no external CSS")


def render(state, handoff=None, inbox=None):
    return cockpit.render(cockpit.load_inputs(state, handoff, inbox), GEN)


def test_empty_states():
    state = TMP / "empty" / "state"
    state.mkdir(parents=True)
    page = render(state)
    for s in ("No book.json in the state folder yet.", "No cards for this session.", "No closed trades yet.",
              "no closed trades yet", "No cards waiting on Jared.", "NO_TRADE", "Missing or unreadable inputs"):
        check(s in page, f"empty state renders: {s!r}")
    for sid in ("book", "today", "trade", "journal", "performance", "weekly"):
        check(f'id="{sid}"' in page, f"section {sid} present")
    no_external(page, "empty")
    check("behind" not in page.lower() and "target gap" not in page.lower() and "$1,000" not in page,
          "no dollars-behind / target-gap field anywhere")

    # handoff folder exists but no cards, no DONE; inbox missing; unreadable book
    h = TMP / "empty" / "priv" / "handoff" / "2026-09-28"
    h.mkdir(parents=True)
    w(state / "book.json", "{not json")
    page = render(state, h, TMP / "empty" / "priv" / "inbox" / "2026-09-28")
    check("cards/DONE" in page and "inbox folder" in page and "unreadable" in page, "missing / unreadable files listed")
    check("not yet" in page and "No cards for this session." in page, "no DONE, no cards render cleanly")
    s = cockpit.journal_stats([])
    check(s["n"] == 0 and s["win_rate"] is None and s["expectancy_r"] is None and s["max_drawdown_pct"] is None,
          "empty journal: no numbers invented")


def _card(tid, ticker, setup, status, entry_date, warnings=(), units=10):
    c = json.loads((EXAMPLES / "trade_card.json").read_text())
    c.update(trade_id=tid, ticker=ticker, setup=setup, status=status, version=1)
    c["time_stop"] = dict(c["time_stop"], entry_session_date=entry_date)
    c["red_team"] = {"decision": "pass", "hard_blocks": [], "warnings": list(warnings), "narrative": "Case against."}
    c["sizing"] = dict(c["sizing"], units=units, name_heat_cap=500 if len(warnings) >= 2 else 1000)
    c["engine"] = {"outcome": "sized"}
    return c


def _journal(tid, setup, r, pnl, mae, mfe, hold, regime="normal"):
    j = json.loads((EXAMPLES / "journal_entry.json").read_text())
    j.update(trade_id=tid, setup=setup, r_multiple=r, net_pnl=pnl, mae_r=mae, mfe_r=mfe, hold_sessions=hold,
             regime_at_entry=regime)
    return j


def seeded():
    base = TMP / "seed"
    state, priv = base / "state", base / "priv"
    ds = "2026-09-28"
    h, i = priv / "handoff" / ds, priv / "inbox" / ds
    w(state / "book.json", {"book": "paper", "as_of": "2026-09-25T15:41:11-05:00", "equity": 101200.0, "cash": 90000,
                            "open_heat": 500.0, "gross_long": 10000, "day_pnl_pct": 0.004, "week_pnl_pct": 0.012,
                            "drawdown_pct": 0.0, "consecutive_full_losses": 0,
                            "positions": [{"trade_id": "DF-2026-0001", "ticker": "OLD", "sector": "Energy",
                                           "setup": "catalyst_breakout", "instrument": "stock", "heat": 500.0,
                                           "entry_price": 50.0, "stop": 48.0, "mark": 53.0,
                                           "entry_session_date": "2026-09-23"}]})
    w(state / "equity_history.json", [{"date": "2025-12-31", "equity": 100000}, {"date": "2026-08-31", "equity": 100500}])
    # three closed trades: +2R, -1R, +0.5R; entered Mon 09-14, Tue 09-15, Mon 09-21
    for tid, setup, r, pnl, mae, mfe, hold, d in (
            ("DF-2026-0010", "catalyst_breakout", 2.0, 1300.0, -0.2, 2.4, 3, "2026-09-14"),
            ("DF-2026-0011", "momentum_pullback", -1.0, -650.0, -1.0, 0.4, 2, "2026-09-15"),
            ("DF-2026-0012", "catalyst_breakout", 0.5, 550.0, -0.4, 1.1, 4, "2026-09-21")):
        w(state / "journal" / f"{tid}.json", _journal(tid, setup, r, pnl, mae, mfe, hold))
        w(state / "trades" / f"{tid}.json", _card(tid, "J" + tid[-2:], setup, "closed", d))
    w(state / "cache" / "bars" / "SPY.json", {"ticker": "SPY", "bars": [
        {"date": "2026-09-11", "close": 700.0}, {"date": "2026-09-25", "close": 707.0}]})
    w(h / "cards" / "DF-2026-0002.json", _card("DF-2026-0002", "META", "momentum_pullback", "pending_human", ds,
                                               ["gap_history"], units=25))
    w(h / "cards" / "DF-2026-0003.json", _card("DF-2026-0003", "COST", "catalyst_breakout", "pending_human", ds,
                                               ["valuation_extreme", "event_just_outside_window"], units=15))
    w(h / "cards" / "DONE", {"marker": "DONE", "revision": 1, "as_of": "2026-09-28T08:21:00-05:00",
                             "counts": {"drafts": 2, "sized": 2, "rejected": 0, "late": 0},
                             "skipped_files": [{"file": f"inbox/{ds}/df-2026-0004.json", "reason": "unrecognized_draft_name"}]})
    w(h / "prep.json", {"tickers": ["T%d" % n for n in range(47)]})
    w(priv / "handoff" / "2026-09-25" / "cards" / "DF-2026-0002.json",
      dict(_card("DF-2026-0002", "META", "momentum_pullback", "candidate", ds), version=0))
    w(i / "DF-2026-0002.json", {"trade_id": "DF-2026-0002"})
    w(i / "DF-2026-0003.draft.json", {"trade_id": "DF-2026-0003"})
    w(i / "DF-2026-0003.redteam.json", {"trade_id": "DF-2026-0003", "flags": {"valuation_extreme": True,
                                                                              "event_just_outside_window": True}})
    regime = json.loads((EXAMPLES / "regime_snapshot.json").read_text())
    w(i / "market_read.json", {"regime": dict(regime, session_date=ds), "price_flow": {"top15": [{}] * 15}})
    return state, priv, h, i


def test_seeded():
    state, priv, h, i = seeded()
    inp = cockpit.load_inputs(state, h, i)
    page = cockpit.render(inp, GEN)
    no_external(page, "seeded")
    check("META" in page and "COST" in page and "REVIEW" in page, "cards and REVIEW state")
    f = dict(cockpit.funnel(inp))
    check(f == {"Screened": 47, "Flagged": 15, "Drafted": 2, "Sized": 2, "Rejected": 0, "Late": 0, "Skipped files": 1},
          f"funnel from prep / market_read / inbox / DONE: {f}")
    check("df-2026-0004.json" in page, "skipped file listed")
    check("market_read.json#regime" in page, "regime from market_read.json")
    check("$101,200.00" in page and "+1.20%" in page and "+0.70%" in page, "equity vs seed and month from history")
    check("+1.50R" in page and ">3<" in page, "open R (53-50)/(50-48) and sessions held 09-23 -> 09-28")
    s = cockpit.journal_stats(inp["journal"])
    check(s["n"] == 3 and abs(s["win_rate"] - 2 / 3) < 1e-9 and s["avg_win_r"] == 1.25 and s["avg_loss_r"] == -1.0,
          f"win rate / avg winner / loser: {s}")
    check(abs(s["expectancy_r"] - 0.5) < 1e-9 and s["avg_hold"] == 3.0, "expectancy and hold")
    check(abs(s["max_drawdown_pct"] - 650.0 / 101300.0) < 1e-12, f"max drawdown on the closed-trade curve: {s['max_drawdown_pct']}")
    check(s["avg_mae_r_winners"] == -0.30000000000000004 or abs(s["avg_mae_r_winners"] + 0.3) < 1e-9, "MAE on winners")
    check(s["avg_mfe_r_losers"] == 0.4, "MFE on losers")
    check(dict(s["r_hist"]) == {"< -1R": 0, "-1 to -0.5": 1, "-0.5 to 0": 0, "0 to 0.5": 0, "0.5 to 1": 1,
                                "1 to 2": 0, "> 2R": 1}, f"R histogram: {s['r_hist']}")
    check("<svg" in page and "<rect" in page, "inline SVG chart")
    check("By setup" in page and "By regime at entry" in page and ">Mon<" in page and ">Tue<" in page,
          "grouped by setup / regime / weekday (from the card entry date)")
    check("vs SPY +1.00%" in page, "SPY beside the book from the SPY bars (700 -> 707)")
    check("valuation_extreme" in page and 'class="pill on">event_just_outside_window' in page, "red team flags shown")
    check("2026-09-25" in page and "candidate" in page, "version history includes the earlier folder's card")
    check("behind" not in page.lower() and "target gap" not in page.lower(), "weekly scoreboard has no target gap")
    check("weekly_scoreboard() over journal entries entered since 2026-09-28" in page, "weekly block source stated")

    wr = json.loads((EXAMPLES / "weekly_review.json").read_text())
    w(priv / "handoff" / "weekly" / "2026-10-02" / "weekly_review.json", wr)
    page2 = cockpit.render(cockpit.load_inputs(state, h, i), GEN)
    check("week ending 2026-10-02" in page2 and "+0.87R" in page2, "weekly_review.json scoreboard preferred when filed")

    # defaults: latest date under the roots; generate writes the file; site/ refused
    hd, idir = cockpit.resolve_dirs(None, None, priv)
    check(hd == priv / "handoff" / "2026-09-28" and idir == priv / "inbox" / "2026-09-28", f"latest date default: {hd}")
    out = cockpit.generate(state / "cockpit.html", state, hd, idir, GEN)
    check(out.exists() and "COST" in out.read_text(), "generate writes cockpit.html")
    try:
        cockpit.generate(TMP / "site" / "cockpit.html", state, hd, idir)
        check(False, "site/ must be refused")
    except ValueError:
        check(True, "site/ refused")
    rc = cockpit.main(["--state-dir", str(state), "--private-dir", str(priv), "--out", str(TMP / "cli.html")])
    check(rc == 0 and (TMP / "cli.html").exists(), "CLI writes the page")
    check("dragonfly/state/live/" in (ROOT / ".gitignore").read_text(), "cockpit.html's folder is gitignored")


def test_weekly_review_schema():
    import jsonschema

    schema = json.loads((SCHEMAS / "weekly_review.schema.json").read_text())
    jsonschema.Draft202012Validator.check_schema(schema)
    v = jsonschema.Draft202012Validator(schema)
    ex = json.loads((EXAMPLES / "weekly_review.json").read_text())
    check(not list(v.iter_errors(ex)), f"example validates: {[e.message for e in v.iter_errors(ex)]}")

    def bad(mut, label):
        doc = copy.deepcopy(ex)
        mut(doc)
        check(list(v.iter_errors(doc)), label)

    def good(mut, label):
        doc = copy.deepcopy(ex)
        mut(doc)
        errs = [e.message for e in v.iter_errors(doc)]
        check(not errs, f"{label}: {errs}")

    bad(lambda d: d["scoreboard"].update(dollars_behind_target=440.8), "no target-gap field in the scoreboard")
    bad(lambda d: d.update(target_gap=1), "no target-gap field at the top level")
    bad(lambda d: d["scoreboard"].update(flat_week_is_success=False), "flat week is a success")
    bad(lambda d: d["coach"].pop("amendment"), "all seven coach answers required")
    good(lambda d: d["coach"].update(amendment="Require 2.0x relative volume on breakouts."), "one amendment as text")
    bad(lambda d: d["coach"].update(amendment=["a", "b"]), "at most one amendment")
    good(lambda d: d["coach"]["setup_mean_r"].update(best=None, worst=None), "no closed trades: best/worst null")
    bad(lambda d: d["setups"][1].update(retirement_eligible=True), "retirement needs 40 trades (n=1)")
    good(lambda d: d["setups"][1].update(closed_trades=40, mean_net_r=-0.05, retirement_eligible=True),
         "40 trades with mean <= 0: eligible")
    bad(lambda d: d["setups"][0].update(closed_trades=45, mean_net_r=0.3, retirement_eligible=True),
        "positive mean R is never eligible")
    good(lambda d: d["coach"]["rule_violations"].append({"rule": "red_not_flattened", "trade_id": "DF-2026-0011",
                                                         "detail": "RED at 10:14, flattened next session"}),
         "rule violation recorded")


def main():
    try:
        for t in (test_empty_states, test_seeded, test_weekly_review_schema):
            t()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print(f"dragonfly cockpit: all {CHECKS} checks passed (offline)")


if __name__ == "__main__":
    main()
