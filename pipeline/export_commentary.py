#!/usr/bin/env python3
"""Market Commentary export (Oct 22 2026).

Reads Ric's posts from commentary/YYYY-MM-DD.md (repo root), picks the newest by
front-matter date, and writes site/data/commentary/latest.json:
  {"title", "date", "author", "html"}  or  {"empty": true} when there is no post.

The body is rendered as plain HTML from a small Markdown subset (paragraphs, #/##/###
headings, "- " lists, **bold**, *italic*, [text](https://...) links). ALL text from the
file is HTML-escaped first, so raw HTML in a post is shown as text, never rendered.
Stdlib only: also runs in the Pages deploy workflow.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "commentary"
OUT_PATH = ROOT / "site" / "data" / "commentary" / "latest.json"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_BULLET_RE = re.compile(r"^\s*[-*] ")
_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")


def parse_post(text: str) -> dict:
    """Split '---' front matter (title/date/author) from the Markdown body."""
    text = text.lstrip("\ufeff").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise ValueError("missing front matter (file must start with ---)")
    end = text.find("\n---", 4)
    if end < 0:
        raise ValueError("unterminated front matter")
    meta = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip().lower()] = v.strip().strip('"').strip("'")
    body = text[end + 4:].split("\n", 1)[1] if "\n" in text[end + 4:] else ""
    for k in ("title", "date", "author"):
        if not meta.get(k):
            raise ValueError(f"front matter missing {k}")
    if not _DATE_RE.match(meta["date"]):
        raise ValueError("date must be YYYY-MM-DD")
    return {"title": meta["title"], "date": meta["date"], "author": meta["author"], "body": body.strip()}


def _inline(escaped: str) -> str:
    s = re.sub(r"\[([^\]]+)\]\((https?://[^\s)\"'<>]+)\)",
               lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>', escaped)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<em>\1</em>", s)
    return s


def render_markdown(body: str) -> str:
    """Markdown subset -> HTML. Input is escaped before any tag is added."""
    out = []
    for block in re.split(r"\n\s*\n", body.strip()):
        lines = [l.rstrip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        esc = [html.escape(l, quote=False) for l in lines]
        if all(re.match(r"^\s*[-*] ", l) for l in lines):
            items = "".join("<li>" + _inline(_BULLET_RE.sub("", e)) + "</li>" for e in esc)
            out.append(f"<ul>{items}</ul>")
            continue
        m = re.match(r"^(#{1,3}) (.+)$", lines[0])
        if m and len(lines) == 1:
            lvl = len(m.group(1)) + 3  # h4..h6 inside the card
            out.append(f"<h{lvl}>{_inline(html.escape(m.group(2), quote=False))}</h{lvl}>")
            continue
        out.append("<p>" + "<br>".join(_inline(e) for e in esc) + "</p>")
    return "\n".join(out)


def latest_post(src_dir: Path = SRC_DIR):
    posts = []
    for p in sorted(src_dir.glob("*.md")) if src_dir.is_dir() else []:
        if not _FILE_RE.match(p.name):
            continue
        try:
            posts.append(parse_post(p.read_text(encoding="utf-8")))
        except ValueError as e:
            print(f"  ⚠ commentary: skipping {p.name}: {e}", file=sys.stderr)
    if not posts:
        return None
    return max(posts, key=lambda x: x["date"])


def build(src_dir: Path = SRC_DIR) -> dict:
    post = latest_post(src_dir)
    if not post:
        return {"empty": True}
    return {"title": html.escape(post["title"], quote=False), "date": post["date"],
            "author": html.escape(post["author"], quote=False), "html": render_markdown(post["body"])}


BAKE_START = "<!--commentary-lastgood:start-->"
BAKE_END = "<!--commentary-lastgood:end-->"


def bake(page: Path, data: dict) -> bool:
    """Embed the last good post in the page between the BAKE markers, so the card can still
    show it when latest.json fails to load. An empty export never overwrites a baked copy."""
    if data.get("empty") or not data.get("html"):
        return False
    text = page.read_text(encoding="utf-8")
    a, b = text.find(BAKE_START), text.find(BAKE_END)
    if a < 0 or b < a:
        raise ValueError(f"{page}: commentary bake markers not found")
    blob = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    tag = f'<script type="application/json" id="commentary-lastgood">{blob}</script>'
    page.write_text(text[:a + len(BAKE_START)] + tag + text[b:], encoding="utf-8")
    return True


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=Path, default=SRC_DIR)
    ap.add_argument("--out", type=Path, default=OUT_PATH)
    ap.add_argument("--check", type=Path, help="validate one post file and exit")
    ap.add_argument("--bake", type=Path, help="also embed the post in this HTML page as the last-good fallback")
    a = ap.parse_args(argv)
    if a.check:
        if not _FILE_RE.match(a.check.name):
            print("file name must be YYYY-MM-DD.md"); return 1
        try:
            p = parse_post(a.check.read_text(encoding="utf-8"))
        except ValueError as e:
            print(f"invalid: {e}"); return 1
        if p["date"] != a.check.stem:
            print("front-matter date must match the file name"); return 1
        print(f"ok: {p['date']} · {p['title']} · {p['author']}"); return 0
    data = build(a.src)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if a.bake and bake(a.bake, data):
        print(f"  ✓ commentary: baked last-good copy into {a.bake}")
    print(f"  ✓ commentary: {'no post yet' if data.get('empty') else data['date'] + ' ' + data['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
