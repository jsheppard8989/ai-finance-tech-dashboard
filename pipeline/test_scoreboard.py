"""Tests for the paper-trade scoreboard (schema 2). Runs on a clean checkout: every input
is a fixture under pipeline/fixtures/scoreboard (a sanitized copy of the Nov 23 book,
the Nov 20-24 three-a-day reads, and the Nov 26 9:02 AM CT read-only Robinhood pull)."""
from __future__ import annotations

import copy
import csv
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import build_scoreboard as bs
import market_calendar as mc
import pull_scoreboard_quotes as pq

CT = ZoneInfo("America/Chicago")
HERE = Path(__file__).resolve().parent
FIX = HERE / "fixtures" / "scoreboard"
QDIR = FIX / "quotes"
SITE = HERE.parent / "site"
NOW = datetime(2026, 11, 26, 9, 30, tzinfo=CT)


@pytest.fixture()
def book():
    return json.loads((FIX / "paper_book.json").read_text())


@pytest.fixture()
def saved():
    return pq.load_saved_legs(QDIR / "saved_legs.csv")


def _live():
    return pq.parse_robinhood_payload(
        pq.load_tool_json(FIX / "rh_equity_2026-11-26_0902.json"),
        pq.load_tool_json(FIX / "rh_options_2026-11-26_0902.json"),
    )


def _build(book, saved, now=NOW):
    eq, opt, _ = _live()
    quotes = pq.normalize_quotes(book, eq, opt, QDIR, now, saved)
    return bs.build_scoreboard(book, quotes, saved, pq.load_csv_history(QDIR), pq.load_closes(QDIR / "spy_closes.csv"), now)


def test_fill_rule():
    assert bs.buy_fill(1.61, 1.64) == pytest.approx(1.63)
    assert bs.sell_fill(0.16, 0.17) == pytest.approx(0.163333, abs=1e-6)


def test_full_record_and_headline(book, saved):
    sb, held = _build(book, saved)
    assert held == []
    rec = sb["record"]
    assert rec["closed_count"] == 8 == len(book["closed"])
    assert (rec["wins"], rec["losses"]) == (3, 5)
    assert rec["win_rate_pct"] == 37.5
    assert rec["realized_pnl"] == pytest.approx(2167.20)
    assert rec["avg_pnl_pct_max_loss"] == pytest.approx(11.79, abs=0.01)
    assert rec["open_count"] == 2
    assert rec["open_pnl"] == pytest.approx(1630.00)  # TLT +2,460.00, GOOGL -830.00
    assert rec["open_max_loss"] == pytest.approx(19680.00)
    assert {r["id"] for r in sb["closed"]} == {p["id"] for p in book["closed"]}


def test_cash_park_is_separate(book, saved):
    sb, _ = _build(book, saved)
    assert sb["cash_park"]["id"] == "strc-park"
    assert all(not r["is_cash_park"] for r in sb["open"])
    assert sb["book"]["park_pnl"] == pytest.approx(-1293.37)
    assert sb["book"]["book_value"] == pytest.approx(353.98 + 15660.00 + 5650.00 + 78672.65)
    assert sb["book"]["trades_pnl"] + sb["book"]["park_pnl"] == pytest.approx(sb["book"]["total_pnl"])


def test_one_percent_basis_max_loss(book, saved):
    sb, _ = _build(book, saved)
    for r in sb["open"] + sb["closed"] + [sb["cash_park"]]:
        assert r["pnl_pct_max_loss"] == pytest.approx(100 * r["pnl"] / r["max_loss"], abs=0.01)
    lrcx = next(r for r in sb["closed"] if r["id"] == "lrcx-put")
    assert lrcx["max_loss"] == pytest.approx(20443.33)
    assert lrcx["pnl_pct_max_loss"] == pytest.approx(-5.10, abs=0.01)
    assert lrcx["owner_stated"] is True


def test_open_marks_tie_to_quotes(book, saved):
    sb, _ = _build(book, saved)
    tlt = next(r for r in sb["open"] if r["id"] == "ric-1123-tlt")
    # 81C 1.93/1.98 -> sell 1.946667; 88C 0.20/0.21 -> buy back 0.206667; net 1.74 x 9,000
    assert tlt["value"] == pytest.approx(15660.00)
    assert tlt["mark_time_ct"] == "2026-11-25T15:14:59-06:00"
    googl = next(r for r in sb["open"] if r["id"] == "scout-1117-googl")
    assert googl["value"] == pytest.approx(5650.00)
    assert googl["entry_text"] == "$10.80 debit"  # no repeated date in the Entry column
    assert "Nov" not in googl["entry_text"]


def test_after_hours_stock_quote_not_used(book, saved):
    eq, _, _ = _live()
    assert pq.quote_problems("STRC", eq["STRC"])  # 7:00 PM CT bid/ask
    sb, _ = _build(book, saved)
    assert sb["cash_park"]["mark_time_ct"] == "2026-11-24T14:59:57-06:00"


def test_freshness_red_after_one_trading_day(book, saved):
    sb, _ = _build(book, saved)
    assert sb["cash_park"]["is_stale"] is True  # Tue mark, Wed session closed
    assert sb["record"]["open_is_stale"] is False  # Wed marks, Fri session not closed yet
    assert sb["record"]["open_stale_after_ct"] == "2026-11-27T12:00:00-06:00"  # Fri half day
    sb2, _ = _build(book, saved, datetime(2026, 11, 27, 12, 1, tzinfo=CT))
    assert sb2["record"]["open_is_stale"] is True
    assert "Today's" not in json.dumps(sb)
    assert pq.STALE_TRADING_DAYS == 1


def test_calendar():
    assert not mc.is_trading_day(datetime(2026, 11, 26).date())
    assert mc.session_close(datetime(2026, 11, 27).date()).hour == 12
    assert mc.stale_after(datetime(2026, 11, 24, 14, 59, tzinfo=CT)).isoformat() == "2026-11-25T15:00:00-06:00"
    assert mc.in_regular_session(datetime(2026, 11, 25, 15, 14, 59, tzinfo=CT))
    assert not mc.in_regular_session(datetime(2026, 11, 25, 19, 0, tzinfo=CT))


def test_row_that_does_not_tie_is_held(book, saved):
    bad = copy.deepcopy(book)
    next(p for p in bad["closed"] if p["id"] == "ceg-q3")["realized"] = -700.00
    sb, held = _build(bad, saved)
    assert any(h["id"] == "ceg-q3" for h in held)
    assert "ceg-q3" not in {r["id"] for r in sb["closed"]}


def test_record_must_match_book_wins_losses(book, saved):
    bad = copy.deepcopy(book)
    bad["wins_losses"]["closed_wins"] = 4
    _, held = _build(bad, saved)
    assert any(h["id"] == "_record" for h in held)


def test_wording_gate_holds_row(book, saved):
    bad = copy.deepcopy(book)
    next(p for p in bad["closed"] if p["id"] == "asts-q3")["exit"] = "Expiry; our bet paid"
    sb, held = _build(bad, saved)
    assert any(h["id"] == "asts-q3" for h in held)


def test_audit_rows(book, saved):
    sb, _ = _build(book, saved)
    tlt = next(r for r in sb["open"] if r["id"] == "ric-1123-tlt")
    assert [l["leg"] for l in tlt["audit"]["entry"]["legs"]] == ["81C", "88C"]
    assert tlt["audit"]["entry"]["math"].endswith("$13,200.00")
    assert tlt["audit"]["mark"]["math"].endswith("$15,660.00")
    mu = next(r for r in sb["closed"] if r["id"] == "mu-cycle")
    assert mu["audit"]["entry"]["math"].endswith("$7,466.67")
    assert mu["audit"]["exit"]["math"].endswith("$9,110.00")
    asts = next(r for r in sb["closed"] if r["id"] == "asts-q3")
    assert asts["audit"]["exit"]["math"].endswith("$4,200.00")


def test_writeups(book, saved):
    sb, _ = _build(book, saved)
    urls = {r["id"]: r["writeup_url"] for r in sb["closed"] + sb["open"]}
    assert urls["mu-cycle"] == "mu-memory-cycle.html"
    assert urls["lrcx-put"] == "lrcx-paid-to-wait.html"
    assert urls["ric-1123-tlt"] == "tlt-call-spread.html"
    assert urls["scout-1117-googl"] == "googl-call-spread.html"
    for u in filter(None, urls.values()):
        assert (SITE / u).is_file(), u


MONTH_YEAR_EXPIRY_RE = re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)-\d{2}\b")


def test_tlt_expiry_is_full_date_not_month_year(book, saved):
    """Expiry is the calendar day, not a month-year shorthand like Jan-27."""
    assert bs.fmt_date("2027-01-15", year_always=True) == "Jan 15, 2027"
    sb, _ = _build(book, saved)
    tlt = next(r for r in sb["open"] if r["id"] == "ric-1123-tlt")
    assert tlt["expiry"] == "2027-01-15"
    assert tlt["expiry_label"] == "Jan 15, 2027"
    assert "Jan 15, 2027" in tlt["structure"]
    assert "Jan-27" not in json.dumps(tlt)
    committed = json.loads((SITE / "data" / "scoreboard.json").read_text())
    committed_tlt = next(r for r in committed["open"] if r["id"] == "ric-1123-tlt")
    assert committed_tlt["expiry_label"] == "Jan 15, 2027"
    for row in list(sb["open"]) + list(sb["closed"]) + ([sb["cash_park"]] if sb.get("cash_park") else []):
        blob = json.dumps(row)
        assert not MONTH_YEAR_EXPIRY_RE.search(blob), (row.get("id"), blob)


def test_equity_curve_vs_spy(book, saved):
    sb, _ = _build(book, saved)
    c = sb["equity_curve"]
    pts = {p["date"]: p for p in c["points"]}
    assert pts["2026-11-15"]["book_value"] == 100000.0
    assert pts["2026-11-24"]["book_value"] == pytest.approx(97786.63)
    assert pts["2026-11-24"]["spy_value"] == pytest.approx(100000 * 718.78 / 754.37, abs=0.01)
    assert "2026-11-25" not in pts and any("Nov 25" in g for g in c["gaps"])


def test_private_notes_not_exported():
    raw = json.loads((Path("/workspace/cos/paper_book/2026-11-23_book.json")).read_text()) \
        if Path("/workspace/cos/paper_book/2026-11-23_book.json").is_file() else None
    if raw is None:
        pytest.skip("private book not on this machine")
    sb, _ = bs.build_scoreboard(raw, {"equity": {}, "options": {}}, now_ct=NOW)
    text = json.dumps(sb)
    assert "A+" not in text and "decision" not in text


def test_parse_wrapped_tool_output(tmp_path):
    raw = (FIX / "rh_options_2026-11-26_0902.json").read_text()
    p = tmp_path / "wrapped.txt"
    p.write_text("<fence source=\"x\">\n\n" + raw + "\n\n</fence>")
    _, opt, _ = pq.parse_robinhood_payload(None, pq.load_tool_json(p))
    assert opt["b5a974df-705b-4254-a22b-a26e248e8123"]["bid"] == 1.93


def test_record_live_read(tmp_path, saved):
    eq, opt, closes = _live()
    paths = pq.record_live_read(tmp_path, eq, opt, closes, saved, datetime(2026, 11, 26, 9, 2, 30, tzinfo=CT))
    rows = list(csv.DictReader(paths["csv"].open()))
    assert len(rows) == 5
    assert pq.load_closes(paths["spy"])["2026-11-24"] == 718.78
    assert json.loads(paths["audit"].read_text())["routine"] == "three-a-day-quote-read"


def test_requests_are_read_only(book, saved):
    reqs = pq.build_mcp_requests(book, saved)
    assert {t["tool"] for t in reqs["tools"]} == {"get_equity_quotes", "get_option_quotes"}
    assert len(reqs["option_instrument_ids"]) == 4 and "SPY" in reqs["equity_symbols"]


def test_committed_scoreboard_ties_to_book(book):
    sb = json.loads((SITE / "data" / "scoreboard.json").read_text())
    assert sb["schema_version"] == 2
    assert bs.verify_existing_scoreboard(sb, book) == []


def test_trades_page():
    html = (SITE / "trades.html").read_text()
    assert html.count('data-kit-tag="trades"') == 2
    assert html.count("app.kit.com/forms/10236979/subscriptions") == 2
    assert "Today's" not in html and not re.search(r"\bbet\b", html, re.I)
    assert 'id="methodology"' in html and "Owner-stated exit" in html and "Nov 15 reset" in html
    assert "./js/scoreboard.js" in html


def test_home_summary():
    html = (SITE / "index.html").read_text()
    assert 'data-scoreboard="summary"' in html and "./js/scoreboard.js" in html
    assert html.index('id="scoreboard-summary"') < html.index('id="signup"')


def test_scoreboard_js_has_no_todays_label():
    js = (SITE / "js" / "scoreboard.js").read_text()
    assert "Today's" not in js and "Mark as of" in js
