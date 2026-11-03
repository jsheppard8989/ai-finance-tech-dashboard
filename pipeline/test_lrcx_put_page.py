"""Checks for site/lrcx-put.html (Lam Research short-put research page, Nov 2, 2026)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "lrcx-put.html"
TITLE = "Lam Research: Paid to Wait on the Memory Toolmaker"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return " ".join(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S).split())


def test_lrcx_one_disclaimer_banned_words_internal_text():
    s = _src()
    t = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert t.lower().count("not investment advice") == 1
    assert "paper trade" in s.split("<strong>Disclaimer:</strong>")[1].split("</p>")[0]
    assert not re.search(r"\b(b[e]ts?|b[e]tting|thin|grades?|graded)\b|not placed", t, re.I)
    assert not re.search(r"\b(JG|Scout|Tony|Wendy|TODO|TBD|DRAFT)\b|/workspace|approved by|back office|\.csv\b", s)
    assert "<!--" not in s


def test_lrcx_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_lrcx_trade_terms():
    t = _text(_src())
    for fig in ("Sell 1 LRCX Dec 4, 2026 $210 put", "$5.5667", "bid $5.00, ask $6.70", "a third of the spread in from the bid",
                "11:11 AM CT, Nov 2, 2026", "$556.67", "$204.43", "$21,000", "$20,443.33", "buy back at $1.00",
                "closes below $200", "About Jan 27, 2027", "Lam has not announced the date", "46%"):
        assert fig in t, fig


def test_lrcx_chart_nav_and_index_link():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>%s</title>" % TITLE in s and "<h1>%s</h1>" % TITLE in s
    assert '<a class="chart-full" href="charts/lrcx/01.png" data-lightbox' in s
    assert (SITE / "charts" / "lrcx" / "01.png").is_file()
    assert "href: 'lrcx-put.html'" in (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    for page in ("index.html", "healthcare.html", "dc-buildout.html", "compute-thesis.html", "mu-memory-cycle.html", "qqq-filter.html", "lrcx-put.html"):
        assert '<a href="lrcx-put.html">%s</a>' % TITLE in (SITE / page).read_text(encoding="utf-8"), page
