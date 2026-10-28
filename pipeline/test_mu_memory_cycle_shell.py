"""Shell checks for site/mu-memory-cycle.html (Micron memory-cycle research page).

These hold for both the empty shell and the page once md_to_research_page.py fills it.
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "mu-memory-cycle.html"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def test_mu_page_one_disclaimer_and_banned_words():
    s = _src()
    text = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert text.lower().count("not investment advice") == 1
    assert not re.search(r"\b(b[e]ts?|thin)\b", text, re.I)
    assert not re.search(r"\bb[e]ts?\b", s, re.I)  # not even in comments or attributes


def test_mu_page_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_mu_page_nav_and_slots():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    for slot in ("title", "asof", "summary", "chart1", "chart2", "body"):
        assert "<!-- CONTENT: %s -->" % slot in s, slot
        assert "<!-- /CONTENT: %s -->" % slot in s, slot
    for n in (1, 2):
        assert re.search(
            r'<a class="chart-full" href="charts/mu/0%d\.png" data-lightbox[^>]*>\s*<img src="charts/mu/0%d\.png"' % (n, n), s
        ), n
    assert "ov.id = 'chart-lightbox'" in s and "querySelectorAll('a[data-lightbox]')" in s
    assert re.search(r'<p class="asof"[^>]*>As of ', s)


def test_mu_page_link_matches_title():
    s = _src()
    title = re.search(r"<title>(.*?)</title>", s).group(1)
    assert re.search(r"<h1>(.*?)</h1>", s).group(1) == title
    assert "label: '%s', href: 'mu-memory-cycle.html'" % title in (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    for page in ("index.html", "healthcare.html", "dc-buildout.html", "compute-thesis.html", "mu-memory-cycle.html"):
        assert '<a href="mu-memory-cycle.html">%s</a>' % title in (SITE / page).read_text(encoding="utf-8"), page
