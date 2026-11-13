"""Approved Nov 13 expiry closeout for the ASTS 43/37 and FRMI 3.00/2.50 put debit spreads."""
import copy
import json
from decimal import Decimal
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import build_trap_map as build
import fetch_trap_map_prices as prices
from trap_map_test_support import private_records, private_archive

ROOT = Path(__file__).resolve().parent.parent


def test_asts_frmi_expiry_settlement_and_surfaces():
    d = private_records()
    asts = next(row for row in d["rows"] if row["id"] == "asts-q3")
    frmi = next(row for row in d["rows"] if row["id"] == "frmi-q3")
    assert asts["status"] == "closed" and frmi["status"] == "closed"

    ax, fx = asts["exit"], frmi["exit"]
    assert ax["reason"] == "expiry" and ax["date"] == "2026-11-13"
    assert fx["reason"] == "expiry" and fx["date"] == "2026-11-13"
    assert "modeled" not in ax and "modeled" not in fx
    assert ax["stock_close"] == 32.6
    assert fx["stock_close"] == 2.61
    assert fx["basis"] == "stock-intrinsic"
    assert asts["trade"]["priced"] == "expiry_settlement"
    assert frmi["trade"]["priced"] == "expiry_settlement"
    assert asts["trade"]["price_note"] == "expiry, official close $32.60"
    assert frmi["trade"]["price_note"] == "expiry, official close $2.61, stock-intrinsic"
    assert "estimate_note" not in asts["trade"] and "estimate_note" not in frmi["trade"]

    assert (asts["trade"]["value"], asts["trade"]["change"], ax["value"], ax["result"]) == (4200, 2529.33, 4200, 2529.33)
    assert (frmi["trade"]["value"], frmi["trade"]["change"], fx["value"], fx["result"]) == (2340, 840, 2340, 840)
    assert Decimal(str(ax["value"])) - Decimal(str(asts["trade"]["cost"])) == Decimal("2529.33")
    assert Decimal(str(fx["value"])) - Decimal(str(frmi["trade"]["cost"])) == Decimal("840")
    # Official-close intrinsic: ASTS is the full $6 width; FRMI is $0.39 stock-intrinsic.
    assert Decimal("6") == min(max(Decimal("43") - Decimal("32.60"), Decimal("0")), Decimal("6"))
    assert Decimal("0.39") == min(max(Decimal("3.00") - Decimal("2.61"), Decimal("0")), Decimal("0.50"))

    page = build.render_page(d)
    open_table = page.split('<tbody id="rows">')[1].split('</tbody>')[0]
    assert 'id="row-asts-q3"' not in open_table
    assert 'id="row-frmi-q3"' not in open_table
    strip = build.render_strip(d)
    for rid, note, cash, pnl in (
        ("asts-q3", "expiry, official close $32.60", "$4,200.00", "+$2,529.33"),
        ("frmi-q3", "expiry, official close $2.61, stock-intrinsic", "$2,340.00", "+$840.00"),
    ):
        closed = page.split('id="row-' + rid + '"')[1].split("</tr>")[0]
        phone = page.split('id="' + rid + '"')[1].split("</details>")[0]
        chip = strip.split('href="trap-map.html#' + rid + '"')[1].split("</a>")[0]
        for surface in (closed, phone, chip):
            assert "Allocated $0.00" in surface and "Freed cash " + cash in surface
            assert "Closed at expiry" in surface
        assert pnl in closed and pnl in phone
        assert note in chip
        blob = (closed + phone + chip).lower()
        assert "graded" not in blob and " bet" not in blob and "better to be" not in blob
    assert "stock-intrinsic" in page and "no replacement" in page
    assert 'Allocated capital</div><div class="mid">$10,470.00</div>' in page


def test_refresh_preserves_asts_frmi_closed_rows(monkeypatch):
    d = private_records()
    d["rows"] = [r for r in d["rows"] if r["id"] in ("asts-q3", "frmi-q3")]
    assert len(d["rows"]) == 2 and all(r["status"] == "closed" for r in d["rows"])
    before = copy.deepcopy(d["rows"])

    def unexpected_quote(*args, **kwargs):
        raise AssertionError("Closed positions must never be repriced")

    monkeypatch.setattr(prices, "spread_mark", unexpected_quote)
    now = datetime(2026, 11, 13, 16, 30, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(prices, "yahoo_close", lambda ticker: (100.0, now))
    assert prices.pull(d, now) == []
    assert d["rows"] == before


def test_locator_points_at_amended_private_archive():
    locator = json.loads((ROOT / "pipeline/trap_map_archive_locator.json").read_text())
    assert locator["private_commit"] == "b790460e33f01d2449f47844a8c4347608a72809"
    assert locator["manifest_sha256"] == "f0771f33529441fb77a3d3b386843fb2d1aa15ccb6fc17d59cc0782515ee3572"
    assert locator["public_historical_portfolio_sha256"] == "4ebf3187f46c4af2145c8db080be04ce4703463bcc90bdd6b4ab36559a9fa297"
    archive = private_archive()
    import hashlib
    assert hashlib.sha256((archive / "manifest.json").read_bytes()).hexdigest() == locator["manifest_sha256"]
