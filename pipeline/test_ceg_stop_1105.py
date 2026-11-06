from trap_map_test_support import private_records
"""Approved modeled stop exit: preserve actual entry basis, not rounded display debit."""
import copy
import json
from decimal import Decimal
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import build_trap_map as build
import fetch_trap_map_prices as prices

ROOT = Path(__file__).resolve().parent.parent


def data():
    return private_records()


def test_ceg_modeled_stop_math_and_archived_disclosure():
    d = data()
    r = next(r for r in d["rows"] if r["id"] == "ceg-q3")
    t = r["trade"]
    assert r["status"] == "closed"
    x = r["exit"]
    assert x["reason"] == "stop" and x["date"] == "2026-11-05"
    assert x["modeled"] is True
    assert x["stock_close"] == 239.65 < x["stock_stop"] == 242.64
    assert t["stop"] == "Close if CEG closes below $242.64."
    assert x["sell_260C"] == 5.6333 and x["buy_290C"] == 1.0167
    net = Decimal(str(x["sell_260C"])) - Decimal(str(x["buy_290C"]))
    assert net == Decimal("4.6166")
    cash = net * 100 * t["contracts"]
    assert cash == Decimal("461.66")
    assert cash - Decimal(str(t["cost"])) == Decimal("-715.01")
    assert (t["mark"], t["value"], t["change"], x["result"]) == (4.6166, 461.66, -715.01, -715.01)
    page = build.render_page(d)
    open_table = page.split('<tbody id="rows">')[1].split('</tbody>')[0]
    assert 'id="row-ceg-q3"' not in open_table
    closed = page.split('id="row-ceg-q3"')[1].split('</tr>')[0]
    phone = page.split('id="ceg-q3"')[1].split('</details>')[0]
    chip = build.render_strip(d).split('href="trap-map.html#ceg-q3"')[1].split('</a>')[0]
    for surface in (closed, phone, chip):
        assert "modeled close on late-day quotes" in surface
        assert "not a contemporaneous fill" in surface
        assert "Allocated $0.00" in surface and "Freed cash $461.66" in surface
    assert "−$715.01" in closed and "−$715.01" in phone
    assert "$1,176.67" in closed and "$239.65" in closed and "$242.64" in closed


def test_refresh_preserves_both_closed_rows(monkeypatch):
    d = data()
    d["rows"] = [r for r in d["rows"] if r["id"] in ("ceg-q3", "lrcx-put")]
    assert len(d["rows"]) == 2 and all(r["status"] == "closed" for r in d["rows"])
    before = copy.deepcopy(d["rows"])
    def unexpected_quote(*args, **kwargs):
        raise AssertionError("Closed positions must never be repriced")
    monkeypatch.setattr(prices, "spread_mark", unexpected_quote)
    now = datetime(2026, 11, 6, 15, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(prices, "yahoo_close", lambda ticker: (766.81, now))
    assert prices.pull(d, now) == []
    assert d["rows"] == before
