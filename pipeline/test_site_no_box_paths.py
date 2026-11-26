"""Fail if a public site page or data file leaks box paths or the paper book."""
from pathlib import Path

SITE = Path(__file__).resolve().parent.parent / "site"
TEXT_SUFFIXES = {".html", ".js", ".css", ".json", ".txt", ".md", ".csv", ".svg", ".xml"}
BANNED = ("/workspace", "paper_book")


def test_site_has_no_box_paths_or_paper_book():
    hits = []
    for path in SITE.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(SITE)
        for i, line in enumerate(text.splitlines(), 1):
            for token in BANNED:
                if token in line:
                    hits.append(f"{rel}:{i}: {line.strip()}")
                    break
    assert hits == [], "box path or paper_book leaked in public site files:\n" + "\n".join(hits)
