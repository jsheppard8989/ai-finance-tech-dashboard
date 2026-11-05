"""The approved LRCX stop fill must survive rebuilds and price refreshes."""
import copy
import json
from pathlib import Path

import build_trap_map as build

ROOT = Path(__file__).resolve().parent.parent


def data():
    return json.loads((ROOT / "site/data/trap_map.json").read_text())


def test_lrcx_stopped_at_authorized_fill():
    d = data()
    r = next(r for r in d["rows"] if r["id"] == "lrcx-put")
    assert r["status"] == "closed"
    assert r["exit"]["reason"] == "stop"
    assert r["exit"]["date"] == "2026-11-05"
    assert r["exit"]["premium_per_share"] == 16
    assert r["exit"]["result"] == -1043.33
    assert r["trade"]["mark"] == -16
    assert r["trade"]["value"] == 19956.67
    assert r["trade"]["change"] == -1043.33
    assert r["trade"]["premium"] - r["exit"]["premium_per_share"] * 100 == -1043.33
    assert "lrcx-put" not in [r["id"] for r in d["rows"] if r["status"] != "closed"]
    page = build.render_page(build.compute(copy.deepcopy(d)))
    open_table = page.split('<tbody id="rows">')[1].split('</tbody>')[0]
    assert 'id="row-lrcx-put"' not in open_table
    assert 'id="row-lrcx-put"' in page.split('id="closedwrap"')[1]
    assert "Stopped out Nov 5, 2026" in page
    assert "$16.00" in page and "−$1,043.33" in page


def test_closed_cash_and_realized_loss_reconcile_with_retained_benchmark():
    d = data()
    buys = copy.deepcopy(d["benchmark"]["buys"])
    # Exercise the accounting even before the production row is closed.
    r = next(r for r in d["rows"] if r["id"] == "lrcx-put")
    r["status"] = "closed"
    r["trade"].update(value=19956.67, change=-1043.33)
    r["exit"] = dict(reason="stop", date="2026-11-05", value=19956.67, result=-1043.33)
    t = build.compute(d)["totals"]
    open_rows = [r for r in d["rows"] if r["status"] != "closed"]
    assert t["cost"] == round(sum(r["trade"]["cost"] for r in open_rows), 2)
    assert t["value"] == round(sum(r["trade"]["value"] for r in open_rows), 2)
    assert t["realized_change"] == -1043.33
    assert t["closed_cash"] == 19956.67
    assert t["portfolio_cost"] == round(t["cost"] + 21000, 2)
    assert t["portfolio_value"] == round(t["value"] + t["closed_cash"], 2)
    assert t["portfolio_change"] == round(t["change"] - 1043.33, 2)
    assert t["spy_change"] == round(t["spy_value"] - t["portfolio_cost"], 2)
    assert d["benchmark"]["buys"] == buys


def test_refresh_preserves_closed_fill_without_requesting_option_quote(monkeypatch):
    import fetch_trap_map_prices as prices
    from datetime import datetime
    from zoneinfo import ZoneInfo

    d = data()
    row = copy.deepcopy(next(r for r in d["rows"] if r["id"] == "lrcx-put"))
    assert row["status"] == "closed"
    d["rows"] = [row]
    before = copy.deepcopy(row)
    def unexpected_quote(*args, **kwargs):
        raise AssertionError("Closed position must never be repriced")
    monkeypatch.setattr(prices, "spread_mark", unexpected_quote)
    now = datetime(2026, 11, 6, 15, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(prices, "yahoo_close", lambda ticker: (766.81, now))
    assert prices.pull(d, now) == []
    assert row == before
