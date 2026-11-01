"""Checks for site/qqq-filter.html (Nasdaq-100 filter research page, Oct 31, 2026)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "qqq-filter.html"
TITLE = "The Nasdaq-100 Is a Filter, Not a Stock Picker"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def test_qqq_one_disclaimer_banned_words_internal_text():
    s = _src()
    text = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert text.lower().count("not investment advice") == 1
    assert not re.search(r"\b(b[e]ts?|b[e]tting|thin)\b", text, re.I)
    assert not re.search(r"\bb[e]ts?\b", s, re.I)
    assert not re.search(r"\b(JG|Scout|Tony|Wendy|TODO|TBD|DRAFT)\b|placeholder|/workspace|approved by|back office|\.csv\b", s)
    assert "<!--" not in s


def test_qqq_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_qqq_no_trade_block_or_grading():
    t = " ".join(_text(_src()).split())
    assert not re.search(r"paper trade|(?<!fast )\bentry\b|max loss|\bstop\b|\btargets?\b|wrong if|right if|\bgrades?\b|\bgraded\b|hit rate|100 shares", t, re.I)


def test_qqq_simulation_labelled_and_sources_linked():
    s = _src()
    t = " ".join(_text(s).split())
    assert t.lower().count("illustrative simulation") >= 5
    for url in ("sciencedirect.com/science/article/abs/pii/S0304405X18301521",
                "news.wpcarey.asu.edu/20180917-do-stocks-outperform-treasury-bills",
                "indexes.nasdaq.com/docs/methodology_NDX.pdf",
                "nasdaq.com/articles/global-indexes/2025-nasdaq-100-reconstitution-and-performance-highlights"):
        assert url in s, url
    for fig in ("1,092", "10.07%", "39.29%", "0.36%", "91.6%", "58%"):
        assert fig in t, fig


def test_qqq_charts_nav_and_index_link():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>%s</title>" % TITLE in s and "<h1>%s</h1>" % TITLE in s
    for n in (1, 2, 3):
        assert re.search(r'<a class="chart-full" href="charts/qqq/0%d\.png" data-lightbox[^>]*>\s*<img src="charts/qqq/0%d\.png"' % (n, n), s), n
        assert (SITE / "charts" / "qqq" / ("0%d.png" % n)).is_file(), n
    assert "label: '%s', href: 'qqq-filter.html'" % TITLE in (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    for page in ("index.html", "healthcare.html", "dc-buildout.html", "compute-thesis.html", "mu-memory-cycle.html", "qqq-filter.html"):
        assert '<a href="qqq-filter.html">%s</a>' % TITLE in (SITE / page).read_text(encoding="utf-8"), page
