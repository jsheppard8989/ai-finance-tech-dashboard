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


def test_kit_signup_is_only_on_the_home_page():
    """Kit form stays on index.html; do not add it to other pages."""
    for page in (ROOT / "site").glob("*.html"):
        if page.name == "index.html":
            continue
        source = page.read_text(encoding="utf-8")
        assert "scarcity-abundance.kit.com" not in source, page.name
        assert 'id="signup"' not in source or page.name == "index.html", page.name
