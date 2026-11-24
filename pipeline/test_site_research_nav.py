"""Regression checks for the shared Research dropdown."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_NAV = ROOT / "site" / "js" / "research-nav.js"


def test_research_menu_has_mobile_viewport_containment_css():
    source = RESEARCH_NAV.read_text(encoding="utf-8")

    assert "@media(max-width:640px)" in source
    assert ".site-nav{position:relative}" in source
    assert ".nav-research{position:static}" in source
    assert "left:8px;right:8px" in source
    assert "max-width:calc(100vw - 16px)" in source
    assert "box-sizing:border-box" in source
    assert "white-space:normal;overflow-wrap:anywhere" in source
