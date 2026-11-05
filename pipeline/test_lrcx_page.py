"""Checks for site/lrcx-paid-to-wait.html (Lam Research research page, Nov 2, 2026)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "lrcx-paid-to-wait.html"
TITLE = "Lam Research: Paid to Wait on the Memory Build-Out"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def _section(s, h2):
    return s.split("<h2>%s</h2>" % h2, 1)[1].split("<h2>", 1)[0]


def test_lrcx_one_disclaimer_banned_words_internal_text():
    s = _src()
    text = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert "including its paper trades" in s
    assert text.lower().count("not investment advice") == 1
    assert not re.search(r"\b(b[e]ts?|b[e]tting|thin)\b", text, re.I)
    assert not re.search(r"\b(JG|Scout|Tony|Wendy|TODO|TBD|DRAFT)\b|placeholder|/workspace|approved by|back office|\.csv\b", s)
    assert not re.search(r"midpoint|not placed|right if|wrong if|\bgrades?\b|\bgraded\b|hit rate", text, re.I)
    assert "<!--" not in s


def test_lrcx_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_lrcx_paper_trade_numbers():
    t = " ".join(_text(_section(_src(), "Paper trade")).split())
    for fig in ("$210 put", "$556.67", "5.5667", "$204.43", "$21,000", "$1.00", "below $200", "Dec 4, 2026", "$20,443.33"):
        assert fig in t, fig
    assert "2.65%" in _text(_src()) and "about 46% below" in _text(_src())


def test_lrcx_forward_lists_only_future_events():
    s = _src()
    for h2 in ("Dates ahead", "What would change our opinion"):
        sec = _section(s, h2)
        assert "2025-11-06" not in sec and "2026-01-07" not in sec, h2
        assert "Jan 28, 2026" not in sec and "Dec 3, 2025" not in sec, h2
    src = _section(s, "Sources")
    assert "2025-11-06-Lam-Research-Corporation-Declares-Quarterly-Dividend" in src
    assert "2026-01-07-Lam-Research-Corporation-Announces-December-Quarter-Financial-Conference-Call" in src


def test_lrcx_chart_nav_and_links():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>%s</title>" % TITLE in s and "<h1>%s</h1>" % TITLE in s
    assert re.search(r'<a class="chart-full" href="charts/lrcx/01\.png" data-lightbox[^>]*>\s*<img src="charts/lrcx/01\.png"', s)
    assert (SITE / "charts" / "lrcx" / "01.png").is_file()
    assert "label: '%s', href: 'lrcx-paid-to-wait.html'" % TITLE in (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    for page in ("index.html", "healthcare.html", "dc-buildout.html", "compute-thesis.html", "mu-memory-cycle.html", "qqq-filter.html", "lrcx-paid-to-wait.html", "power-bottleneck.html"):
        assert '<a href="lrcx-paid-to-wait.html">%s</a>' % TITLE in (SITE / page).read_text(encoding="utf-8"), page
