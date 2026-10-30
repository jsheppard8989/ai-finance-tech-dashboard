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
    # Oct 29 2026: template CONTENT slot markers (and all HTML comments) are stripped from the
    # published page after the fill, so view-source carries no template notes.
    assert "<!--" not in s and "CONTENT:" not in s
    assert "<title>Micron and the Memory Cycle" in s and "Micron and the Memory Cycle</h1>" in s
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


def test_mu_page_chart3():
    """Oct 30 2026 (v2): Chart 3, price path vs modeled bottom, sits after Chart 2 with its own image,
    caption naming the revenue-peak anchor (FQ4 FY26, provisional), alt text and source note."""
    s = _src()
    for n in (1, 2, 3):
        assert 'id="chart-%d"' % n in s, n
        assert (SITE / "charts" / "mu" / ("0%d.png" % n)).is_file(), n
    assert s.index('id="chart-2"') < s.index('id="chart-3"') < s.index('data-slot="body"')
    fig = re.search(r'<figure class="chart" id="chart-3">(.*?)</figure>', s, re.S).group(1)
    assert re.search(r'<a class="chart-full" href="charts/mu/03\.png" data-lightbox[^>]*>\s*<img src="charts/mu/03\.png"', fig)
    assert re.search(r'<img [^>]*alt="[^"]{40,}"', fig)
    cap = _text(fig)
    assert "Chart 3" in cap and "revenue-peak" in cap and "FQ4 FY26" in cap and "provisional" in cap
    assert "Source:" in cap
