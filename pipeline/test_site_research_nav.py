"""Regression checks for the shared Research dropdown."""
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_NAV = ROOT / "site" / "js" / "research-nav.js"


def test_research_menu_has_mobile_viewport_containment_css():
    source = RESEARCH_NAV.read_text(encoding="utf-8")

    assert "@media(max-width:640px)" in source
    assert ".site-nav{position:relative}" in source
    assert ".nav-research{position:static}" in source or ".nav-research,.nav-trades{position:static}" in source
    assert "left:8px;right:8px" in source
    assert "max-width:calc(100vw - 16px)" in source
    assert "box-sizing:border-box" in source
    assert "white-space:normal;overflow-wrap:anywhere" in source



def test_research_and_trades_menus_are_split():
    source = RESEARCH_NAV.read_text(encoding="utf-8")
    # Research holds theses only.
    assert "var RESEARCH_PAGES = [" in source
    assert "href: 'power-bottleneck.html'" in source
    assert "href: 'compute-thesis.html'" in source
    assert "href: 'healthcare.html'" in source
    assert "href: 'qqq-filter.html'" in source
    assert "href: 'dc-buildout.html'" not in source
    assert "href: 'https://jsheppard8989.github.io/spacex-path/'" in source
    # Trade write-ups and the scoreboard live under Trades, not Research.
    assert "var TRADES_PAGES = [" in source
    assert "href: 'trades.html'" in source
    assert "href: 'lrcx-paid-to-wait.html'" in source
    assert "href: 'mu-memory-cycle.html'" in source
    research_block = source.split("var RESEARCH_PAGES = [", 1)[1].split("];", 1)[0]
    trades_block = source.split("var TRADES_PAGES = [", 1)[1].split("];", 1)[0]
    assert "lrcx-paid-to-wait.html" not in research_block
    assert "mu-memory-cycle.html" not in research_block
    assert "trades.html" not in research_block
    assert "power-bottleneck.html" not in trades_block
    # Mobile containment also covers the Trades dropdown.
    assert ".nav-research,.nav-trades{position:static}" in source or ".nav-trades{position:static}" in source


def test_every_page_has_both_menu_hooks_and_noscript_fallbacks():
    site = ROOT / "site"
    pages = sorted(site.glob("*.html"))
    assert pages
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert "data-research-menu" in html, page.name
        assert "data-trades-menu" in html, page.name
        assert "./js/research-nav.js" in html, page.name
        assert 'href="power-bottleneck.html">Who Owns the Energized Megawatt?</a>' in html, page.name
        assert 'href="trades.html">Live Paper-Trade Scoreboard</a>' in html, page.name
        assert 'href="lrcx-paid-to-wait.html">Lam Research: Paid to Wait (closed Nov 5)</a>' in html, page.name
        assert 'href="mu-memory-cycle.html">Micron and the Memory Cycle</a>' in html, page.name
        # DC Buildout stays live but out of the nav (Oct 23 / Nov 23 pull).
        if page.name != "dc-buildout.html":
            assert "dc-buildout.html" not in html, page.name
        research_ns = html.split("data-research-menu", 1)[1].split("</noscript>", 1)[0]
        trades_ns = html.split("data-trades-menu", 1)[1].split("</noscript>", 1)[0] if "data-trades-menu" in html else ""
        if page.name != "dc-buildout.html":
            assert "dc-buildout.html" not in research_ns, page.name
        assert "dc-buildout.html" not in trades_ns, page.name
        # Debates stays out of the first menu slot.
        nav = html.split('<nav class="site-nav"', 1)[1].split("</nav>", 1)[0]
        assert nav.index("data-research-menu") < nav.index('href="debait.html"'), page.name
