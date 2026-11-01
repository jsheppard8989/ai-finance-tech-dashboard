"""Checks for site/healthcare.html (Healthcare Abundance research page, Oct 31, 2026 research-essay rewrite)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "healthcare.html"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def test_healthcare_one_disclaimer_mentions_paper_trades():
    s = _src()
    text = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert text.lower().count("not investment advice") == 1
    assert "including its paper trades" in text


def test_healthcare_banned_words_and_internal_text():
    s = _src()
    text = _text(s)
    assert not re.search(r"\b(b[e]ts?|thin)\b", text, re.I)
    assert not re.search(r"\bb[e]ts?\b", s, re.I)
    assert not re.search(r"\b(JG|Scout|Tony|Wendy|TODO|TBD|DRAFT)\b|placeholder|/workspace|back office|\.csv\b", s)
    assert "<!--" not in s


def test_healthcare_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_healthcare_view_basket_and_names():
    t = " ".join(_text(_src()).split()).replace("&amp;", "&")
    assert "Our view (opinion)" in t and t.lower().count("opinion") == 1
    assert "long stock basket" in t
    for p in ("$28.09", "$3.33", "$77.97", "$183.10", "$102.20", "The historical rhyme", "Upside versus downside", "What would change our mind"):
        assert p in t, p
    for n in ("Hims & Hers", "GoodRx", "Tempus AI", "Guardant Health", "Abbott"):
        assert n in t, n
    # research piece, not a trade write-up
    assert not re.search(r"call spread|\bstrikes?\b|expiry|\bdebits?\b|max loss|\bstop\b|\btargets?\b|below 90|\bgrades?\b|right if|wrong if|hit rate", t, re.I)


def test_healthcare_charts_and_nav():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>Healthcare Abundance</title>" in s and "<h1>Healthcare Abundance</h1>" in s
    for n in (1, 2, 3, 4):
        assert re.search(r'<a class="chart-full" href="charts/healthcare/0%d\.png" data-lightbox[^>]*>\s*<img src="charts/healthcare/0%d\.png"' % (n, n), s), n
        assert (SITE / "charts" / "healthcare" / ("0%d.png" % n)).is_file(), n
    assert s.count('<p class="cnote">Source:') == 4
    assert re.search(r'<p class="asof"[^>]*>As of ', s)
