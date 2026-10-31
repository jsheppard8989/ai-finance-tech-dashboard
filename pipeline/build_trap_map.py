#!/usr/bin/env python3
"""Build the Trap Map from its one source of truth, site/data/trap_map.json.

Writes:
  - site/trap-map.html             (v9 layout: one card-row per trade; scrolls sideways on phones)
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
MINUS = "\u2212"
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


def newest_quote_time(d: dict):
    """Newest price timestamp actually written: open-row trade.mid_time and the SPY close time."""
    stamps = [(r.get("trade") or {}).get("mid_time") for r in d["rows"] if r.get("status") != "graded"]
    stamps.append((d.get("benchmark") or {}).get("spy_close_time"))
    parsed = [datetime.fromisoformat(s).astimezone(CT) for s in stamps if s]
    return max(parsed).isoformat(timespec="seconds") if parsed else None


def compute(d: dict) -> dict:
    newest = newest_quote_time(d)
    if newest:
        d["quotes_as_of"] = newest
    rows = [r for r in d["rows"] if r.get("status") != "graded" and (r.get("trade") or {}).get("cost") is not None]
    b = d["benchmark"]
    d["totals"] = {
        "cost": round(sum(r["trade"]["cost"] for r in rows), 2),
        "value": round(sum(r["trade"]["value"] for r in rows), 2),
        "spy_value": round(sum(x["shares"] for x in b["buys"]) * b["spy_close_now"], 2),
        "change": round(sum(r["trade"]["value"] for r in rows) - sum(r["trade"]["cost"] for r in rows), 2),
        "computed_by": "pipeline/build_trap_map.py",
    }
    for r in rows:
        r["trade"]["change"] = round(r["trade"]["value"] - r["trade"]["cost"], 2)
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


def _dt(s) -> datetime:
    return datetime.fromisoformat(s).astimezone(CT)


def _fmt_full(s) -> str:
    t = _dt(s)
    return f"{t.strftime('%b')} {t.day}, {t.year}, {t.strftime('%I:%M %p').lstrip('0')} CT"


def _sg(n) -> str:
    return ("+" if n >= 0 else "\u2212") + money(abs(n))


def _cl(n) -> str:
    return "up" if n >= 0 else "down"


def _hue(t: str) -> str:
    h = 0
    for ch in t:
        h = (h * 31 + ord(ch)) % 360
    return f"hsl({h},45%,42%)"


def _is_long(direction: str) -> bool:
    return "short" not in direction.lower()


def _exit_cell(r, today: date) -> str:
    t, ev = r["trade"], r["event"]
    prog = ""
    if not t.get("grade_date"):
        top, sub = "When a stop is hit", e(t["stop"])
    elif r["status"] == "graded" or date.fromisoformat(t["grade_date"]) < today:
        top, sub = "Graded", e(ev["name"])
    else:
        gd = date.fromisoformat(t["grade_date"])
        left = (gd - today).days
        tot = max(1, (gd - date.fromisoformat(t.get("posted") or r["date_added"])).days)
        done = max(2, 100 * (tot - left) / tot)
        top, sub = e(fmt_date(t["grade_date"])), f"{e(ev['name'])} · {e(ev['when'])}"
        prog = f'<div class="prog"><i style="width:{done:.1f}%"></i></div><div class="small">{left} days to go</div>'
    return (f'<div class="exit">{top}</div>{prog}<div class="small" style="margin-top:3px">{sub}</div>'
            f'<div class="small"><a href="{e(_rel(ev["link"]))}">{e(ev["link_label"])}</a></div>')


def _expr_cell(r) -> str:
    t = r["trade"]
    x = t["expression"]
    if x.get("holdings"):
        dl = "".join(f'<dt>{e(h["ticker"])}</dt><dd>{e(h["shares"])} sh at ${h["entry"]:.2f}</dd>' for h in x["holdings"])
        dl += f'<dt>Bought</dt><dd>{e(x["bought"])}</dd><dt>Most it can lose</dt><dd>{e(t["max_loss"])}</dd>'
        return f'<div class="expr"><div class="ty">{e(x["type"])}</div><dl>{dl}</dl><div class="small" style="margin-top:4px">{e(t["grade_rule"])}</div></div>'
    dl = (f'<dt>Strikes</dt><dd>{e(x["strikes"])}</dd><dt>Expiry</dt><dd>{e(x["expiry"])}</dd>'
          f'<dt>Contracts</dt><dd>{e(x["contracts"])}</dd><dt>Cost</dt><dd>{e(x["debit"])}</dd>'
          f'<dt>Stock then</dt><dd>{e(x["stock_then"])}</dd><dt>Most it can lose</dt><dd>{e(t["max_loss"])}</dd>')
    note = f'<div class="note">Note: {e(x["caveat"])}.</div>' if x.get("caveat") else ""
    return f'<div class="expr"><div class="ty">{e(x["type"])}</div><dl>{dl}</dl>{note}<div class="small" style="margin-top:4px">{e(t["grade_rule"])}</div></div>'


def _gl_bar(c, cost, max_p) -> str:
    p = c / cost
    w = 50 * abs(p) / max_p if max_p else 0
    pos = "left:50%" if p >= 0 else f"left:{50 - w:.2f}%"
    return (f'<div class="gl"><b></b><i style="{pos};width:{w:.2f}%;background:var(--{"pos" if p >= 0 else "neg"})"></i></div>'
            f'<div class="pct {_cl(c)}">{"+" if p >= 0 else MINUS}{abs(100 * p):.1f}%</div>')


def _row(r, today: date, max_p: float) -> str:
    t = r["trade"]
    k = "L" if _is_long(r["direction"]) else "S"
    why = e(r["reason"])
    if r.get("notes"):
        why += f'<div class="small" style="margin-top:4px"><b>Notes:</b> {e(r["notes"])}</div>'
    if r.get("main_risk"):
        why += f'<div class="note">{e(r["main_risk"])}</div>'
    why += (f'<div class="small" style="margin-top:4px"><b>What proves it:</b> {e(r["what_proves_it"])}</div>'
            f'<div class="small"><b>Why we hold this view:</b> {e(r["why_we_hold"])}</div>')
    if r["status"] == "graded":
        why += f'<div class="small"><b>Graded {e(fmt_date(r["graded_on"]))}: {e(r["outcome"])}.</b> {e(r.get("grade_detail", ""))}</div>'
    return (f'<tr class="{k}" id="row-{e(r["id"])}">'
            f'<td><div class="stk"><div class="mono" style="background:{_hue(r["ticker"])}">{e(r["ticker"][:4])}</div><div>'
            f'<div class="tk">{e(r["ticker"])}</div><div class="co">{e(r["company"])}</div>'
            f'<div class="added">Added {e(fmt_date(r["date_added"]))}</div></div></div></td>\n'
            f' <td><span class="dir d{k}">{e(r["direction"])}</span><div class="small" style="margin-top:5px">{e(r["horizon"])}</div></td>\n'
            f' <td>{why}</td>\n <td>{_exit_cell(r, today)}</td><td>{_expr_cell(r)}</td>\n'
            f' <td class="money"><div class="paid">Allocated {money(t["cost"])}</div><div class="d {_cl(t["change"])}">{_sg(t["change"])}</div>'
            f'{_gl_bar(t["change"], t["cost"], max_p)}</td></tr>')


# Old row ids that now live inside another row. Kept as hidden anchors so old links still land.
MOVED = {"hims-q3": "healthcare-five"}


def _card(r, today: date, max_p: float) -> str:
    """Phone layout: tap-to-expand card. Carries the public #id (the desktop row is #row-<id>)."""
    t = r["trade"]
    k = "L" if _is_long(r["direction"]) else "S"
    why = e(r["reason"])
    if r.get("notes"):
        why += f'<div class="small" style="margin-top:4px"><b>Notes:</b> {e(r["notes"])}</div>'
    if r.get("main_risk"):
        why += f'<div class="note">{e(r["main_risk"])}</div>'
    why += (f'<div class="small" style="margin-top:4px"><b>What proves it:</b> {e(r["what_proves_it"])}</div>'
            f'<div class="small"><b>Why we hold this view:</b> {e(r["why_we_hold"])}</div>')
    return (f'<details class="ev" id="{e(r["id"])}" data-dir="{k}" data-published="{e(t.get("posted") or r["date_added"])}">'
            f'<summary><span class="tk">{e(r["ticker"])}</span> <span class="dir d{k}">{e(r["direction"])}</span> '
            f'<span class="d {_cl(t["change"])}">{_sg(t["change"])}</span>'
            f'<span class="sumline">{e(r["reason"])}</span>'
            f'<span class="small">{e(r["company"])} · {e(r["horizon"])} · Allocated {money(t["cost"])}</span></summary>'
            f'<div class="cb"><div>{why}</div><h4>Expected exit</h4><div>{_exit_cell(r, today)}</div>'
            f'<h4>Expression</h4><div>{_expr_cell(r)}</div><h4>Money</h4><div class="money">'
            f'<div class="paid">Allocated {money(t["cost"])}</div><div class="d {_cl(t["change"])}">{_sg(t["change"])}</div>'
            f'{_gl_bar(t["change"], t["cost"], max_p)}</div></div></details>')


def render_page(d: dict) -> str:
    """v9 layout. Server-rendered from the JSON (no separate data file, no client script)."""
    T = d["totals"]
    today = _dt(d["quotes_as_of"]).date()
    open_rows = sorted((r for r in d["rows"] if r["status"] != "graded"), key=lambda r: r["event"].get("date") or "9999")
    closed = [r for r in d["rows"] if r["status"] == "graded"]
    spy_c = round(T["spy_value"] - T["cost"], 2)
    zm = max(abs(T["change"]), abs(spy_c)) * 1.15 or 1

    def zr(c, lab):
        w = 50 * abs(c) / zm
        pos = "left:50%" if c >= 0 else f"left:{50 - w:.2f}%"
        return (f'<div class="zrow"><b>{lab}</b><div class="ztrk"><b></b><i style="{pos};width:{w:.2f}%;'
                f'background:{"var(--pos)" if c >= 0 else "var(--neg)"}"></i></div>'
                f'<span class="chg {_cl(c)}">{_sg(c)} ({"+" if c >= 0 else MINUS}{abs(100 * c / T["cost"]):.1f}%)</span></div>')
    axis = f"${int(zm):,}"
    hero = (f'<div class="kpis"><div><div class="lbl">Our trades are worth</div><div class="big">{money(T["value"])}</div></div>'
            f'<div><div class="lbl">Allocated</div><div class="mid">{money(T["cost"])}</div></div>'
            f'<div><div class="lbl">Same money in the S&amp;P 500</div><div class="mid">{money(T["spy_value"])}</div></div></div>\n'
            f'<div class="zbar"><div class="lbl">Gain or loss since each trade was added</div>{zr(T["change"], "Our trades")}'
            f'{zr(spy_c, "S&amp;P 500")}<div class="zax"><span></span><div><span>\u2212{axis}</span><span>$0</span>'
            f'<span>+{axis}</span></div><span></span></div></div>')
    max_p = max([abs(r["trade"]["change"] / r["trade"]["cost"]) for r in open_rows] or [1])
    trs = "\n".join(_row(r, today, max_p) for r in open_rows)
    cards = "\n".join(_card(r, today, max_p) for r in open_rows + closed)
    ids = {r["id"] for r in d["rows"]}
    moved = {o: n for o, n in MOVED.items() if n in ids and o not in ids}
    cards += "".join(f'\n<details class="ev" id="{e(o)}" data-moved-to="{e(n)}" hidden></details>' for o, n in moved.items())
    moved_js = json.dumps(moved)
    past = d.get("past_calls") or []
    closed_html = ""
    if closed or past:
        closed_html = ("<h2>Closed</h2><table><tbody>" + "".join(_row(r, today, max_p) for r in closed) + "".join(
            f'<tr><td><div class="tk">{e(c["ticker"])}</div></td><td colspan="4">{e(c["outcome_text"])}</td>'
            f'<td>Graded: {e(c["grade"])}</td></tr>' for c in past) + "</tbody></table>")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Trap Map</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<!-- Generated by pipeline/build_trap_map.py from site/data/trap_map.json. Do not edit by hand. -->
<style>
:root{{--pos:#0f7b4a;--neg:#b42318;--ink:#1b1f24;--mute:#5d6670;--line:#e3e6ea;--bg:#f4f6f9}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.45 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:var(--ink);background:var(--bg)}}
.wrap{{max-width:1220px;margin:0 auto;padding:22px 24px 40px}}
h1{{margin:0 0 4px;font-size:30px;letter-spacing:-.02em}}.sub{{color:var(--mute);margin:0 0 4px}}.asof{{font-size:13px;color:var(--mute);margin:0 0 16px;font-weight:600}}
.bar{{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px}}
.card{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px 18px;box-shadow:0 1px 2px rgba(16,24,40,.04)}}
.hero{{flex:1;background:linear-gradient(135deg,#ffffff,#f3f8f5)}}
.kpis{{display:flex;gap:28px;align-items:flex-end}}
.lbl{{font-size:11.5px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);font-weight:600}}
.big{{font-size:32px;font-weight:800;letter-spacing:-.02em;line-height:1.1;font-variant-numeric:tabular-nums}}.mid{{font-size:22px;font-weight:700;font-variant-numeric:tabular-nums}}
.chg{{font-weight:700;font-variant-numeric:tabular-nums}}
.zbar{{margin-top:14px}}.zrow{{display:grid;grid-template-columns:120px 1fr 120px;gap:10px;align-items:center;font-size:13px;margin:6px 0}}
.ztrk{{position:relative;height:14px;background:#eef0f3;border-radius:7px}}.ztrk i{{position:absolute;top:0;height:100%;border-radius:7px}}.ztrk b{{position:absolute;left:50%;top:-4px;width:2px;height:22px;background:#6b7580}}
.zax{{display:grid;grid-template-columns:120px 1fr 120px;gap:10px;font-size:11px;color:var(--mute)}}.zax div{{display:flex;justify-content:space-between}}
.legend{{flex:2;min-width:300px;font-size:13px;color:var(--mute)}}
table{{width:100%;border-collapse:separate;border-spacing:0 8px;margin-top:-8px}}
th{{text-align:left;border:0!important;background:transparent!important;font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--mute);background:#fafbfc;padding:10px;border-bottom:1px solid var(--line)}}
td{{padding:12px 10px;vertical-align:top;background:#fff;border-top:1.5px solid #cfd5dc;border-bottom:1.5px solid #cfd5dc}}
td:last-child{{border-right:1.5px solid #cfd5dc;border-radius:0 10px 10px 0}}
td:first-child{{border-left:1.5px solid #cfd5dc;border-radius:10px 0 0 10px}}
tbody tr:nth-child(even) td{{background:#fcfdfe}}
tr.L td:first-child{{border-left:5px solid var(--pos)}}tr.S td:first-child{{border-left:5px solid var(--neg)}}
.stk{{display:flex;gap:9px;align-items:flex-start}}
.mono{{flex:none;width:38px;height:38px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;color:#fff}}
.tk{{font-weight:800;font-size:16px}}.co{{color:var(--mute);font-size:12.5px}}.added{{font-size:12px;color:var(--mute);margin-top:3px}}
.dir{{display:inline-block;font-weight:700;font-size:12.5px;padding:3px 9px;border-radius:999px;white-space:nowrap}}
.dL{{background:#e6f4ec;color:var(--pos);border:1px solid #9fd4b8}}.dS{{background:#fdecea;color:var(--neg);border:1px solid #f0aaa3}}
.small{{font-size:12.5px;color:var(--mute)}}.note{{font-size:12.5px;color:#7a4b00;margin-top:3px}}
.exit{{font-weight:800;font-size:16px}}.up{{color:var(--pos)}}.down{{color:var(--neg)}}
.prog{{height:6px;background:#eef0f3;border-radius:3px;margin:6px 0 2px;overflow:hidden}}.prog i{{display:block;height:100%;background:#4a74c9;border-radius:3px}}
.expr .ty{{font-weight:700;font-size:13px}}.expr dl{{margin:4px 0 0;display:grid;grid-template-columns:auto 1fr;gap:1px 8px;font-size:12.5px}}.expr dt{{color:var(--mute)}}.expr dd{{margin:0}}
.money .paid{{font-size:12.5px;color:var(--mute)}}.money .d{{font-size:18px;font-weight:800;font-variant-numeric:tabular-nums}}
.gl{{position:relative;height:10px;background:#eef0f3;border-radius:5px;margin-top:6px}}.gl i{{position:absolute;top:0;height:100%;border-radius:5px}}.gl b{{position:absolute;left:50%;top:-3px;width:1px;height:16px;background:#9aa3ad}}
.pct{{font-size:12px;font-weight:600}}
a{{color:#0b5cad}}h2{{font-size:17px;margin:22px 0 8px}}
.log li{{margin:3px 0}}.foot{{font-size:12.5px;color:var(--mute);margin-top:18px}}

.cards{{display:none}}
details.ev{{background:#fff;border:1.5px solid #cfd5dc;border-radius:10px;margin:0 0 10px}}details.ev[data-dir=L]{{border-left:5px solid var(--pos)}}details.ev[data-dir=S]{{border-left:5px solid var(--neg)}}
details.ev summary{{list-style:none;cursor:pointer;padding:12px 14px;display:block}}details.ev summary::-webkit-details-marker{{display:none}}
details.ev summary::after{{content:"Tap for details \u25be";display:block;font-size:12px;color:#0b5cad;margin-top:4px}}details.ev[open] summary::after{{content:"Hide details \u25b4"}}
details.ev .d{{font-weight:800;float:right}}.sumline{{display:block;margin:6px 0 2px}}
.cb{{padding:0 14px 14px;border-top:1px solid var(--line)}}.cb h4{{margin:10px 0 2px;font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}}
@media (max-width:760px){{.wrap{{padding:14px 12px 30px}}table{{display:none}}.cards{{display:block}}.kpis{{flex-wrap:wrap;gap:14px}}.zrow,.zax{{grid-template-columns:80px 1fr 110px}}}}
</style></head><body><div class="wrap">
<div class="top" style="font-size:13px;margin-bottom:10px"><a href="index.html">\u2190 Home</a></div>
<h1>Trap Map</h1>
<p class="sub">{e(d["purpose"])}</p>
<p class="asof" id="asof">Quotes as of {e(_fmt_full(d["quotes_as_of"]))}</p>
<div class="bar">
 <div class="card hero" id="tot">{hero}</div>
</div>
<table class="desk"><thead><tr><th style="width:170px">Stock</th><th style="width:96px">Direction</th><th>Why we think so</th><th style="width:170px">Expected exit</th><th style="width:235px">Expression</th><th style="width:140px">Money</th></tr></thead><tbody id="rows">
{trs}
</tbody></table>
<div class="cards">
{cards}
</div>
<div id="closedwrap">{closed_html}</div>
<p class="foot">This is our opinion, not advice. These are paper trades only. Prices from Yahoo Finance.</p>
</div>
<script>
(function(){{var moved={moved_js};function openLinked(){{var id=location.hash.slice(1);if(!id)return;id=moved[id]||id;
var el=document.getElementById(id);if(el&&el.tagName==='DETAILS'){{el.open=true;}}
var row=document.getElementById('row-'+id);var target=(row&&row.offsetParent!==null)?row:el;if(target)target.scrollIntoView();}}
window.addEventListener('hashchange',openLinked);openLinked();}})();
</script>
</body></html>
"""


def grade_label(grade_date, today: date | None = None) -> str:
    """'Grades <date>' while the grade date is still ahead (CT), 'Graded <date>' once reached."""
    today = today or datetime.now(CT).date()
    gd = date.fromisoformat(str(grade_date)[:10])
    return ("Grades " if gd > today else "Graded ") + fmt_date(grade_date)


def render_strip(d: dict, today: date | None = None) -> str:
    T = d["totals"]
    chips = "".join(
        f'<a class="trap-chip" href="trap-map.html#{e(r["id"])}" style="display:inline-block;margin:0.2rem 0.35rem 0.2rem 0;padding:0.3rem 0.55rem;border:1px solid rgba(255,255,255,0.12);border-radius:8px;color:#e6f1ff;text-decoration:none;font-size:0.75rem;">'
        f'<strong>{e(r["ticker"])}</strong> <span style="color:{"#34d399" if _is_long(r["direction"]) else "#f87171"};">{e(r["direction"])}</span> '
        f'<span style="color:#9ca3af;">· {e(grade_label(r["trade"]["grade_date"], today) if r["trade"].get("grade_date") else "Holding until stopped out")}'
        f' · worth {money(r["trade"]["value"])} (allocated {money(r["trade"]["cost"])}'
        f'{", index " + str(r["trade"]["index_now"]) if r["trade"].get("index_now") is not None else ""})</span></a>'
        for r in sorted_rows(d))
    return (f'{START}\n    <div class="card" id="trap-map-strip" style="padding: 0.75rem; margin: 0 0 1rem 0;">\n'
            f'      <h3 style="font-size: 0.9rem; color: #00d4ff; margin-bottom: 0.25rem;"><a href="trap-map.html" style="color:#00d4ff;text-decoration:none;">🪤 Trap Map</a></h3>\n'
            f'      <p style="color: #9ca3af; font-size: 0.7rem; margin-bottom: 0.4rem;">{e(d["purpose"])} Tracked as paper trades. '
            f'Allocated {money(T["cost"])} · worth now {money(T["value"])} ({_sg(T["change"])}) · same money in the S&amp;P 500: '
            f'{money(T["spy_value"])} ({_sg(round(T["spy_value"] - T["cost"], 2))}). Quotes as of {e(fmt_time(d["quotes_as_of"]))}.</p>\n'
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
    errs = trap_map_check.check_computed(d)
    if errs:
        raise SystemExit("Trap Map check failed after compute:\n  " + "\n  ".join(errs))
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
