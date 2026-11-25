"""Tests for pull_scoreboard_quotes.py, build_scoreboard.py, and site/index.html scoreboard."""
from __future__ import annotations

import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import build_scoreboard as bs
import pull_scoreboard_quotes as pq

CT = ZoneInfo("America/Chicago")
ROOT = Path(__file__).resolve().parent.parent
STATE_BOOK = ROOT / "pipeline" / "state" / "paper_book.json"
STATE_FALLBACK = ROOT / "pipeline" / "state" / "fallback_quotes.csv"
SITE_SCOREBOARD = ROOT / "site" / "data" / "scoreboard.json"
SITE_INDEX = ROOT / "site" / "index.html"


def _sample_book() -> dict:
    if STATE_BOOK.is_file():
        return json.loads(STATE_BOOK.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"Expected {STATE_BOOK} for test suite")


def test_fill_rule_math():
    assert bs.buy_fill(99.31, 99.35) == pytest.approx(99.33666667, abs=1e-6)
    assert bs.sell_fill(97.68, 97.83) == pytest.approx(97.73, abs=1e-6)
    assert bs.sell_fill(5.00, 6.70) == pytest.approx(5.56666667, abs=1e-6)


def test_nov23_book_and_nov24_fallback_tie_out():
    book = _sample_book()
    now_ct = datetime(2026, 11, 24, 22, 15, tzinfo=CT)
    quotes = pq.normalize_quotes(
        book=book,
        saved_legs_path=ROOT / "pipeline" / "state" / "saved_legs.csv",
        fallback_csv_path=STATE_FALLBACK,
        now=now_ct,
    )
    assert quotes["is_fallback"] is True
    assert quotes["quote_time_label"] == "Nov 24, 3:00 PM CT"

    sb, held = bs.build_scoreboard(book, quotes, now_ct=now_ct)
    assert held == []
    assert sb["is_fallback_quote"] is True
    assert "Saved quotes" in sb["quote_source"]

    t = sb["totals"]
    assert t["cash"] == pytest.approx(353.98, abs=0.01)
    assert t["allocated_cost"] == pytest.approx(99646.02, abs=0.01)
    assert t["open_value"] == pytest.approx(97432.65, abs=0.01)
    assert t["book_value"] == pytest.approx(97786.63, abs=0.01)
    assert t["unrealized_pnl"] == pytest.approx(-2213.37, abs=0.01)
    assert t["realized_pnl_since_reset"] == pytest.approx(0.0, abs=0.01)

    open_by_id = {r["id"]: r for r in sb["open"]}
    assert set(open_by_id.keys()) == {"strc-park", "scout-1117-googl", "ric-1123-tlt"}

    assert open_by_id["strc-park"]["current_mark"] == pytest.approx(97.73, abs=0.001)
    assert open_by_id["strc-park"]["current_value"] == pytest.approx(78672.65, abs=0.01)
    assert open_by_id["strc-park"]["unrealized_pnl"] == pytest.approx(-1293.37, abs=0.01)

    assert open_by_id["scout-1117-googl"]["current_mark"] == pytest.approx(10.2167, abs=0.001)
    assert open_by_id["scout-1117-googl"]["current_value"] == pytest.approx(6130.00, abs=0.01)
    assert open_by_id["scout-1117-googl"]["unrealized_pnl"] == pytest.approx(-350.00, abs=0.01)

    assert open_by_id["ric-1123-tlt"]["current_mark"] == pytest.approx(1.4033, abs=0.001)
    assert open_by_id["ric-1123-tlt"]["current_value"] == pytest.approx(12630.00, abs=0.01)
    assert open_by_id["ric-1123-tlt"]["unrealized_pnl"] == pytest.approx(-570.00, abs=0.01)

    closed_by_id = {r["id"]: r for r in sb["closed"]}
    assert set(closed_by_id.keys()) == {"lrcx-put"}
    lrcx = closed_by_id["lrcx-put"]
    assert lrcx["ticker"] == "LRCX"
    assert lrcx["strike"] == "$210 put"
    assert lrcx["expiry"] == "2026-12-04"
    assert lrcx["closed"] == "2026-11-05"
    assert lrcx["status"] == "closed_stop"
    assert lrcx["exit_fill"] == pytest.approx(16.00, abs=0.01)
    assert lrcx["realized_pnl"] == pytest.approx(-1043.33, abs=0.01)
    assert lrcx["pre_reset"] is True


def test_robinhood_live_quotes_override_fallback(tmp_path):
    book = _sample_book()
    now_ct = datetime(2026, 11, 25, 11, 30, tzinfo=CT)
    raw_rh = {
        "equity": [
            {
                "symbol": "STRC",
                "bid_price": "98.10",
                "ask_price": "98.25",
                "last_trade_price": "98.18",
                "updated_at": "2026-11-25T17:29:45Z",
            },
            {
                "symbol": "GOOGL",
                "bid_price": "305.00",
                "ask_price": "305.10",
                "last_trade_price": "305.05",
                "updated_at": "2026-11-25T17:29:45Z",
            },
            {
                "symbol": "TLT",
                "bid_price": "80.90",
                "ask_price": "80.92",
                "last_trade_price": "80.91",
                "updated_at": "2026-11-25T17:29:45Z",
            },
        ],
        "options": [
            {
                "instrument_id": "33e32d67-6dcf-4fab-8889-19b5373ea4eb",
                "bid_price": "17.00",
                "ask_price": "17.30",
                "updated_at": "2026-11-25T17:29:45Z",
            },
            {
                "instrument_id": "e7c7b26b-7251-42f3-812a-a0ad72f61e82",
                "bid_price": "6.00",
                "ask_price": "6.30",
                "updated_at": "2026-11-25T17:29:45Z",
            },
            {
                "instrument_id": "b5a974df-705b-4254-a22b-a26e248e8123",
                "bid_price": "1.60",
                "ask_price": "1.66",
                "updated_at": "2026-11-25T17:29:45Z",
            },
            {
                "instrument_id": "9e61ff0f-7500-4877-ad3e-c2f7662ea878",
                "bid_price": "0.18",
                "ask_price": "0.21",
                "updated_at": "2026-11-25T17:29:45Z",
            },
        ],
    }
    quotes = pq.normalize_quotes(
        book=book,
        robinhood_raw=raw_rh,
        fallback_csv_path=STATE_FALLBACK,
        now=now_ct,
    )
    assert quotes["is_fallback"] is False
    assert "Robinhood read-only" in quotes["quote_source"]

    sb, held = bs.build_scoreboard(book, quotes, now_ct=now_ct)
    assert held == []
    assert sb["is_fallback_quote"] is False
    open_by_id = {r["id"]: r for r in sb["open"]}
    # STRC: sell fill on 98.10/98.25 = 98.15 -> 805 * 98.15 = 79010.75
    assert open_by_id["strc-park"]["current_mark"] == pytest.approx(98.15, abs=0.001)
    assert open_by_id["strc-park"]["current_value"] == pytest.approx(79010.75, abs=0.01)
    # GOOGL: sell 300C at 17.10, buy 340C at 6.20 -> net mark 10.90 -> 6540.00 (+60.00)
    assert open_by_id["scout-1117-googl"]["current_mark"] == pytest.approx(10.90, abs=0.001)
    assert open_by_id["scout-1117-googl"]["unrealized_pnl"] == pytest.approx(60.00, abs=0.01)


def test_auto_close_at_stop_and_expiry():
    book = copy.deepcopy(_sample_book())
    # Set stop_below on GOOGL and make TLT expired on 2027-01-15
    for pos in book["open"]:
        if pos["id"] == "scout-1117-googl":
            pos["stop_below"] = 290.00
    now_ct = datetime(2027, 1, 15, 15, 5, tzinfo=CT)
    quotes = {
        "is_fallback": False,
        "quote_source": "Robinhood read-only (Jan 15, 3:05 PM CT)",
        "quote_time_ct": now_ct.isoformat(timespec="seconds"),
        "quote_time_label": "Jan 15, 3:05 PM CT",
        "equity": {
            "STRC": {"bid": 99.00, "ask": 99.15, "last": 99.05, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
            "GOOGL": {"bid": 285.00, "ask": 285.10, "last": 285.00, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
            "TLT": {"bid": 85.00, "ask": 85.02, "last": 85.00, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
        },
        "options": {
            "33e32d67-6dcf-4fab-8889-19b5373ea4eb": {"bid": 12.00, "ask": 12.30, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
            "e7c7b26b-7251-42f3-812a-a0ad72f61e82": {"bid": 2.00, "ask": 2.30, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
            "b5a974df-705b-4254-a22b-a26e248e8123": {"bid": 3.95, "ask": 4.10, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
            "9e61ff0f-7500-4877-ad3e-c2f7662ea878": {"bid": 0.00, "ask": 0.03, "quote_time_ct": now_ct.isoformat(timespec="seconds"), "quote_time_label": "Jan 15, 3:05 PM CT", "is_fallback": False},
        },
    }
    sb, held = bs.build_scoreboard(book, quotes, now_ct=now_ct)
    assert held == []
    closed_by_id = {r["id"]: r for r in sb["closed"]}
    assert closed_by_id["scout-1117-googl"]["status"] == "closed_stop"
    assert closed_by_id["ric-1123-tlt"]["status"] == "closed_expiry"
    assert "lrcx-put" in closed_by_id
    assert sb["totals"]["closed_since_reset_count"] == 2


def test_bad_math_or_banned_wording_holds_only_offending_row():
    book = copy.deepcopy(_sample_book())
    now_ct = datetime(2026, 11, 24, 22, 15, tzinfo=CT)
    quotes = pq.normalize_quotes(
        book=book,
        saved_legs_path=ROOT / "pipeline" / "state" / "saved_legs.csv",
        fallback_csv_path=STATE_FALLBACK,
        now=now_ct,
    )
    # Corrupt GOOGL entry cost + put banned wording in TLT wrong_if
    for pos in book["open"]:
        if pos["id"] == "scout-1117-googl":
            pos["cost"] = 9999.00
        if pos["id"] == "ric-1123-tlt":
            pos["proved_wrong"] = "We placed a bet and graded it B+."

    sb, held = bs.build_scoreboard(book, quotes, now_ct=now_ct)
    held_ids = {h["id"] for h in held}
    assert held_ids == {"scout-1117-googl", "ric-1123-tlt"}
    # STRC and LRCX still ship!
    assert [r["id"] for r in sb["open"]] == ["strc-park"]
    assert [r["id"] for r in sb["closed"]] == ["lrcx-put"]


def test_site_scoreboard_files_and_wording_clean():
    assert SITE_SCOREBOARD.is_file()
    book = _sample_book()
    sb = json.loads(SITE_SCOREBOARD.read_text(encoding="utf-8"))
    errs = bs.verify_existing_scoreboard(sb, book)
    assert errs == []

    html = SITE_INDEX.read_text(encoding="utf-8")
    assert 'id="scoreboard-summary"' in html
    assert 'data-scoreboard="summary"' in html
    assert "./js/scoreboard.js" in html
    assert 'id="latest-piece"' in html
    trades = (ROOT / "site" / "trades.html").read_text(encoding="utf-8")
    assert 'id="scoreboard"' in trades
    assert 'data-scoreboard="full"' in trades
    assert "./js/scoreboard.js" in trades
    js = (ROOT / "site" / "js" / "scoreboard.js").read_text(encoding="utf-8")
    assert "./data/scoreboard.json" in js
    # No grading words or Trap Map naming in the scoreboard markup/script
    for label, block in (
        ("home-summary", html.split('id="scoreboard-summary"', 1)[1].split('<div class="grid">', 1)[0]),
        ("trades", trades),
        ("scoreboard-js", js),
    ):
        assert not bs.GRADING_RE.search(block), label
        assert not bs.RETIRED_NAME_RE.search(block), label
