"""Regression checks for retired home-page market plumbing cards and liquidity ticker."""
from pathlib import Path


HOME = Path(__file__).resolve().parents[1] / "site" / "index.html"


def test_home_page_omits_retired_cards_and_has_liquidity_ticker():
    source = HOME.read_text(encoding="utf-8")

    assert 'id="curve-widget"' not in source
    assert 'id="compute-forward-widget"' not in source
    assert 'id="compute-forward-chart"' not in source
    assert 'id="treasury-widget"' not in source
    assert 'id="treasury-expand"' not in source
    assert 'id="liquidity-ticker"' in source
