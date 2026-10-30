#!/usr/bin/env python3
"""Build the Trap Map from its one source of truth, site/data/trap_map.json.

Writes:
  - site/trap-map.html             (table on desktop, tap-to-expand cards on phones)
  - the homepage strip in site/index.html between <!-- TRAP_STRIP:START --> / <!-- TRAP_STRIP:END -->
  - computed fields back into trap_map.json: totals (paid, value now, S&P value) and changes
    (generated from each row's history, newest first). Nothing here is typed by hand.

Runs trap_map_check.py first and refuses to build on any failure.
Usage: python3 pipeline/build_trap_map.py [--check]   (--check: exit 1 if outputs are out of date)
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trap_map_check  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
DATA = SITE / "data" / "trap_map.json"
PAGE = SITE / "trap-map.html"
INDEX = SITE / "index.html"
CT = ZoneInfo("America/Chicago")
START, END = "<!-- TRAP_STRIP:START -->", "<!-- TRAP_STRIP:END -->"
ORDER = {"live": 0, "new": 1, "holding": 2, "graded": 3}
e = lambda s: html.escape(str(s if s is not None else ""), quote=True)


def money(n) -> str:
    return f"${n:,.2f}"


def fmt_date(s) -> str:
    d = date.fromisoformat(str(s)[:10])
    out = f"{d.strftime('%b')} {d.day}"
    return out if d.year == 2026 else f"{out}, {d.year}"


def fmt_time(s) -> str:
    t = datetime.fromisoformat(s).astimezone(CT)
    return f"{t.strftime('%b')} {t.day}, {t.strftime('%I:%M %p').lstrip('0')} CT"


def compute(d: dict) -> dict:
    rows = [r for r in d["rows"] if r.get("status") != "graded" and (r.get("trade") or {}).get("cost") is not None]
    b = d["benchmark"]
    d["totals"] = {
        "cost": round(sum(r["trade"]["cost"] for r in rows), 2),
        "value": round(sum(r["trade"]["value"] for r in rows), 2),
        "spy_value": round(sum(x["shares"] for x in b["buys"]) * b["spy_close_now"], 2),
        "computed_by": "pipeline/build_trap_map.py",
    }
    seen, changes = set(), []
    for r in d["rows"]:
        for h in r.get("history") or []:
            if h["text"] in seen:
                continue
            seen.add(h["text"])
            changes.append({"date": h["at"][:10], "at": h["at"], "text": h["text"]})
    changes.sort(key=lambda c: datetime.fromisoformat(c["at"]), reverse=True)
    d["changes"] = changes
    return d


def sorted_rows(d):
    return sorted(d["rows"], key=lambda r: (ORDER.get(r["status"], 9), (r["event"].get("date") or "9999")))


def _value_line(r):
    t = r["trade"]
    if t.get("value") is None:
        return ""
    px = f"Mid {t['mid']}, " if t.get("mid") is not None else "Close, "
    return f"<br>Worth {money(t['value'])} (paid {money(t['cost'])})<br>{px}{e(fmt_time(t['mid_time']))}"


def _graded_on(r):
    t = r["trade"]
    if r["status"] == "graded":
        return (f'<span class="out {e(r["outcome"])}">{e(r["outcome"])}</span>'
                f'<div class="small">Graded {e(fmt_date(r["graded_on"]))}. {e(r.get("grade_detail", ""))}</div>')
    if r["status"] == "holding":
        idx = f" Index now {t['index_now']}." if t.get("index_now") is not None else ""
        return (f'<span class="margin">Stay long unless stopped out</span><div class="small">{e(t["stop"])}{e(idx)}</div>'
                f'<div class="small">{e(t["grade_rule"])}</div>')
    return f'<span class="margin">{e(fmt_date(t["grade_date"]))} close</span><div class="small">{e(t["grade_rule"])}</div>'


def _why(r):
    t = r["trade"]
    out = e(r["reason"])
    if r.get("notes"):
        out += f'<div class="small mt"><b>Notes:</b> {e(r["notes"])}</div>'
    if r.get("main_risk"):
        out += f'<div class="note">{e(r["main_risk"])}</div>'
    out += f'<div class="small mt"><b>What proves it:</b> {e(r["what_proves_it"])}</div>'
    out += f'<div class="small"><b>Why we hold this view:</b> {e(r["why_we_hold"])}</div>'
    out += (f'<div class="small"><b>Paper trade:</b> {e(t["text"])}. Most it can lose: {e(t["max_loss"])}. '
            f'Quoted {e(t["quoted"])}.</div>')
    return out


def _event(r):
    ev = r["event"]
    res = r.get("research")
    out = e(ev["name"])
    if res:
        out += f'<div class="small"><a href="{e(_rel(res["url"]))}"><b>{e(res["label"])}</b></a></div>'
    out += f'<div class="small">{e(ev["when"])}</div><div class="small"><a href="{e(_rel(ev["link"]))}">{e(ev["link_label"])}</a></div>'
    return out


def _rel(url: str) -> str:
    """Own-site links stay relative so they work on any host."""
    return re.sub(r"^https://jsheppard8989\.github\.io/ai-finance-tech-dashboard/", "", url)


def _status(r):
    return (f'<span class="st s-{e(r["status"])}">{e(r["status"].upper())}</span><div class="small mt">'
            f'Added {e(fmt_date(r["date_added"]))}<br>Checked {e(fmt_date(r["last_reviewed"]))}{_value_line(r)}</div>')


def _stock(r):
    return f'<div class="tk">{e(r["ticker"])}</div><div class="co">{e(r["company"])}</div>'


def _call(r):
    return f'<span class="lean {e(r["lean"])}">{e(r["lean"])}</span><div class="small mt">{e(r["horizon"])}</div>'


def render_page(d: dict) -> str:
    T, b = d["totals"], d["benchmark"]
    rows = sorted_rows(d)
    mid_time = next(r["trade"]["mid_time"] for r in rows if r["trade"].get("mid_time"))
    buys = "; ".join(f'{money(x["dollars"])} on {fmt_date(x["date"])} at {money(x["price"])}' for x in b["buys"])
    trs = "\n".join(
        f'<tr id="row-{e(r["id"])}"><td>{_stock(r)}</td><td>{_call(r)}</td><td>{_why(r)}</td><td>{_event(r)}</td>'
        f'<td>{_graded_on(r)}</td><td>{_status(r)}</td></tr>' for r in rows)
    cards = "\n".join(
        f'<details class="ev" id="{e(r["id"])}" data-published="{e(r["trade"].get("posted") or r["date_added"])}">'
        f'<summary><span class="tk">{e(r["ticker"])}</span> <span class="lean {e(r["lean"])}">{e(r["lean"])}</span> '
        f'<span class="st s-{e(r["status"])}">{e(r["status"].upper())}</span>'
        f'<span class="sumline">{e(r["reason"])}</span>'
        f'<span class="small">{e(r["company"])} · {e(r["horizon"])}</span></summary>'
        f'<div class="cb"><div>{_why(r)}</div><h4>The event</h4><div>{_event(r)}</div>'
        f'<h4>Graded on</h4><div>{_graded_on(r)}</div><h4>Status</h4><div>{_status(r)}</div></div></details>'
        for r in rows)
    log = "\n".join(f'<li><b>{e(fmt_date(c["date"]))}:</b> {e(c["text"])}</li>' for c in d["changes"])
    past = ""
    if d.get("past_calls"):
        past = "<h2>Past calls</h2><ul class=\"log\">" + "".join(
            f'<li><b>{e(c["ticker"])}</b> <span class="lean {e(c["lean"])}">{e(c["lean"])}</span> {e(c["outcome_text"])} '
            f'Grade: <span class="out {e(c["grade"])}">{e(c["grade"])}</span></li>' for c in d["past_calls"]) + "</ul>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Trap Map</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- Generated by pipeline/build_trap_map.py from site/data/trap_map.json. Do not edit by hand. -->
<style>
:root{{--pos:#0f7b4a;--neg:#b42318;--ink:#1b1f24;--mute:#5d6670;--line:#e3e6ea;--bg:#f7f8fa}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.wrap{{max-width:1180px;margin:0 auto;padding:22px 24px 40px}}
.top{{font-size:13px;margin-bottom:10px}}
h1{{margin:0 0 4px;font-size:26px}}.sub{{color:var(--mute);margin:0 0 14px}}
.bar{{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:14px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:12px 14px}}
.tr{{flex:2;min-width:300px}}.tr b{{font-size:17px}}.legend{{flex:3;min-width:300px;font-size:13px;color:var(--mute)}}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:10px;overflow:hidden}}
th{{text-align:left;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute);background:#fbfbfc;padding:9px 10px;border-bottom:1px solid var(--line)}}
td{{padding:10px;border-bottom:1px solid var(--line);vertical-align:top}}
.tk{{font-weight:700}}.co{{color:var(--mute);font-size:13px}}
.lean{{display:inline-block;font-weight:700;font-size:13px;padding:2px 8px;border-radius:999px;color:#fff}}
.Positive{{background:var(--pos)}}.Negative{{background:var(--neg)}}
.st{{font-size:12px;font-weight:700;padding:2px 7px;border-radius:6px;border:1px solid}}
.s-new{{color:#6b4e00;border-color:#d8b44a;background:#fff8e1}}.s-live{{color:#0b5cad;border-color:#8fbbe8;background:#eef5fd}}.s-holding{{color:#0f7b4a;border-color:#8fd1b0;background:#eefaf3}}.s-graded{{color:#444;border-color:#bbb;background:#f1f1f1}}
.small{{font-size:12.5px;color:var(--mute)}}.note{{font-size:12.5px;color:#7a4b00;margin-top:3px}}.mt{{margin-top:4px}}
.margin{{font-weight:700}}
.out{{font-weight:700}}.out.Push{{color:#555}}.out.Right{{color:var(--pos)}}.out.Wrong{{color:var(--neg)}}
a{{color:#0b5cad}}h2{{font-size:17px;margin:22px 0 8px}}
.log li{{margin:3px 0}}.foot{{font-size:12.5px;color:var(--mute);margin-top:18px}}
.cards{{display:none}}
details.ev{{background:#fff;border:1px solid var(--line);border-radius:10px;margin:0 0 10px;padding:0}}
details.ev summary{{list-style:none;cursor:pointer;padding:12px 14px;display:block}}
details.ev summary::-webkit-details-marker{{display:none}}
details.ev summary::after{{content:"Tap for details ▾";display:block;font-size:12px;color:#0b5cad;margin-top:4px}}
details.ev[open] summary::after{{content:"Hide details ▴"}}
.sumline{{display:block;margin:6px 0 2px}}
.cb{{padding:0 14px 14px;border-top:1px solid var(--line)}}.cb h4{{margin:10px 0 2px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}}
@media (max-width:760px){{.wrap{{padding:14px 12px 30px}}table{{display:none}}.cards{{display:block}}.tr,.legend{{min-width:0;flex:1 1 100%}}}}
</style></head><body><div class="wrap">
<div class="top"><a href="index.html">← Home</a></div>
<h1>{e(d["title"])}</h1>
<p class="sub">{e(d["purpose"])}</p>
<div class="bar">
 <div class="card tr" id="tot"><b>Running total</b><br>Cost to fund every trade: {money(T["cost"])}<br>What the trades are worth now: <b>{money(T["value"])}</b><br>If we'd put the same money in the S&amp;P 500 on the same days: <b>{money(T["spy_value"])}</b><br><span class="small">Values at the midpoint, {e(fmt_time(mid_time))}. S&amp;P 500 as SPY: {e(buys)}; SPY now {money(b["spy_close_now"])} ({e(fmt_time(b["spy_close_time"]))}).</span></div>
 <div class="card legend"><b>How we grade.</b> {e(d["how_we_grade"])}</div>
</div>
<table><thead><tr><th style="width:120px">Stock</th><th style="width:92px">Our call</th><th>Why we think so</th><th style="width:205px">The event</th><th style="width:170px">Graded on</th><th style="width:120px">Status</th></tr></thead><tbody>
{trs}
</tbody></table>
<div class="cards">
{cards}
</div>
{past}
<h2>What changed</h2><ul class="log">
{log}
</ul>
<p class="foot">{e(d["disclaimer"])} Prices from Yahoo Finance. Updated {e(fmt_time(d["as_of"]))}.</p>
</div>
<script>
(function(){{function openLinked(){{var id=location.hash.slice(1);if(!id)return;var el=document.getElementById(id);if(el&&el.tagName==='DETAILS'){{el.open=true;el.scrollIntoView();}}}}
window.addEventListener('hashchange',openLinked);openLinked();}})();
</script>
</body></html>
"""


def render_strip(d: dict) -> str:
    T = d["totals"]
    chips = "".join(
        f'<a class="trap-chip" href="trap-map.html#{e(r["id"])}" style="display:inline-block;margin:0.2rem 0.35rem 0.2rem 0;padding:0.3rem 0.55rem;border:1px solid rgba(255,255,255,0.12);border-radius:8px;color:#e6f1ff;text-decoration:none;font-size:0.75rem;">'
        f'<strong>{e(r["ticker"])}</strong> <span style="color:{"#34d399" if r["lean"] == "Positive" else "#f87171"};">{e(r["lean"])}</span> '
        f'<span style="color:#9ca3af;">· {e(("Graded " + fmt_date(r["trade"]["grade_date"])) if r["trade"].get("grade_date") else "Holding until stopped out")}'
        f' · worth {money(r["trade"]["value"])} (paid {money(r["trade"]["cost"])})</span></a>'
        for r in sorted_rows(d))
    return (f'{START}\n    <div class="card" id="trap-map-strip" style="padding: 0.75rem; margin: 0 0 1rem 0;">\n'
            f'      <h3 style="font-size: 0.9rem; color: #00d4ff; margin-bottom: 0.25rem;"><a href="trap-map.html" style="color:#00d4ff;text-decoration:none;">🪤 Trap Map</a></h3>\n'
            f'      <p style="color: #9ca3af; font-size: 0.7rem; margin-bottom: 0.4rem;">{e(d["purpose"])} Tracked as paper trades. '
            f'Paid {money(T["cost"])} · worth now {money(T["value"])} · same money in the S&amp;P 500: {money(T["spy_value"])}.</p>\n'
            f'      <div>{chips}</div>\n    </div>\n    {END}')


def apply_strip(index_html: str, strip: str) -> str:
    if START in index_html:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: strip, index_html, flags=re.S)
    anchor = '    <div class="grid">'
    assert anchor in index_html, "index.html: grid anchor not found for the Trap Map strip"
    return index_html.replace(anchor, "    " + strip + "\n\n" + anchor, 1)


def build(write=True):
    d = json.loads(DATA.read_text(encoding="utf-8"))
    errs = trap_map_check.check(d)
    if errs:
        raise SystemExit("Trap Map check failed:\n  " + "\n  ".join(errs))
    d = compute(d)
    data_out = json.dumps(d, indent=1, ensure_ascii=False) + "\n"
    page = render_page(d)
    idx = apply_strip(INDEX.read_text(encoding="utf-8"), render_strip(d))
    outs = {DATA: data_out, PAGE: page, INDEX: idx}
    stale = [p for p, s in outs.items() if not p.exists() or p.read_text(encoding="utf-8") != s]
    if write:
        for p in stale:
            p.write_text(outs[p], encoding="utf-8")
    return stale


if __name__ == "__main__":
    if "--check" in sys.argv:
        stale = build(write=False)
        if stale:
            print("Trap Map outputs out of date:", ", ".join(str(p.relative_to(ROOT)) for p in stale))
            sys.exit(1)
        print("Trap Map outputs up to date")
    else:
        print("Wrote:", ", ".join(str(p.relative_to(ROOT)) for p in build()) or "nothing (up to date)")
