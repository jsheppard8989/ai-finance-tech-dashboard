#!/usr/bin/env python3
"""In-place text patches for Vladimir Keil / Lio on served site files (preserves JSON formatting)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FILES = [
    ROOT / "site" / "data" / "archive.json",
    ROOT / "site" / "data" / "podcast_summaries.json",
    ROOT / "site" / "data" / "pundits.json",
    ROOT / "site" / "data" / "data.js",
]

REPLACEMENTS = [
    ("Vlad Kyle", "Vladimir Keil"),
    ('"slug": "vlad-kyle"', '"slug": "vladimir-keil"'),
    (
        "Vlad Kyle is co-founder and CEO of Leo, which builds AI agents for enterprise procurement.",
        "Vladimir Keil is co-founder and CEO of Lio, which builds AI agents for enterprise procurement.",
    ),
    (
        "Vladimir Keil is co-founder and CEO of Leo, which builds AI agents for enterprise procurement.",
        "Vladimir Keil is co-founder and CEO of Lio, which builds AI agents for enterprise procurement.",
    ),
    ("CEO of Leo", "CEO of Lio"),
    ("Leo agents", "Lio agents"),
    ("Leo\u2019s", "Lio\u2019s"),
]


def main() -> None:
    for path in FILES:
        text = path.read_text(encoding="utf-8")
        original = text
        for old, new in REPLACEMENTS:
            text = text.replace(old, new)
        if text != original:
            path.write_text(text, encoding="utf-8")
            print(f"✓ {path.relative_to(ROOT)}")
        else:
            print(f"  (unchanged) {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
