import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import export_commentary as ec
from market_data_io import strip_internal_notes

POST = """---
title: Rates & <b>risk</b>
date: 2026-10-23
author: Ric Santori
---
Funding is **tight**; see [the H.4.1](https://www.federalreserve.gov/releases/h41/).

<script>alert(1)</script>

- one
- *two*
"""


def test_render_escapes_raw_html(tmp_path):
    (tmp_path / "2026-10-23.md").write_text(POST)
    (tmp_path / "2026-10-20.md").write_text(POST.replace("2026-10-23", "2026-10-20").replace("Rates", "Old"))
    d = ec.build(tmp_path)
    assert d["date"] == "2026-10-23" and d["author"] == "Ric Santori"
    assert d["title"] == "Rates &amp; &lt;b&gt;risk&lt;/b&gt;"
    assert "<script" not in d["html"] and "&lt;script&gt;" in d["html"]
    assert "<strong>tight</strong>" in d["html"]
    assert '<a href="https://www.federalreserve.gov/releases/h41/" target="_blank" rel="noopener noreferrer">the H.4.1</a>' in d["html"]
    assert "<ul><li>one</li><li><em>two</em></li></ul>" in d["html"]


def test_no_javascript_links():
    assert "<a" not in ec.render_markdown("[x](javascript:alert(1))")


def test_empty_and_bad_files(tmp_path):
    assert ec.build(tmp_path) == {"empty": True}
    (tmp_path / "2026-10-24.md").write_text("no front matter")
    (tmp_path / "notes.md").write_text(POST)
    assert ec.build(tmp_path) == {"empty": True}


def test_check_mode(tmp_path):
    f = tmp_path / "2026-10-23.md"
    f.write_text(POST)
    assert ec.main(["--check", str(f)]) == 0
    g = tmp_path / "2026-10-22.md"
    g.write_text(POST)
    assert ec.main(["--check", str(g)]) == 1  # date mismatch


def test_curve_data_retired():
    md = {"curve_data": {"x": 1}, "treasury_calendar": {}, "data_fetch_status": {"curve_data": "live", "treasury_calendar": "live"}}
    strip_internal_notes(md)
    assert "curve_data" not in md and md["data_fetch_status"] == {"treasury_calendar": "live"}


def test_home_has_commentary_not_curve():
    html = (Path(__file__).resolve().parents[1] / "site" / "index.html").read_text()
    assert "Market Commentary" in html and "First commentary coming soon" in html
    assert "Curve Snapshot" not in html and "curve-widget" not in html
    assert html.count("<strong>Disclaimer:</strong>") == 1


def test_no_quote_entities_and_quote_safe_links():
    out = ec.render_markdown("Amazon's \"view\" [x](https://e.com/\"onmouseover=alert(1))")
    assert "&#x27;" not in out and "&quot;" not in out
    assert "Amazon's" in out and "<a" not in out


def test_bake_embeds_last_good_and_keeps_it_on_empty(tmp_path):
    page = tmp_path / "index.html"
    page.write_text("<div>" + ec.BAKE_START + ec.BAKE_END + "</div>")
    data = {"title": "T", "date": "2026-10-29", "author": "Ric", "html": "<p>a</script>&b</p>"}
    assert ec.bake(page, data)
    out = page.read_text()
    assert out.count('id="commentary-lastgood"') == 1 and "</script>&b" not in out
    blob = out.split('id="commentary-lastgood">', 1)[1].split("</script>", 1)[0]
    assert json.loads(blob) == data
    assert ec.bake(page, data) and page.read_text().count('id="commentary-lastgood"') == 1
    assert not ec.bake(page, {"empty": True}) and json.loads(page.read_text().split('lastgood">', 1)[1].split("</script>", 1)[0]) == data
