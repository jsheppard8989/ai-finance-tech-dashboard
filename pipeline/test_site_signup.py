"""Regression checks for the home-page newsletter signup."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOME = ROOT / "site" / "index.html"


def test_home_page_contains_kit_signup():
    source = HOME.read_text(encoding="utf-8")

    assert 'id="signup"' in source
    assert (
        '<script async data-uid="7ac38e24ff" '
        'src="https://scarcity-abundance.kit.com/7ac38e24ff/index.js"></script>'
    ) in source
