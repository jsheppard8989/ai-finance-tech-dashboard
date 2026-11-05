#!/usr/bin/env python3
"""Regenerate MU research from tracked source through the existing converter.

Layout, captions and chart alt text live in docs/research/mu/page_shell.html.
No quote fetching, database access or publishing.
"""
from pathlib import Path

import md_to_research_page

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/research/mu"
PAGE = ROOT / "site/mu-memory-cycle.html"


def main():
    return md_to_research_page.main([
        str(SOURCE / "mu_page.md"), "--summary-md", str(SOURCE / "mu_summary.md"),
        "--title", "Micron and the Memory Cycle",
        "--asof", "Oct 30, 2026, before the open; entry model corrected Nov 5, 2026",
        "--page", str(SOURCE / "page_shell.html"), "--out", str(PAGE),
        "--strict", "--strip-comments",
    ])


if __name__ == "__main__":
    raise SystemExit(main())
