"""Approved modeled stop exit for the Healthcare Abundance basket (HIMS Q3 subscribers)."""
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


def test_healthcare_modeled_stop_math_and_public_disclosure():
    d = private_records()
    r = next(row for row in d["rows"] if row["id"] == "healthcare-five")
    t = r["trade"]
    assert r["status"] == "closed"
    x = r["exit"]
    assert x["reason"] == "stop" and x["date"] == "2026-11-09"
    assert x["modeled"] is True
    assert x["subscribers_print_m"] == 2.788 < x["subscribers_stop_m"] == 2.891
    assert x["index_at_exit"] == 98.86 > x["index_stop"] == 90
    assert t["priced"] == "modeled_exit"
    assert "modeled session closing prices" in t["price_note"]
    assert "not a fill" in t["price_note"]
    assert (t["value"], t["change"], x["value"], x["result"]) == (4942.87, -57.13, 4942.87, -57.13)
    assert Decimal(str(x["value"])) - Decimal(str(t["cost"])) == Decimal("-57.13")
    assert x["legs"] == {"HIMS": 22.94, "GDRX": 3.65, "TEM": 84.37, "GH": 158.66, "ABT": 110.53}
    page = build.render_page(d)
    open_table = page.split('<tbody id="rows">')[1].split('</tbody>')[0]
    assert 'id="row-healthcare-five"' not in open_table
    closed = page.split('id="row-healthcare-five"')[1].split('</tr>')[0]
    phone = page.split('id="healthcare-five"')[1].split('</details>')[0]
    chip = build.render_strip(d).split('href="trap-map.html#healthcare-five"')[1].split('</a>')[0]
    for surface in (closed, phone, chip):
        assert "modeled session closing prices" in surface
        assert "not a fill" in surface
        assert "Allocated $0.00" in surface and "Freed cash $4,942.87" in surface
    assert "−$57.13" in closed and "−$57.13" in phone
    assert "$5,000.00" in closed and "2.788" in json.dumps(r)
    # No grading language / banned wording on the closed surfaces.
    blob = (closed + phone + chip).lower()
    assert "graded" not in blob and " bet" not in blob


def test_refresh_preserves_healthcare_closed_row(monkeypatch):
    d = private_records()
    d["rows"] = [r for r in d["rows"] if r["id"] in ("healthcare-five", "ceg-q3", "lrcx-put")]
    assert len(d["rows"]) == 3 and all(r["status"] == "closed" for r in d["rows"])
    before = copy.deepcopy(d["rows"])

    def unexpected_quote(*args, **kwargs):
        raise AssertionError("Closed positions must never be repriced")

    monkeypatch.setattr(prices, "spread_mark", unexpected_quote)
    now = datetime(2026, 11, 10, 15, tzinfo=ZoneInfo("America/Chicago"))
    monkeypatch.setattr(prices, "yahoo_close", lambda ticker: (100.0, now))
    assert prices.pull(d, now) == []
    assert d["rows"] == before


def test_locator_points_at_amended_private_archive():
    locator = json.loads((ROOT / "pipeline/trap_map_archive_locator.json").read_text())
    assert locator["private_commit"] == "c7eff38e3dd022d066dba968cb9866d74022c9c9"
    assert locator["manifest_sha256"] == "a357a38f8797e54a7ad20684f01cf66dc15bccfacb01e81606ccad16cf8b05c4"
    # Public portfolio JSON stays the Nov 5 frozen historical record.
    assert locator["public_historical_portfolio_sha256"] == "4ebf3187f46c4af2145c8db080be04ce4703463bcc90bdd6b4ab36559a9fa297"
    archive = private_archive()
    import hashlib
    assert hashlib.sha256((archive / "manifest.json").read_bytes()).hexdigest() == locator["manifest_sha256"]
