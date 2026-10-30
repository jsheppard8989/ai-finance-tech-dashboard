"""Checks for site/healthcare.html (Healthcare Abundance research page, Oct 30, 2026 update)."""
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
    assert "<strong>Paper trade.</strong>" in s


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


def test_healthcare_view_trade_and_names():
    t = " ".join(_text(_src()).split())
    assert "keeping the Sep 18 basket" in t
    for p in ("$28.09", "$3.33", "$77.97", "$183.10", "$102.20", "2.891 million", "below 90"):
        assert p in t, p
    for n in ("Hims & Hers", "GoodRx", "Tempus AI", "Guardant Health", "Abbott"):
        assert n in t.replace("&amp;", "&"), n
    assert "Grade date: none" in t and "Strike and expiry: none" in t


def test_healthcare_charts_and_nav():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>Healthcare Abundance</title>" in s and "<h1>Healthcare Abundance</h1>" in s
    for n in (1, 2, 3):
        assert re.search(r'<a class="chart-full" href="charts/healthcare/0%d\.png" data-lightbox[^>]*>\s*<img src="charts/healthcare/0%d\.png"' % (n, n), s), n
        assert (SITE / "charts" / "healthcare" / ("0%d.png" % n)).is_file(), n
    assert s.count('<p class="cnote">Source:') == 3
    assert re.search(r'<p class="asof"[^>]*>As of ', s)
