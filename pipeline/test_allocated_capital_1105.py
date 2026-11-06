"""Current allocation excludes stopped positions, without discarding freed cash."""
import json
from pathlib import Path
import build_trap_map as build

ROOT = Path(__file__).resolve().parent.parent


def test_closed_allocation_is_zero_on_archived_desktop_phone_and_home():
    d = json.loads((ROOT / "pipeline/private_archive/trap_map/trap_map.json").read_text())
    page = build.render_page(d)
    assert len([r for r in d["rows"] if r["status"] != "closed"]) == 6
    assert d["totals"]["cost"] == 18640.67
    for rid, cash, loss in (("lrcx-put", "$19,956.67", "−$1,043.33"),
                            ("ceg-q3", "$461.66", "−$715.01")):
        closed = page.split('id="row-' + rid + '"')[1].split('</tr>')[0]
        phone = page.split('id="' + rid + '"')[1].split('</details>')[0]
        chip = build.render_strip(d).split('href="trap-map.html#' + rid + '"')[1].split('</a>')[0]
        for surface in (closed, phone, chip):
            assert "Allocated $0.00" in surface
            assert "Freed cash " + cash in surface
        assert loss in closed and loss in phone
    for r in d["rows"]:
        if r["status"] != "closed":
            card = page.split('id="'+r["id"]+'"')[1].split('</details>')[0]
            assert "Allocated " + build.money(r["trade"]["cost"]) in card


def test_portfolio_and_benchmark_charts_use_starting_capital_not_open_allocation():
    d = json.loads((ROOT / "pipeline/private_archive/trap_map/trap_map.json").read_text())
    t = d["totals"]
    page = build.render_page(d)
    assert "Return on starting capital" in page
    assert "Starting capital " + build.money(t["portfolio_cost"]) in page
    assert "Freed cash" in page and "Total portfolio value" in page
    for field in ("portfolio_change", "spy_change"):
        assert f'{abs(100*t[field]/t["portfolio_cost"]):.1f}%' in page
    assert "Original S&amp;P 500 purchases are retained" in page
