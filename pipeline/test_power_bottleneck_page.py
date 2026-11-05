"""Checks for site/power-bottleneck.html (power research + GEV paper trade, Nov 5, 2026)."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "power-bottleneck.html"
TITLE = "Who Owns the Energized Megawatt?"


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def _section(s, h2):
    return s.split("<h2>%s</h2>" % h2, 1)[1].split("<h2>", 1)[0]


def test_power_one_disclaimer_banned_words_internal_text():
    s = _src()
    text = _text(s)
    assert s.count("<strong>Disclaimer:</strong>") == 1
    assert "including its paper trades" in s
    assert text.lower().count("not investment advice") == 1
    assert not re.search(r"\b(b[e]ts?|b[e]tting|thin)\b", text, re.I)
    assert not re.search(r"\b(JG|Scout|Tony|Wendy|TODO|TBD|DRAFT)\b|placeholder|/workspace|approved by|back office|\.csv\b", s)
    assert not re.search(r"midpoint|not placed|right if|wrong if|\bgrades?\b|\bgraded\b|hit rate", text, re.I)
    assert "<!--" not in s
    assert "860/950" not in s and "$950" not in text


def test_power_style_gate_clean():
    from site_text_sanitize import style_gate_hits
    assert not style_gate_hits(_text(_src()))


def test_power_paper_trade_numbers():
    t = " ".join(_text(_section(_src(), "Paper trade")).split())
    for fig in ("$860", "$900", "$46.00", "$31.80", "$14.20", "$1,420", "$2,580", "$874.20", "$776.49", "Jan 15, 2027"):
        assert fig in t, fig
    assert "no stop or target" in t.lower() or "Held to the Jan 15" in t


def test_power_forward_lists_only_future_events():
    s = _src()
    sec = _section(s, "What would change our opinion")
    # no past dated opinion-changers; research body may cite historical facts elsewhere
    assert "2025-" not in sec
    assert "Jan 28, 2026" not in sec


def test_power_charts_nav_and_links():
    s = _src()
    assert "data-research-menu" in s and "./js/research-nav.js" in s
    assert "<title>%s</title>" % TITLE in s and "<h1>%s</h1>" % TITLE in s
    for name in ("6_deals_mw.png", "5_tln_ramp.png", "4_lbnl_queue.png", "1_pjm_price_vs_cap.png", "2_pjm_shortfall.png", "3_gev_gw.png"):
        assert 'href="charts/power/%s"' % name in s
        assert (SITE / "charts" / "power" / name).is_file(), name
    assert "label: '%s', href: 'power-bottleneck.html'" % TITLE in (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    for page in ("index.html", "healthcare.html", "dc-buildout.html", "compute-thesis.html", "mu-memory-cycle.html", "qqq-filter.html", "lrcx-paid-to-wait.html", "power-bottleneck.html"):
        assert '<a href="power-bottleneck.html">%s</a>' % TITLE in (SITE / page).read_text(encoding="utf-8"), page
