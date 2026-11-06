"""Regression checks for the saved Oct 29 opening quotes, never later marks."""
import copy
import importlib.util
import json
import re
from fractions import Fraction
from pathlib import Path

import pytest

import build_trap_map

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "site/data/trap_map.json"
# Opening snapshots documented by the Nov 5 entry-fill audit.
ENTRIES = {
    "ASTS": ("3.30", "3.60", "1.03", "1.28", 7, 43, 37, 1670.67),
    "FRMI": (".35", ".45", ".15", ".20", 60, 3, 2.5, 1500.00),
    "TSAT": ("5.80", "6.60", "3.00", "3.50", 5, 40, 30, 1583.33),
    "MU": ("108", "128", "40", "60", 1, 700, 500, 7466.67),
}


def load():
    return json.loads(DATA.read_text())


def migration():
    spec = importlib.util.spec_from_file_location("entry_fills", ROOT / "scripts/reprice_entry_fills_1105.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("ticker", ENTRIES)
def test_entry_costs_use_original_bid_asks(ticker):
    d = load()
    row = next(r for r in d["rows"] if r["ticker"] == ticker)
    t = row["trade"]
    lb, la, sb, sa, n, long_k, short_k, cost = ENTRIES[ticker]
    lb, la, sb, sa = map(Fraction, (lb, la, sb, sa))
    debit = la - (la - lb) / 3 - (sb + (sa - sb) / 3)
    assert round(float(debit * 100 * n), 2) == cost
    assert t["cost"] == cost
    assert t["max_loss"] == f"${cost:,.2f}"
    assert t["entry_debit"] == pytest.approx(float(debit))
    assert t["breakeven"] == pytest.approx(float(long_k - debit))
    assert t["max_profit"] == round(float((Fraction(str(long_k)) - Fraction(str(short_k)) - debit) * 100 * n), 2)
    assert t["contracts"] == n
    assert t["exit"] == {"type": "expiry", "date": t["expiry"]}
    assert t["change"] == round(t["value"] - t["cost"], 2)
    assert not re.search(r"at mid|midpoint|the mid|fill at mid", json.dumps(row), re.I)
    entry = t["entry_pricing"]
    assert entry["rule"] == "third_from_worst"
    assert entry["snapshot_date"] == "2026-10-29"
    assert [(x["bid"], x["ask"]) for x in entry["legs"]] == [(float(lb), float(la)), (float(sb), float(sa))]


def test_original_date_benchmark_and_totals():
    d = load()
    lot = next(x for x in d["benchmark"]["buys"] if x["date"] == "2026-10-29")
    assert lot["price"] == 769.36
    assert lot["dollars"] == 12220.67
    assert lot["shares"] == pytest.approx(12220.67 / 769.36, abs=0.000005)
    # LRCX and CEG are closed: open allocation excludes both; portfolio_* retains original capital.
    open_rows = [r for r in d["rows"] if r["status"] != "closed"]
    lrcx = next(r for r in d["rows"] if r["id"] == "lrcx-put")
    assert lrcx["status"] == "closed"
    assert lrcx["exit"]["result"] == -1043.33
    ceg = next(r for r in d["rows"] if r["id"] == "ceg-q3")
    assert ceg["status"] == "closed"
    assert ceg["exit"]["result"] == -715.01
    assert ceg["exit"]["modeled"] is True
    assert len(open_rows) == 6
    assert d["totals"]["cost"] == round(sum(r["trade"]["cost"] for r in open_rows), 2) == 18640.67
    assert d["totals"]["realized_change"] == -1758.34
    # Original funded capital is the return/benchmark basis, NOT current allocation.
    original_capital = sum(r["trade"]["cost"] for r in d["rows"])
    released_capital = lrcx["trade"]["cost"] + ceg["trade"]["cost"]
    assert released_capital == 22176.67
    assert d["totals"]["portfolio_cost"] == round(original_capital, 2) == 40817.34
    assert d["totals"]["cost"] == round(original_capital - released_capital, 2)
    assert d["totals"]["value"] == round(sum(r["trade"]["value"] for r in open_rows), 2)
    assert lrcx["exit"]["value"] == 19956.67
    assert ceg["exit"]["value"] == 461.66
    assert d["totals"]["closed_cash"] == round(lrcx["exit"]["value"] + ceg["exit"]["value"], 2) == 20418.33
    assert d["totals"]["portfolio_value"] == round(d["totals"]["value"] + d["totals"]["closed_cash"], 2)
    assert d["totals"]["portfolio_change"] == round(d["totals"]["change"] + d["totals"]["realized_change"], 2)
    assert d["totals"]["portfolio_change"] == round(d["totals"]["portfolio_value"] - original_capital, 2)
    assert d["totals"]["spy_change"] == round(d["totals"]["spy_value"] - original_capital, 2)
    assert any("lrcx-put" in lot.get("rows", []) for lot in d["benchmark"]["buys"])
    page = build_trap_map.render_page(d)
    assert 'Allocated capital</div><div class="mid">$18,640.67</div>' in page
    assert 'Original allocation</div>' not in page
    assert build_trap_map.compute(copy.deepcopy(d)) == d


def test_caveats_are_anchored_to_repriced_entries():
    rows = {r["ticker"]: r for r in load()["rows"]}
    assert "Few contracts trade; this modeled fill is not assured" in rows["FRMI"]["trade"]["expression"]["caveat"]
    assert "40P: 2" in rows["TSAT"]["trade"]["expression"]["caveat"]
    caveat = rows["MU"]["trade"]["expression"]["caveat"]
    assert "$20 wide" in caveat and "previous day" in caveat and "not assured" in caveat
    assert "$625.33" in rows["MU"]["what_proves_it"]


def test_repricing_is_idempotent_and_preserves_current_marks():
    d = load()
    # Entry calculations must not depend on any newer mark/quoted time.
    for r in d["rows"]:
        if r["ticker"] in ENTRIES:
            r["trade"]["mark"] = 99.1234
            r["trade"]["value"] = 9876.54
            r["trade"]["quoted"] = "A deliberately unrelated later quote"
    before = copy.deepcopy(d)
    migration().apply(d)
    once = copy.deepcopy(d)
    migration().apply(d)
    assert d == once
    for r, original in zip(d["rows"], before["rows"]):
        if r["ticker"] not in ENTRIES:
            assert r == original
        else:
            for key in ("mark", "value", "quoted", "mid_time", "mid_source", "legs", "contracts", "posted", "expiry", "exit"):
                assert r["trade"][key] == original["trade"][key]
    assert d["benchmark"]["buys"][1:] == before["benchmark"]["buys"][1:]


def test_mu_source_page_and_chart_terms_are_synchronized():
    for path in (ROOT / "docs/research/mu/mu_page.md", ROOT / "site/mu-memory-cycle.html"):
        text = path.read_text()
        for old in ("$68.00", "$6,800", "$13,200", "$632", "debit at the midpoint"):
            assert old not in text, (path, old)
        for new in ("$74.666667", "$7,466.67", "$12,533.33", "$625.33", "$20 wide", "previous day"):
            assert new in text, (path, new)
        assert not re.search(r"\b(?:graded?|grading|bets?|thin)\b", text, re.I)
        assert "zero at breakeven" in text
        assert "at or above $700" in text
    from PIL import Image
    for n in (2, 3):
        with Image.open(ROOT / f"site/charts/mu/0{n}.png") as image:
            assert "$625.33" in image.info.get("Description", "")
