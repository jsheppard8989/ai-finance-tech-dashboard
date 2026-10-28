#!/usr/bin/env python3
"""Fill a research page shell (e.g. site/mu-memory-cycle.html) from a markdown draft.

The shell marks each slot with paired comments:
    <!-- CONTENT: title -->   ... <!-- /CONTENT: title -->
    <!-- CONTENT: asof -->    ... <!-- /CONTENT: asof -->
    <!-- CONTENT: summary --> ... <!-- /CONTENT: summary -->
    <!-- CONTENT: chart1 -->  ... <!-- /CONTENT: chart1 -->   (caption / alt / note only)
    <!-- CONTENT: chart2 -->  ... <!-- /CONTENT: chart2 -->
    <!-- CONTENT: body -->    ... <!-- /CONTENT: body -->
Markers are kept, so the script can be re-run on its own output.

The summary comes from the first markdown section whose heading matches
--summary-heading (default: "summary" or "short version"), or from --summary-md.
That section is removed from the body. The H1 is dropped (the page title comes
from --title). Everything else becomes the body.

Handles: GFM-style pipe tables (wrapped in <div class="tbl"> for scrolling),
2-space nested lists, lists/tables with no blank line before them, footnotes,
inline code, and FACT / REPORTED / INFERENCE / ESTIMATE / OPINION / UNVERIFIED
labels (rendered as small colored badges). Links to repo-relative files
(e.g. mu_data/x.csv) are not on the site, so by default they become plain text.

It never touches git and never publishes. Default output is a preview file;
pass --in-place to rewrite the page.

Examples:
  python3 scripts/md_to_research_page.py draft.md --title "Micron and the Memory Cycle" \
      --asof "Oct 29, 2026, 12:30 PM CT" --out /tmp/mu_preview/mu-memory-cycle.html
  python3 scripts/md_to_research_page.py draft.md --title "..." --asof "..." --in-place \
      --chart1-caption "..." --chart1-alt "..." --chart1-note "Source: ..." --strict
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from pathlib import Path

try:
    import markdown  # python-markdown 3.x
except ImportError:  # pragma: no cover
    sys.exit("python-markdown is required: pip install markdown")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))
try:
    from site_text_sanitize import style_gate_hits  # repo's banned-wording style gate
except Exception:  # pragma: no cover
    style_gate_hits = None
try:
    from process_checks import check_fact_gate  # publish_guard BLOCKS on this
except Exception:  # pragma: no cover
    check_fact_gate = None

LABELS = ("FACT", "REPORTED", "INFERENCE", "ESTIMATE", "OPINION", "UNVERIFIED")
LABEL_RE = re.compile(r"(?:<strong>)?\b(%s)\b(?:</strong>)?(:)?" % "|".join(LABELS))
LIST_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")
REL_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\((?!https?:|mailto:|#)([^)\s]+)\)")
# Words that usually mean an editorial note leaked into the public text.
DEFAULT_LEAKS = (r"\bDRAFT\b", r"\bTODO\b", r"\bTBD\b", r"\bplaceholders?\b", r"NOT FOR PUBLICATION",
                 r"NOTE TO EDITORS", r"\bJG\b", r"\bScout\b", r"\bG's\b", r"\bfor G\b", r"fact-check",
                 r"\.csv\b", r"\.bak\b")


def slot_re(name: str) -> re.Pattern:
    return re.compile(r"(<!-- CONTENT: %s\b[^>]*-->)(.*?)(<!-- /CONTENT: %s -->)" % (name, name), re.S)


def fill_slot(page: str, name: str, inner: str) -> str:
    rx = slot_re(name)
    if not rx.search(page):
        raise SystemExit(f"slot '{name}' not found in page (missing <!-- CONTENT: {name} --> ... <!-- /CONTENT: {name} -->)")
    return rx.sub(lambda m: m.group(1) + "\n" + inner + "\n      " + m.group(3), page, count=1)


# ------------------------------------------------------------------ markdown prep
def split_sections(md: str, heading_rx: str | None):
    """Return (title_h1, summary_md or None, summary_heading, body_md)."""
    lines = md.splitlines()
    h1 = None
    if lines and lines[0].startswith("# "):
        h1 = lines.pop(0)[2:].strip()
    if not heading_rx:
        return h1, None, None, "\n".join(lines)
    rx = re.compile(heading_rx, re.I)
    start = level = None
    for i, ln in enumerate(lines):
        m = re.match(r"^(#{2,6})\s+(.*)", ln)
        if m and rx.search(m.group(2)):
            start, level, head = i, len(m.group(1)), m.group(2).strip()
            break
    if start is None:
        return h1, None, None, "\n".join(lines)
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = re.match(r"^(#{1,6})\s", lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    summary = "\n".join(lines[start + 1:end]).strip()
    body = "\n".join(lines[:start] + lines[end:])
    return h1, summary, head, body


def drop_sections(md: str, patterns: list[str]) -> tuple[str, list[str]]:
    if not patterns:
        return md, []
    rxs = [re.compile(p, re.I) for p in patterns]
    out, dropped, skip_level = [], [], None
    for ln in md.splitlines():
        m = re.match(r"^(#{1,6})\s+(.*)", ln)
        if m:
            lvl = len(m.group(1))
            if skip_level is not None and lvl <= skip_level:
                skip_level = None
            if skip_level is None and any(r.search(m.group(2)) for r in rxs):
                skip_level = lvl
                dropped.append(m.group(2).strip())
                continue
        if skip_level is None:
            out.append(ln)
    return "\n".join(out), dropped


def normalize(md: str, keep_rel_links: bool, notes: list[str]) -> str:
    # Repo-relative links (CSV files etc.) are not published with the site.
    rel = REL_LINK_RE.findall(md)
    if rel and not keep_rel_links:
        notes.append(f"{len(rel)} repo-relative link(s) turned into plain text: "
                     + ", ".join(sorted({t for _, t in rel}))[:300])
        md = REL_LINK_RE.sub(r"\1", md)
    out, prev = [], ""
    in_fence = False
    for ln in md.splitlines():
        if ln.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence:
            m = LIST_RE.match(ln)
            if m:
                ind = len(m.group(1).expandtabs(4))
                if ind and ind % 4:  # 2-space nesting -> python-markdown's 4
                    ln = " " * ((ind + 1) // 2 * 4) + ln.lstrip()
                if prev.strip() and not LIST_RE.match(prev) and not prev.startswith((" ", "\t")):
                    out.append("")  # list right after a paragraph needs a blank line
            elif ln.startswith("|") and prev.strip() and not prev.startswith("|"):
                out.append("")  # same for tables
        out.append(ln)
        prev = ln
    return "\n".join(out)


def render(md: str) -> str:
    h = markdown.markdown(md, extensions=["tables", "fenced_code", "footnotes", "sane_lists"],
                          output_format="html")
    h = re.sub(r"<table>", '<div class="tbl"><table>', h)
    h = h.replace("</table>", "</table></div>")
    return badge(h)


def badge(h: str) -> str:
    """FACT / REPORTED / ... -> <span class="lbl lbl-fact">FACT</span>, in text only (not tags, code)."""
    parts = re.split(r"(<code>.*?</code>|<[^>]+>)", h, flags=re.S)
    out = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p.startswith("<strong>") and i + 2 < len(parts) and parts[i + 2] == "</strong>" \
                and parts[i + 1] in LABELS:
            out.append(f'<span class="lbl lbl-{parts[i + 1].lower()}">{parts[i + 1]}</span>')
            i += 3
            if i < len(parts) and parts[i].startswith(":"):
                parts[i] = parts[i][1:]
            continue
        if p.startswith("<"):
            out.append(p)
        else:
            out.append(re.sub(r"\b(%s)\b:?" % "|".join(LABELS),
                              lambda m: f'<span class="lbl lbl-{m.group(1).lower()}">{m.group(1)}</span>', p))
        i += 1
    return "".join(out)


def text_of(h: str) -> str:
    return html.unescape(re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", h, flags=re.S))


def indent(h: str, n: int = 8) -> str:
    pad = " " * n
    return "\n".join(pad + ln if ln.strip() else ln for ln in h.splitlines())


# ------------------------------------------------------------------ main
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("markdown", type=Path)
    ap.add_argument("--title", required=True)
    ap.add_argument("--asof", required=True, help='e.g. "Oct 29, 2026, 12:30 PM CT" (the "As of" prefix is added)')
    ap.add_argument("--page", type=Path, default=REPO / "site" / "mu-memory-cycle.html")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--out", type=Path, help="write here (default: /tmp/<page name>.preview.html)")
    g.add_argument("--in-place", action="store_true", help="rewrite --page itself")
    ap.add_argument("--summary-heading", default=r"summary|short version",
                    help="regex for the markdown heading whose section becomes the summary box ('' to disable)")
    ap.add_argument("--summary-md", type=Path, help="separate markdown file for the summary box")
    ap.add_argument("--summary-title", default="The short version")
    ap.add_argument("--drop-heading", action="append", default=[],
                    help="regex; drop any section whose heading matches (repeatable), e.g. 'Charts: placeholders'")
    ap.add_argument("--keep-relative-links", action="store_true")
    for n in (1, 2):
        ap.add_argument(f"--chart{n}-caption")
        ap.add_argument(f"--chart{n}-sub", help="smaller second caption line")
        ap.add_argument(f"--chart{n}-alt")
        ap.add_argument(f"--chart{n}-note", help="source note under the chart")
    ap.add_argument("--sync-nav", action="store_true",
                    help="if the title changed, update research-nav.js and every page's noscript link text")
    ap.add_argument("--strict", action="store_true", help="exit 1 on any warning")
    a = ap.parse_args(argv)

    page = a.page.read_text(encoding="utf-8")
    md = a.markdown.read_text(encoding="utf-8")
    warns: list[str] = []
    notes: list[str] = []

    md, dropped = drop_sections(md, a.drop_heading)
    if dropped:
        notes.append("dropped sections: " + "; ".join(dropped))
    h1, summary_md, summary_head, body_md = split_sections(md, a.summary_heading or None)
    if a.summary_md:
        summary_md = a.summary_md.read_text(encoding="utf-8")
        summary_head = str(a.summary_md)
    if h1:
        notes.append(f"markdown H1 dropped (page title is --title): {h1!r}")
    if summary_md is None:
        warns.append("no summary section found; summary box left as placeholder")
    else:
        notes.append(f"summary box from: {summary_head!r}")

    t = html.escape(a.title, quote=False)
    page = re.sub(r"<title>.*?</title>", f"<title>{t}</title>", page, count=1, flags=re.S)
    page = fill_slot(page, "title", f"    <h1>{t}</h1>")
    page = fill_slot(page, "asof", f'    <p class="asof" data-slot="asof">As of {html.escape(a.asof, quote=False)}</p>')
    if summary_md is not None:
        sh = render(normalize(summary_md, a.keep_relative_links, notes))
        page = fill_slot(page, "summary",
                         '      <section class="summary-box" aria-labelledby="summary-h">\n'
                         f'        <h2 id="summary-h">{html.escape(a.summary_title)}</h2>\n{indent(sh)}\n      </section>')
    body = render(normalize(body_md, a.keep_relative_links, notes))
    page = fill_slot(page, "body", f'      <section class="body" data-slot="body">\n{indent(body)}\n      </section>')

    for n in (1, 2):
        m = slot_re(f"chart{n}").search(page)
        if not m:
            warns.append(f"chart{n} slot missing")
            continue
        block = m.group(2)
        cap, sub = getattr(a, f"chart{n}_caption"), getattr(a, f"chart{n}_sub")
        alt, note = getattr(a, f"chart{n}_alt"), getattr(a, f"chart{n}_note")
        if cap:
            c = html.escape(cap) + (f'<span class="csub">{html.escape(sub)}</span>' if sub else "")
            block = re.sub(r'<span data-slot="chart%d-caption"[^>]*>.*?</span>' % n,
                           f'<span data-slot="chart{n}-caption">{c}</span>', block, flags=re.S)
        if alt:
            block = re.sub(r'(<img src="[^"]+" alt=")[^"]*(")', lambda mm: mm.group(1) + html.escape(alt) + mm.group(2), block)
        if note:
            block = re.sub(r'<span data-slot="chart%d-note"[^>]*>.*?</span>' % n,
                           f'<span data-slot="chart{n}-note">{html.escape(note)}</span>', block, flags=re.S)
        page = page[:m.start(2)] + block + page[m.end(2):]

    # ---------------- checks (warn; --strict makes them fatal)
    text = text_of(page)
    if "placeholder" in page and 'class="placeholder"' in page:
        warns.append("%d placeholder(s) still unfilled" % page.count('class="placeholder"'))
    n_disc = page.count("<strong>Disclaimer:</strong>")
    n_nia = text.lower().count("not investment advice")
    if n_disc != 1 or n_nia != 1:
        warns.append(f"disclaimer count wrong: {n_disc} 'Disclaimer:' / {n_nia} 'not investment advice' (need exactly 1)")
    if style_gate_hits:
        hits = style_gate_hits(text)
        if hits:
            warns.append(f"style gate (banned wording): {hits[:3]}")
    if re.search(r"\bthin\b", text, re.I):
        warns.append("banned word 'thin' present (research-page tests reject it)")
    body_text = text_of(body) + " " + (text_of(sh) if summary_md is not None else "")
    for pat in DEFAULT_LEAKS:
        hits = re.findall(r".{0,40}%s.{0,40}" % pat, body_text)
        if hits:
            warns.append(f"possible editorial leak /{pat}/ x{len(hits)}: {hits[0].strip()!r}")
    if check_fact_gate:
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "page.html").write_text(page, encoding="utf-8")
            for b in check_fact_gate(Path(td)):
                warns.append(f"FACT gate (publish_guard will BLOCK): FACT with no URL: {b['text'][:110]!r}")
    if "[^" in md and "footnote" not in body:
        warns.append("footnote markers found but not rendered")
    raw_html = re.findall(r"<(?!https?:)[a-zA-Z][^>]*>", md)
    if raw_html:
        notes.append(f"raw HTML passed through from markdown: {raw_html[:3]}")
    if "<!-- CONTENT:" in body:
        warns.append("markdown contains a CONTENT marker")

    # nav title sync
    href = a.page.name
    js_p = a.page.parent / "js" / "research-nav.js"
    js = js_p.read_text(encoding="utf-8") if js_p.exists() else ""
    want = "label: '%s', href: '%s'" % (a.title.replace("'", "\\'"), href)
    if js and want not in js:
        if a.sync_nav:
            js = re.sub(r"label: '[^']*', href: '%s'" % re.escape(href), want, js)
            js_p.write_text(js, encoding="utf-8")
            for p in a.page.parent.glob("*.html"):
                s = p.read_text(encoding="utf-8")
                s2 = re.sub(r'<a href="%s">[^<]*</a>' % re.escape(href), f'<a href="{href}">{t}</a>', s)
                if s2 != s and p.resolve() != a.page.resolve():
                    p.write_text(s2, encoding="utf-8")
            page = re.sub(r'<a href="%s">[^<]*</a>' % re.escape(href), f'<a href="{href}">{t}</a>', page)
            notes.append("nav labels synced to new title")
        else:
            warns.append("title differs from research-nav.js label; re-run with --sync-nav (updates nav + noscript lists)")

    n_badges = body.count('class="lbl ')
    out = a.page if a.in_place else (a.out or Path("/tmp") / (a.page.stem + ".preview.html"))
    out.parent.mkdir(parents=True, exist_ok=True)
    for src in re.findall(r'<img src="([^"]+)"', page):
        if not re.match(r"https?:", src) and not (out.parent / src).is_file():
            warns.append(f"chart image not found next to {out.name}: {src}")
    out.write_text(page, encoding="utf-8")
    print(f"wrote {out} ({len(page):,} bytes; body {len(body):,} bytes, "
          f"{body.count('<table>')} table(s), {n_badges} label badge(s))")
    for n in notes:
        print("  note:", n)
    for w in warns:
        print("  WARN:", w)
    return 1 if (a.strict and warns) else 0


if __name__ == "__main__":
    sys.exit(main())
