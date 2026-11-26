"""Regression checks for static social metadata and the shared site navigation."""
from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BASE_URL = "https://jsheppard8989.github.io/ai-finance-tech-dashboard/"
IMAGE_URL = BASE_URL + "img/og-default.jpg"
PAGES = {
    "index.html": (
        "Summaries and themes from the podcasts and newsletters in our feed.",
        "website",
    ),
    "archive.html": (
        "Historical insights and Overton Window terms (definitions + emerging concepts)",
        "website",
    ),
    "debait.html": (
        "Short host + two pundit voices on this week's contract (ElevenLabs).",
        "website",
    ),
    "dc-buildout.html": (
        "Who gets paid when the industry spends hundreds of billions on AI data centers, and who carries the risk if it overbuilds.",
        "article",
    ),
    "compute-thesis.html": (
        "Which AI compute builders turn the shortage into profit before supply catches up or their money runs out: a three-part scorecard on contracts, cash and chip life. Jared Sheppard, AI and Finance.",
        "article",
    ),
    "healthcare.html": (
        "As new treatments become plentiful, the money in medicine moves to whoever owns the patient's path to care: finding the right person, testing them, fitting the treatment, getting it filled and keeping them on it.",
        "article",
    ),
    "lrcx-paid-to-wait.html": (
        "Lam Research: Paid to Wait on the Memory Build-Out",
        "article",
    ),
    "mu-memory-cycle.html": (
        "Micron, the US memory-chip maker, closed at $934.27 on Oct 29, 2026 (FACT, Yahoo).",
        "article",
    ),
    "power-bottleneck.html": (
        "For the next 12 to 24 months, an AI chip is only worth as much as the energized megawatt under it.",
        "article",
    ),
    "qqq-filter.html": (
        "Why owning the sieve beats guessing the gold nugget",
        "article",
    ),
    "trades.html": (
        "Every paper trade we have closed and every one still open, with timed marks, P&L as a percent of max loss, and the fill math behind each number.",
        "website",
    ),
    "tlt-call-spread.html": (
        "TLT Jan 15, 2027 81/88 call spread ×90, opened Mon Nov 23, 2026",
        "article",
    ),
    "googl-call-spread.html": (
        "GOOGL Mar 19, 2027 300/340 call spread ×6, opened Fri Nov 20, 2026",
        "article",
    ),
}


def _content(source: str, selector: str) -> str:
    match = re.search(selector, source, re.S)
    assert match, selector
    return html.unescape(match.group(1))


def test_every_site_page_has_static_social_metadata_and_ordered_nav():
    assert {p.name for p in SITE.glob("*.html")} == set(PAGES)
    for filename, (description, og_type) in PAGES.items():
        source = (SITE / filename).read_text(encoding="utf-8")
        title = _content(source, r"<title>(.*?)</title>")
        assert _content(source, r'<meta name="description" content="([^"]*)">') == description
        assert _content(source, r'<meta property="og:title" content="([^"]*)">') == title
        assert _content(source, r'<meta property="og:description" content="([^"]*)">') == description
        assert _content(source, r'<meta property="og:url" content="([^"]*)">') == BASE_URL + filename
        assert _content(source, r'<meta property="og:type" content="([^"]*)">') == og_type
        assert _content(source, r'<meta property="og:image" content="([^"]*)">') == IMAGE_URL
        assert _content(source, r'<meta name="twitter:card" content="([^"]*)">') == "summary_large_image"
        assert _content(source, r'<meta name="twitter:site" content="([^"]*)">') == "@MrsDogood1722"
        assert _content(source, r'<meta name="twitter:title" content="([^"]*)">') == title
        assert _content(source, r'<meta name="twitter:description" content="([^"]*)">') == description
        assert _content(source, r'<meta name="twitter:image" content="([^"]*)">') == IMAGE_URL

        nav = _content(source, r'<nav class="site-nav"[^>]*>(.*?)</nav>')
        links = re.findall(r'<a href="([^"]+)"(?: id="([^"]+)")?>(.*?)</a>', nav)
        visible = [(href, re.sub(r"<.*?>", "", label)) for href, _, label in links if "noscript" not in label]
        # Ignore links nested in the research noscript fallback.
        top_level = [
            (href, label)
            for href, label in visible
            if href in {"index.html", "archive.html", "debait.html", "https://x.com/MrsDogood1722"}
        ]
        expected = [
            *(([("index.html", "Home")]) if filename != "index.html" else []),
            ("archive.html", "Archive"),
            ("debait.html", "Long & Short"),
            ("https://x.com/MrsDogood1722", "Follow @MrsDogood1722"),
        ]
        assert top_level == expected
        assert nav.index("data-research-menu") < nav.index("data-trades-menu")
        assert nav.index("data-trades-menu") < nav.index('href="archive.html"')
        assert nav.index("data-research-menu") < nav.index('href="debait.html"')
        if filename == "index.html":
            assert 'href="debait.html" id="home-debate-listen"' in nav


def test_research_shell_and_generator_refresh_social_text(tmp_path):
    shell = ROOT / "docs" / "research" / "mu" / "page_shell.html"
    source = shell.read_text(encoding="utf-8")
    for marker in (
        'meta name="description"',
        'meta property="og:title"',
        'meta name="twitter:title"',
        "Follow @MrsDogood1722",
    ):
        assert marker in source

    page = tmp_path / "new-research.html"
    page.write_text(source, encoding="utf-8")
    draft = tmp_path / "draft.md"
    draft.write_text(
        "# Old draft title\n\n## Summary\nThe existing summary sentence. A second sentence.\n\n## Body\nBody copy.\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "md_to_research_page.py"),
            str(draft),
            "--title",
            "Fresh title",
            "--asof",
            "Nov 24, 2026",
            "--page",
            str(page),
            "--in-place",
        ],
        check=True,
        cwd=ROOT,
    )
    generated = page.read_text(encoding="utf-8")
    assert '<meta property="og:title" content="Fresh title">' in generated
    assert '<meta name="twitter:title" content="Fresh title">' in generated
    for name in ("description", "twitter:description"):
        assert f'<meta name="{name}" content="The existing summary sentence. A second sentence.">' in generated
    assert '<meta property="og:description" content="The existing summary sentence. A second sentence.">' in generated

    draft.write_text("# Old draft title\n\n## Body\nBody copy only.\n", encoding="utf-8")
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "md_to_research_page.py"),
            str(draft),
            "--title",
            "Title-only fallback",
            "--asof",
            "Nov 24, 2026",
            "--page",
            str(page),
            "--in-place",
        ],
        check=True,
        cwd=ROOT,
    )
    generated = page.read_text(encoding="utf-8")
    for attribute in ("description", "twitter:description"):
        assert f'<meta name="{attribute}" content="Title-only fallback">' in generated
    assert '<meta property="og:description" content="Title-only fallback">' in generated
