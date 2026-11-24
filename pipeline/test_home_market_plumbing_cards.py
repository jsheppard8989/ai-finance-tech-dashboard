"""Regression checks for retired home-page market plumbing cards."""
from pathlib import Path


HOME = Path(__file__).resolve().parents[1] / "site" / "index.html"


def test_home_page_omits_curve_and_compute_forward_cards():
    source = HOME.read_text(encoding="utf-8")

    assert 'id="curve-widget"' not in source
    assert 'id="compute-forward-widget"' not in source
    assert 'id="compute-forward-chart"' not in source
