"""Checks for site/googl-call-spread.html (Scout's GOOGL note, verbatim except public line swaps)."""
import re
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
PAGE = SITE / "googl-call-spread.html"
NOTE = Path("/workspace/cos/trade_notes/GOOGL_2026-11-20.md")
TITLE = "GOOGL Mar 19, 2027 300/340 call spread ×6, opened Fri Nov 20, 2026"
NAV_LABEL = "GOOGL Mar 19, 2027 300/340 call spread ×6"
PUBLIC_OWNER = "Owner: Scout · Id: SCOUT-1117-GOOGL · Paper only · Booked Nov 20, 2026, 9:17 AM CT"
PUBLIC_SOURCES = "Sources: entry quotes taken Nov 20, 2026, 9:15 AM CT (Robinhood, read-only); fills per the scoreboard fill rule."


def _src():
    return PAGE.read_text(encoding="utf-8")


def _text(s):
    return re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", s, flags=re.S)


def test_googl_page_copies_the_note_verbatim_except_public_lines():
    src = _src()
    note = NOTE.read_text(encoding="utf-8").strip()
    lines = [ln.strip() for ln in note.splitlines() if ln.strip()]
    assert lines[0] == f"# {TITLE}"
    page_text = re.sub(r"\s+", " ", _text(src))
    page_text = re.sub(r"\s+([,.;:])", r"\1", page_text)
    for line in lines:
        expected = line[2:].strip() if line.startswith("# ") else line
        expected = expected.replace("**", "")
        if expected.startswith("Owner:"):
            expected = PUBLIC_OWNER
        elif expected.startswith("Sources:"):
            expected = PUBLIC_SOURCES
        assert expected in page_text, expected
    assert f"<title>{TITLE}</title>" in src
    assert f"<h1>{TITLE}</h1>" in src
    assert PUBLIC_OWNER in src and PUBLIC_SOURCES in src
    assert "/workspace" not in src and "paper_book" not in src


def test_googl_page_nav_and_writeup_link():
    src = _src()
    assert "data-research-menu" in src and "./js/research-nav.js" in src
    nav_js = (SITE / "js" / "research-nav.js").read_text(encoding="utf-8")
    assert f"label: '{NAV_LABEL}', href: 'googl-call-spread.html'" in nav_js
    assert f'<a href="googl-call-spread.html">{NAV_LABEL}</a>' in src
    for page in (
        "index.html",
        "healthcare.html",
        "dc-buildout.html",
        "compute-thesis.html",
        "mu-memory-cycle.html",
        "qqq-filter.html",
        "lrcx-paid-to-wait.html",
        "power-bottleneck.html",
        "trades.html",
        "tlt-call-spread.html",
        "googl-call-spread.html",
    ):
        html = (SITE / page).read_text(encoding="utf-8")
        assert f'<a href="googl-call-spread.html">{NAV_LABEL}</a>' in html, page
