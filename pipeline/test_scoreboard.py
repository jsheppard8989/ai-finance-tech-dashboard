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
    assert sb["record"]["open_stale_after_ct"] == "2026-11-27T12:15:00-06:00"  # Fri half day, option close
    sb_mid, _ = _build(book, saved, _ct(2026, 11, 27, 12, 1))
    assert sb_mid["record"]["open_is_stale"] is False  # option session still open
    sb2, _ = _build(book, saved, _ct(2026, 11, 27, 12, 15, 1))
    assert sb2["record"]["open_is_stale"] is True
    assert "Today's" not in json.dumps(sb)
    assert pq.STALE_TRADING_DAYS == 1


def test_calendar():
    assert not mc.is_trading_day(datetime(2026, 11, 26).date())
    assert mc.session_close(datetime(2026, 11, 27).date()).hour == 12
    assert mc.stale_after(datetime(2026, 11, 24, 14, 59, tzinfo=CT)).isoformat() == "2026-11-25T15:00:00-06:00"
    assert mc.in_regular_session(datetime(2026, 11, 25, 15, 14, 59, tzinfo=CT), "option")
    assert not mc.in_regular_session(datetime(2026, 11, 25, 15, 14, 59, tzinfo=CT), "share")
    assert not mc.in_regular_session(datetime(2026, 11, 25, 19, 0, tzinfo=CT), "option")
    assert not mc.in_regular_session(datetime(2026, 11, 25, 19, 0, tzinfo=CT), "share")


def _ct(y, mo, d, h, mi, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=CT)


def test_quote_cutoff_boundaries():
    # Regular session: shares through 15:00:00, options through 15:15:00 (inclusive).
    d = datetime(2026, 11, 25).date()
    assert mc.quote_cutoff(d, "share") == _ct(2026, 11, 25, 15, 0, 0)
    assert mc.quote_cutoff(d, "option") == _ct(2026, 11, 25, 15, 15, 0)
    assert mc.in_regular_session(_ct(2026, 11, 25, 15, 0, 0), "share")
    assert not mc.in_regular_session(_ct(2026, 11, 25, 15, 0, 1), "share")
    assert mc.in_regular_session(_ct(2026, 11, 25, 15, 15, 0), "option")
    assert not mc.in_regular_session(_ct(2026, 11, 25, 15, 15, 1), "option")
    # A 15:14:59 option quote (TLT) is in session; the same stamp is not a share mark.
    assert mc.in_regular_session(_ct(2026, 11, 25, 15, 14, 59), "option")
    assert not mc.in_regular_session(_ct(2026, 11, 25, 15, 14, 59), "share")
    # Half day (Fri Nov 27, 2026): shares 12:00 PM CT, options 12:15 PM CT.
    hd = datetime(2026, 11, 27).date()
    assert hd in mc.NYSE_EARLY_CLOSES
    assert mc.quote_cutoff(hd, "share") == _ct(2026, 11, 27, 12, 0, 0)
    assert mc.quote_cutoff(hd, "option") == _ct(2026, 11, 27, 12, 15, 0)
    assert mc.in_regular_session(_ct(2026, 11, 27, 12, 0, 0), "share")
    assert not mc.in_regular_session(_ct(2026, 11, 27, 12, 0, 1), "share")
    assert mc.in_regular_session(_ct(2026, 11, 27, 12, 15, 0), "option")
    assert not mc.in_regular_session(_ct(2026, 11, 27, 12, 15, 1), "option")
    assert not mc.in_regular_session(_ct(2026, 11, 27, 12, 14, 59), "share")
    assert mc.in_regular_session(_ct(2026, 11, 27, 12, 14, 59), "option")


def _assert_mark_at_or_before_cutoff(row: dict, kind: str, label: str) -> None:
    ts = pq.parse_ct_timestamp(row.get("mark_time_ct"))
    assert ts is not None, f"{label}: missing mark_time_ct"
    local = ts.astimezone(CT)
    cutoff = mc.quote_cutoff(local.date(), kind)
    assert local <= cutoff, f"{label}: mark {local.isoformat()} is after the {kind} cutoff {cutoff.isoformat()}"
    for i, leg in enumerate(((row.get("audit") or {}).get("mark") or {}).get("legs") or []):
        lts = pq.parse_ct_timestamp(leg.get("quote_time_ct"))
        if lts is None:
            continue
        ll = lts.astimezone(CT)
        lcut = mc.quote_cutoff(ll.date(), kind)
        assert ll <= lcut, (
            f"{label} audit.mark.legs[{i}]: {ll.isoformat()} is after the {kind} cutoff {lcut.isoformat()}"
        )


def test_displayed_option_marks_not_after_option_close(book, saved):
    sb, held = _build(book, saved)
    assert held == []
    rows = [r for r in sb["open"] if not r.get("is_cash_park") and not r.get("shares")]
    assert rows, "expected open option rows"
    for row in rows:
        _assert_mark_at_or_before_cutoff(row, "option", row["id"])
    committed = json.loads((SITE / "data" / "scoreboard.json").read_text())
    for row in committed["open"]:
        if row.get("is_cash_park") or row.get("shares"):
            continue
        _assert_mark_at_or_before_cutoff(row, "option", f"committed {row['id']}")
    # TLT's 3:14:59 PM CT mark stays accepted under the 3:15 option close.
    tlt = next(r for r in committed["open"] if r["id"] == "ric-1123-tlt")
    assert tlt["mark_time_ct"] == "2026-11-25T15:14:59-06:00"


def test_displayed_share_marks_not_after_share_close(book, saved):
    sb, held = _build(book, saved)
    assert held == []
    park = sb["cash_park"]
    _assert_mark_at_or_before_cutoff(park, "share", park["id"])
    committed = json.loads((SITE / "data" / "scoreboard.json").read_text())
    _assert_mark_at_or_before_cutoff(committed["cash_park"], "share", "committed cash_park")


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
    assert "$13,200.00" in tlt["audit"]["entry"]["math"]
    assert "$15,660.00" in tlt["audit"]["mark"]["math"]
    mu = next(r for r in sb["closed"] if r["id"] == "mu-cycle")
    assert "$7,466.67" in mu["audit"]["entry"]["math"]
    assert "$9,110.00" in mu["audit"]["exit"]["math"]
    asts = next(r for r in sb["closed"] if r["id"] == "asts-q3")
    assert "$4,200.00" in asts["audit"]["exit"]["math"]


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
    assert ("Option marks use the last regular-session quote at or before the 3:15 PM CT "
            "option close; share marks use the last quote at or before the 3:00 PM CT close. "
            "After-hours quotes are never used.") in html
    assert "./js/scoreboard.js" in html


def test_home_summary():
    html = (SITE / "index.html").read_text()
    assert 'data-scoreboard="summary"' in html and "./js/scoreboard.js" in html
    assert html.index('id="scoreboard-summary"') < html.index('id="signup"')


def test_scoreboard_js_has_no_todays_label():
    js = (SITE / "js" / "scoreboard.js").read_text()
    assert "Today's" not in js and "Mark as of" in js

# --------------------------------------------------------------------------- displayed price × qty ties to dollars

_ROUNDED = " (rounded)"
_DOLLAR = re.compile(r"\$([\d,]+(?:\.\d+)?)")
_OPTION_PRODUCT = re.compile(
    r"\(([\d.]+(?:\s*-\s*[\d.]+)*)\)\s*×\s*(\d+)\s*×\s*100\s*=\s*\$([\d,]+(?:\.\d+)?)(?:\s*\(rounded\))?"
)
_SHARE_PRODUCT = re.compile(
    r"(\d+)\s+sh\s+×\s*([\d.]+)\s*=\s*\$([\d,]+(?:\.\d+)?)(?:\s*\(rounded\))?"
)
_SINGLE_PRODUCT = re.compile(
    r"\$?([\d.]+)\s*×\s*(\d+)\s*=\s*\$([\d,]+(?:\.\d+)?)(?:\s*\(rounded\))?"
)
_WORTH_PRODUCT = re.compile(
    r"worth\s+\$([\d.]+)\s*×\s*(\d+)\s*×\s*100\s*=\s*\$([\d,]+(?:\.\d+)?)(?:\s*\(rounded\))?"
)


def _cents(s: str) -> float:
    return bs.r2(float(s.replace(",", "")))


def _assert_product(price: float, qty: float, dollars: float, rounded: bool, label: str) -> None:
    got = bs.r2(price * qty)
    dollars = bs.r2(dollars)
    if rounded:
        assert got != dollars, f"{label}: labeled rounded but {price} × {qty} already equals {dollars}"
        return
    assert got == dollars, f"{label}: {price} × {qty} = {got}, expected {dollars}"


def test_unit_price_formatter_examples():
    # TLT entry: 2 and 4 decimal prices do not reproduce $13,200.00
    text, rounded = bs.format_unit_price(1.466667, 13200.0, 9000)
    assert text == "$1.4667" and rounded is True
    # GOOGL mark
    text, rounded = bs.format_unit_price(9.416667, 5650.0, 600)
    assert text == "$9.4167" and rounded is True
    # GOOGL entry ties at 2 decimals
    text, rounded = bs.format_unit_price(10.80, 6480.0, 600)
    assert text == "$10.80" and rounded is False
    # TLT mark ties at 2 decimals
    text, rounded = bs.format_unit_price(1.74, 15660.0, 9000)
    assert text == "$1.74" and rounded is False


def test_leg_fill_math_uses_4dp_when_uneven():
    # TLT mark legs: /3 is not even
    assert bs.leg_fill_math({"side": "sell to close", "bid": 1.93, "ask": 1.98}) == (
        "1.93 + (1.98 - 1.93)/3 = 1.9467"
    )
    assert bs.leg_fill_math({"side": "buy to close", "bid": 0.20, "ask": 0.21}) == (
        "0.21 - (0.21 - 0.20)/3 = 0.2067"
    )
    # GOOGL entry legs
    assert bs.leg_fill_math({"side": "buy", "bid": 16.20, "ask": 16.70}) == (
        "16.70 - (16.70 - 16.20)/3 = 16.5333"
    )
    assert bs.leg_fill_math({"side": "sell", "bid": 5.60, "ask": 6.00}) == (
        "5.60 + (6.00 - 5.60)/3 = 5.7333"
    )
    # Even /3 stays at 2 decimals (TLT entry long, STRC mark, GEV entry)
    assert bs.leg_fill_math({"side": "buy", "bid": 1.61, "ask": 1.64}) == (
        "1.64 - (1.64 - 1.61)/3 = 1.63"
    )
    assert bs.leg_fill_math({"side": "sell to close", "bid": 97.68, "ask": 97.83}) == (
        "97.68 + (97.83 - 97.68)/3 = 97.73"
    )
    assert bs.leg_fill_math({"side": "buy", "bid": 42.00, "ask": 48.00}) == (
        "48.00 - (48.00 - 42.00)/3 = 46.00"
    )


def test_option_product_uses_displayed_leg_fills():
    # TLT mark: product must use the 4-dec leg fills, and they do tie to $15,660.00
    assert bs.format_option_product([1.946667, 0.206667], 90, 15660.0) == (
        "(1.9467 - 0.2067) × 90 × 100 = $15,660.00"
    )
    # TLT entry: mixed 2-and-4 displayed fills, does not tie
    assert bs.format_option_product([1.63, 0.163333], 90, 13200.0) == (
        "(1.63 - 0.1633) × 90 × 100 = $13,200.00 (rounded)"
    )
    # GOOGL entry: 4-dec legs that still tie
    assert bs.format_option_product([16.533333, 5.733333], 6, 6480.0) == (
        "(16.5333 - 5.7333) × 6 × 100 = $6,480.00"
    )


def _check_row_displays(row: dict, *, options_qty: int | None, shares: int | None) -> list[str]:
    """Return a list of (label, before-not-used) — actually just assert; called per row."""
    rid = row["id"]
    if options_qty:
        mult = options_qty * 100
        if row.get("entry_text"):
            rounded = _ROUNDED in row["entry_text"]
            m = _DOLLAR.search(row["entry_text"])
            assert m, f"{rid} entry_text has no price: {row['entry_text']!r}"
            _assert_product(_cents(m.group(1)), mult, row["cost"], rounded, f"{rid} entry_text")
            if rounded:
                # confirm 2 and 4 don't tie using the raw debit implied by cost would need book;
                # check against displayed 4-dec price not equaling cost.
                assert bs.r2(_cents(m.group(1)) * mult) != bs.r2(row["cost"]), f"{rid} entry labeled rounded but ties"
        if row.get("mark_text"):
            rounded = _ROUNDED in row["mark_text"]
            m = _DOLLAR.search(row["mark_text"])
            assert m, f"{rid} mark_text has no price: {row['mark_text']!r}"
            _assert_product(_cents(m.group(1)), mult, row["value"], rounded, f"{rid} mark_text")
            if rounded:
                assert bs.r2(_cents(m.group(1)) * mult) != bs.r2(row["value"]), f"{rid} mark labeled rounded but ties"
    if shares:
        if row.get("entry_text"):
            rounded = _ROUNDED in row["entry_text"]
            m = _DOLLAR.search(row["entry_text"])
            assert m, f"{rid} entry_text has no price: {row['entry_text']!r}"
            _assert_product(_cents(m.group(1)), shares, row["cost"], rounded, f"{rid} entry_text")
            if rounded:
                assert bs.r2(_cents(m.group(1)) * shares) != bs.r2(row["cost"])
        if row.get("mark_text"):
            rounded = _ROUNDED in row["mark_text"]
            m = _DOLLAR.search(row["mark_text"])
            assert m, f"{rid} mark_text has no price: {row['mark_text']!r}"
            _assert_product(_cents(m.group(1)), shares, row["value"], rounded, f"{rid} mark_text")
            if rounded:
                assert bs.r2(_cents(m.group(1)) * shares) != bs.r2(row["value"])
    audit = row.get("audit") or {}
    for section in ("entry", "mark", "exit"):
        block = audit.get(section) or {}
        math = block.get("math") or ""
        if not math:
            continue
        rounded = math.endswith(_ROUNDED.strip()) or math.rstrip().endswith("rounded)")
        if m := _OPTION_PRODUCT.search(math):
            fill_texts = [x.strip() for x in m.group(1).split("-")]
            fills = [float(x) for x in fill_texts]
            contracts = int(m.group(2))
            dollars = _cents(m.group(3))
            net = fills[0] - sum(fills[1:])
            _assert_product(net, contracts * 100, dollars, rounded, f"{rid} audit.{section} {math}")
            if rounded:
                assert bs.r2(net * contracts * 100) != dollars
            leg_texts = _displayed_leg_fill_texts(block)
            if leg_texts:
                assert fill_texts == leg_texts, (
                    f"{rid} audit.{section}: product operands {fill_texts} != displayed legs {leg_texts}"
                )
        elif m := _SHARE_PRODUCT.search(math):
            sh, price_text, dollars = int(m.group(1)), m.group(2), _cents(m.group(3))
            price = float(price_text)
            _assert_product(price, sh, dollars, rounded, f"{rid} audit.{section} {math}")
            if rounded:
                assert bs.r2(price * sh) != dollars
            leg_texts = _displayed_leg_fill_texts(block)
            if leg_texts:
                assert price_text == leg_texts[0], (
                    f"{rid} audit.{section}: product price {price_text} != displayed leg {leg_texts[0]}"
                )
        elif m := _WORTH_PRODUCT.search(math):
            price, contracts, dollars = float(m.group(1)), int(m.group(2)), _cents(m.group(3))
            _assert_product(price, contracts * 100, dollars, rounded, f"{rid} audit.{section} {math}")
            if rounded:
                assert bs.r2(price * contracts * 100) != dollars
        elif m := _SINGLE_PRODUCT.search(math):
            # first match might be later in a compound sentence (LRCX exit has two products)
            for idx, m in enumerate(_SINGLE_PRODUCT.finditer(math)):
                price_text, qty, dollars = m.group(1), int(m.group(2)), _cents(m.group(3))
                price = float(price_text)
                chunk_rounded = "(rounded)" in math[m.start():m.end()+12]
                _assert_product(price, qty, dollars, chunk_rounded, f"{rid} audit.{section} {m.group(0)}")
                if chunk_rounded:
                    assert bs.r2(price * qty) != dollars
                leg_texts = _displayed_leg_fill_texts(block)
                # One-leg entry products (LRCX credit) must match the displayed fill.
                # Exit lines like "$16.00 × 100" have no fill-rule legs.
                if len(leg_texts) == 1 and idx == 0:
                    assert price_text == leg_texts[0], (
                        f"{rid} audit.{section}: product price {price_text} != displayed leg {leg_texts[0]}"
                    )
        for i, leg in enumerate(block.get("legs") or []):
            if "bid" in leg and "ask" in leg:
                _assert_leg_fill(leg, f"{rid} audit.{section}.legs[{i}]")


_LEG_MATH = re.compile(
    r"([\d.]+)\s*([+-])\s*\(([\d.]+)\s*-\s*([\d.]+)\)/3\s*=\s*([\d.]+)"
)


def _displayed_leg_fill_texts(block: dict) -> list[str]:
    out = []
    for leg in block.get("legs") or []:
        m = _LEG_MATH.search(leg.get("math") or "")
        if m:
            out.append(m.group(5))
    return out


def _assert_leg_fill(leg: dict, label: str) -> None:
    """Displayed fill must equal the bid/ask fill-rule result at 4dp; 2dp only if even."""
    math = leg.get("math") or ""
    m = _LEG_MATH.search(math)
    assert m, f"{label}: no fill-rule formula in {math!r}"
    bid, ask = float(leg["bid"]), float(leg["ask"])
    buy_side = str(leg.get("side") or "").lower().startswith("buy")
    expected = bs.buy_fill(bid, ask) if buy_side else bs.sell_fill(bid, ask)
    shown = float(m.group(5))
    assert bs._rn(shown, 4) == bs._rn(expected, 4), (
        f"{label}: displayed {shown} != fill-rule {expected} at 4dp ({math})"
    )
    even = bs._rn(expected, 4) == bs._rn(expected, 2)
    places = 2 if even else 4
    want = f"{bs._rn(expected, places):.{places}f}"
    assert m.group(5) == want, f"{label}: showed {m.group(5)}, expected {want} ({math})"
    if buy_side:
        assert m.group(2) == "-", f"{label}: buy leg should subtract the /3 ({math})"
        assert float(m.group(1)) == bs._rn(ask, 2)
        assert float(m.group(3)) == bs._rn(ask, 2)
        assert float(m.group(4)) == bs._rn(bid, 2)
    else:
        assert m.group(2) == "+", f"{label}: sell leg should add the /3 ({math})"
        assert float(m.group(1)) == bs._rn(bid, 2)
        assert float(m.group(3)) == bs._rn(ask, 2)
        assert float(m.group(4)) == bs._rn(bid, 2)


def _qty_of(row: dict) -> tuple[int | None, int | None]:
    if row.get("id") == "strc-park" or (row.get("is_cash_park") and "sh at" in (row.get("entry_text") or "")):
        m = re.search(r"(\d+)\s+sh", row.get("entry_text") or "")
        return None, int(m.group(1)) if m else 805
    st = row.get("structure") or ""
    m = re.search(r"[×x](\d+)", st)
    if m:
        return int(m.group(1)), None
    return None, None


def test_displayed_prices_tie_out_on_build(book, saved):
    sb, held = _build(book, saved)
    assert held == []
    rows = list(sb["open"]) + list(sb["closed"]) + ([sb["cash_park"]] if sb.get("cash_park") else [])
    for row in rows:
        opt, sh = _qty_of(row)
        _check_row_displays(row, options_qty=opt, shares=sh)


def test_displayed_prices_tie_out_on_committed_scoreboard():
    sb = json.loads((SITE / "data" / "scoreboard.json").read_text())
    rows = list(sb["open"]) + list(sb["closed"]) + ([sb["cash_park"]] if sb.get("cash_park") else [])
    for row in rows:
        opt, sh = _qty_of(row)
        _check_row_displays(row, options_qty=opt, shares=sh)



# --------------------------------------------------------------------------- session-based staleness
def _check(mark, kind, now, expect):
    """is_stale and the published stale_after (what the page compares to) must agree."""
    assert mc.is_stale(mark, now, kind) is expect, (mark, kind, now)
    assert (now > mc.stale_after(mark, kind)) is expect, (mark, kind, now)


def test_stale_thanksgiving_wed_option_mark():
    mark = _ct(2026, 11, 25, 15, 14, 59)  # TLT leg stamp, Wed before Thanksgiving
    assert mc.stale_after(mark, "option") == _ct(2026, 11, 27, 12, 15)
    for now in (_ct(2026, 11, 25, 16, 0), _ct(2026, 11, 26, 0, 1), _ct(2026, 11, 26, 16, 4),
                _ct(2026, 11, 26, 23, 59), _ct(2026, 11, 27, 8, 30), _ct(2026, 11, 27, 12, 14, 59),
                _ct(2026, 11, 27, 12, 15, 0)):
        _check(mark, "option", now, False)
    for now in (_ct(2026, 11, 27, 12, 15, 1), _ct(2026, 11, 27, 15, 15, 1), _ct(2026, 11, 28, 10, 0)):
        _check(mark, "option", now, True)


def test_stale_weekend_friday_close_mark():
    opt = _ct(2026, 11, 20, 15, 10)  # Fri option mark
    shr = _ct(2026, 11, 20, 14, 55)  # Fri share mark
    for now in (_ct(2026, 11, 21, 12, 0), _ct(2026, 11, 22, 20, 0), _ct(2026, 11, 23, 9, 0),
                _ct(2026, 11, 23, 14, 59, 59)):
        _check(opt, "option", now, False)
        _check(shr, "share", now, False)
    _check(shr, "share", _ct(2026, 11, 23, 15, 0, 1), True)
    _check(opt, "option", _ct(2026, 11, 23, 15, 0, 1), False)
    _check(opt, "option", _ct(2026, 11, 23, 15, 15, 1), True)


def test_stale_half_day_black_friday():
    mark = _ct(2026, 11, 25, 14, 59)  # Wed marks, Thu holiday, Fri half day
    assert mc.stale_after(mark, "share") == _ct(2026, 11, 27, 12, 0)
    assert mc.stale_after(mark, "option") == _ct(2026, 11, 27, 12, 15)
    _check(mark, "share", _ct(2026, 11, 27, 11, 59), False)
    _check(mark, "share", _ct(2026, 11, 27, 12, 0, 1), True)
    _check(mark, "option", _ct(2026, 11, 27, 12, 0, 1), False)
    _check(mark, "option", _ct(2026, 11, 27, 12, 15, 1), True)
    # The full-day closes (3:00 / 3:15) are not used on a half day.
    assert mc.stale_after(mark, "share") != _ct(2026, 11, 27, 15, 0)
    assert mc.stale_after(mark, "option") != _ct(2026, 11, 27, 15, 15)
    _check(mark, "share", _ct(2026, 11, 27, 14, 0), True)
    _check(mark, "option", _ct(2026, 11, 27, 14, 0), True)


def test_stale_monday_holiday():
    mark = _ct(2026, 2, 13, 14, 50)  # Fri before Presidents Day (Mon Feb 16, 2026)
    assert mc.stale_after(mark, "share") == _ct(2026, 2, 17, 15, 0)
    assert mc.stale_after(mark, "option") == _ct(2026, 2, 17, 15, 15)
    for now in (_ct(2026, 2, 16, 15, 30), _ct(2026, 2, 17, 14, 59)):
        _check(mark, "share", now, False)
        _check(mark, "option", now, False)
    _check(mark, "share", _ct(2026, 2, 17, 15, 0, 1), True)
    _check(mark, "option", _ct(2026, 2, 17, 15, 15, 1), True)
    m27 = _ct(2027, 1, 15, 15, 0)  # MLK Day 2027 is Mon Jan 18
    assert mc.stale_after(m27, "option") == _ct(2027, 1, 19, 15, 15)


def test_mark_session_attribution():
    assert mc.mark_session(_ct(2026, 11, 25, 19, 0)) == _ct(2026, 11, 25, 0, 0).date()  # after close: same day
    assert mc.mark_session(_ct(2026, 11, 26, 9, 2)) == _ct(2026, 11, 25, 0, 0).date()   # holiday: prior session
    assert mc.mark_session(_ct(2026, 11, 23, 7, 0)) == _ct(2026, 11, 20, 0, 0).date()   # pre-open Mon: Fri
    assert mc.last_completed_session(_ct(2026, 11, 26, 16, 4), "option") == _ct(2026, 11, 25, 0, 0).date()


def test_calendar_table_2026_2027():
    hol = sorted(d.isoformat() for d in mc.NYSE_HOLIDAYS)
    assert len(hol) == 20 and hol[0] == "2026-01-01" and hol[-1] == "2027-12-24"
    assert all(mc.is_trading_day(d) for d in mc.NYSE_EARLY_CLOSES)
    assert not mc.NYSE_HOLIDAYS & mc.NYSE_EARLY_CLOSES
    assert all(d.weekday() < 5 for d in mc.NYSE_HOLIDAYS)


def test_scoreboard_rows_thanksgiving_afternoon(book, saved):
    now = _ct(2026, 11, 26, 16, 4)
    sb, held = _build(book, saved, now)
    assert not held
    by = {r["ticker"]: r for r in sb["open"]}
    assert by["TLT"]["mark_time_ct"] == "2026-11-25T15:14:59-06:00"
    assert by["TLT"]["is_stale"] is False and by["TLT"]["stale_after_ct"] == "2026-11-27T12:15:00-06:00"
    assert by["GOOGL"]["is_stale"] is False and by["GOOGL"]["stale_after_ct"] == "2026-11-27T12:15:00-06:00"
    assert sb["cash_park"]["is_stale"] is True  # Tue Nov 24 share mark; Wed's session closed
    assert sb["cash_park"]["stale_after_ct"] == "2026-11-25T15:00:00-06:00"
    later, _ = _build(book, saved, _ct(2026, 11, 27, 12, 15, 1))
    assert all(r["is_stale"] for r in later["open"]) and later["record"]["open_is_stale"]
