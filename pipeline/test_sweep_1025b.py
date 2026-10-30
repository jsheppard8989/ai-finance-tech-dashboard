"""Oct 25 2026 sweep round 2 (cos/sweep_1025/fixes_round2.md): names, dc-buildout cleanup,
and forward-curve placeholders kept off the Compute Forward chart."""
import json, re, subprocess
from pathlib import Path
import pytest
import export_data
import fetch_compute_curve as fcc

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PRE = "2684146c"  # origin/main before round 2 (#592)


def _old(path):
    r = subprocess.run(["git", "show", f"{PRE}:{path}"], cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("pre-fix snapshot not available")
    return json.loads(r.stdout)


def _fix(obj):
    out = export_data._apply_summary_overrides(obj)
    return out if out is not None else obj


def test_pundit_fixes_reapply_on_export():
    pund = _fix(_old("site/data/pundits.json"))
    text = json.dumps(pund, ensure_ascii=False)
    for bad in ("Sam Elan", "Brain professor", "Brain Professor", "Brinkett", "Stine Pella", "Pella's",
                "Caterpillar and Vernova", "Lassie, she has", "She is recognized for her innovative"):
        assert bad not in text, bad
    by_id = {p["id"]: p for p in pund}
    assert by_id[466]["last_proof_snippet"].startswith(
        "Dario Amodei, CEO of Anthropic, published a 3,800-word essay titled We Must Pace the Frontier. Monday, President Trump")
    assert "Sam Altman" not in by_id[466]["last_proof_snippet"]
    assert by_id[420]["bio"].startswith(
        "Anima Anandkumar is the Bren Professor of Computing and Mathematical Sciences at Caltech, known for")
    assert by_id[420]["pundit_profile"]["derived"]["current_role"] == \
        "Bren Professor of Computing and Mathematical Sciences at Caltech"
    assert by_id[366]["name"] == "Fr\u00e9d\u00e9ric Renken"
    assert by_id[365]["name"] == "Steijn Pelle"
    assert by_id[365]["bio"].endswith(
        "He is recognized for his innovative application of AI in healthcare administration, aiming to reduce the workload of healthcare professionals.")
    assert by_id[366]["slug"] == "frederick-brinkett"  # slugs/URLs untouched


def test_latent_space_summary_and_vernova():
    arch = json.dumps(_fix(_old("site/data/archive.json")), ensure_ascii=False)
    assert "RJHONICY" not in arch and "hosts Brandon" not in arch
    assert ("the AI Engineer Podcast, the hosts interview Anima Anandkumar, the Bren Professor of Computing "
            "and Mathematical Sciences at Caltech") in arch
    assert "Caterpillar and GE Vernova" in arch and "Caterpillar and Vernova" not in arch


def test_site_data_has_no_old_forms():
    for f in ("data.js", "pundits.json", "archive.json", "podcast_summaries.json"):
        text = (SITE / "data" / f).read_text(encoding="utf-8")
        for bad in ("Sam Elan", "Brain Professor", "rain professor", "RJHONICY", "Brinkett", "Stine Pella",
                    "Caterpillar and Vernova"):
            assert bad not in text, (f, bad)


def test_dc_buildout_cleanup():
    html = (SITE / "dc-buildout.html").read_text(encoding="utf-8")
    assert "not yet reviewed" not in html
    assert "PJM filed its revised emergency power-buying plan with federal regulators on Thu Oct 29 (docket ER27-330-000)" in html
    assert "falling to $2.27 by Jun 2027" not in html and "expected to fall that fast" not in html
    assert "Kalshi" not in html and "aicomputetracker.com" not in html
    # Round 2b fallback: Ornn link, no Ornn index number
    assert ("We'll check our view against Ornn's H100 spot index, a daily measure of what it costs to rent an "
            "NVIDIA H100 chip right now.") in html
    assert "https://data.ornn.com/markets/h100-sxm" in html and "$3.03" not in html
    assert "<p>Our view (opinion): H100 rents could fall through 2027 as newer Blackwell chips add supply." in html
    for line in html.splitlines():
        if "Ornn" in line:
            assert not re.search(r"\b(bet|bets|betting|thin)\b", line, re.I), line


def test_compute_thesis_forward_chart_removed_and_renumbered():
    html = (SITE / "compute-thesis.html").read_text(encoding="utf-8")
    for bad in ("57.1%", "$1.35", "Kalshi", "forward-curves.json", "compute_forward_curve", "market_data.json",
                "as the forwards imply", "D.ornn", "$3.03"):
        assert bad not in html, bad
    nums = sorted(set(re.findall(r'data-chart="(\d)"', html)))
    assert nums == ["1", "2", "3", "4"]
    assert re.findall(r'<span class="cnum">Chart (\d)</span>', html) == ["1", "2", "3", "4"]
    assert sorted(set(re.findall(r'id="chart-(\d)"', html))) == ["1", "2", "3", "4"]
    assert "(our math, chart 3)" in html and "$1,442M (chart 3)" in html and "chart 5" not in html.lower()
    assert "var h = host(3); if (!h) return;" in html and "draw(4, {" in html and "draw(3," not in html
    assert "<li>Spot rents (Ornn, SemiAnalysis) turn down as new capacity switches on.</li>" in html
    assert "https://data.ornn.com/markets/h100-sxm" in html


def _pt(key, price, src="bracket", lo_open=False, hi_open=False, quality="thin"):
    return {"priceUsdPerGpuHour": price, "quality": quality,
            "evidence": {"tenorKey": key, "valueSource": src, "loOpen": lo_open, "hiOpen": hi_open,
                         "identified": quality == "quality-passed"}}


def test_exporter_drops_open_bracket_placeholders():
    raw = {"asOf": "2026-10-25T12:37:40Z", "chips": [{"id": "h100", "provenance": {}, "points": [
        _pt("2026-10", 2.9), _pt("2026-11", 3.11, quality="quality-passed"), _pt("2026-12", 3.32),
        _pt("2027-01", 3.0, lo_open=True, hi_open=True),
        _pt("2027-06", 3.88, lo_open=True), _pt("2027-07", 3.91, lo_open=True), _pt("2027-08", 1.35, hi_open=True),
        _pt("2027-09", 2.5, src="quotes"),
    ]}]}
    out = fcc.parse(raw)["h100"]
    assert [p["tenor_key"] for p in out["points"]] == ["2026-10", "2026-11", "2026-12", "2027-09"]
    assert out["placeholders_dropped"] == ["2027-01", "2027-06", "2027-07", "2027-08"]
    assert all(p["price"] not in (3.88, 3.91, 1.35) for p in out["points"])
    assert out["points"][1]["identified"] is True


def test_published_curve_and_chart_js_have_no_placeholders():
    md = json.loads((SITE / "data" / "market_data.json").read_text(encoding="utf-8"))
    fc = md["compute_forward_curve"]
    h100 = {p["tenor_key"]: p["price"] for p in fc["h100"]["points"]}
    assert not any(h100.get(k) == v for k, v in (("2027-06", 3.88), ("2027-07", 3.91), ("2027-08", 1.35)))
    for chip in ("a100", "h100", "b200", "h200"):
        if chip in fc:
            assert not set(fc[chip].get("placeholders_dropped") or []) & {p["tenor_key"] for p in fc[chip]["points"]}
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert "placeholders_dropped" in html and "p.placeholder === true" in html and "ev.hiOpen === true" in html
