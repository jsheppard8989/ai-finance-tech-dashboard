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


PAGE_SUBTITLE = "Paper trades at real prices. The market keeps score."  # page only; homepage strip keeps d["purpose"]
CLOSED_PREVIEW = Path(__file__).resolve().parent / "trap_map_closed_preview.json"
ENDED = {"Target": ("Hit target", "RIGHT"), "Stop": ("Hit stop", "WRONG"), "Not placed": ("Not placed", "NONE")}


def _closed_extra():
    """Closed rows kept outside trap_map.json (preview copy; edit or delete this one file to change them)."""
    return json.loads(CLOSED_PREVIEW.read_text(encoding="utf-8")) if CLOSED_PREVIEW.exists() else []


def _plain(r) -> str:
    if not _is_long(r["direction"]):
        return "We expect the stock to fall"
    return "We expect these stocks to rise" if r.get("kind") == "basket" else "We expect the stock to rise"


def _bar(c, scale) -> str:
    w = 48 * abs(c) / scale if scale else 0
    pos = "left:50%" if c >= 0 else f"left:{50 - w:.2f}%"
    return f'<div class="gl"><span class="mid"></span><i class="{"p" if c >= 0 else "n"}" style="{pos};width:{max(w, .8):.2f}%"></i></div>'


def _paper(t) -> str:
    x = t.get("expression") or {}
    if x.get("holdings"):
        return ", ".join(h["ticker"] for h in x["holdings"]) + " stock basket, equal dollars"
    n = x.get("contracts")
    return f'{x["expiry"]} {x["strikes"].replace(" ", "")} put spread, {n} contract{"s" if n != 1 else ""}'


def _exit(r, today: date) -> str:
    """Spreads are held to expiry by default, so the expected exit is the option expiry."""
    t = r["trade"]
    if not t.get("expiry"):
        return f'<div class="ex">Until a stop is hit</div><div class="sm">{e(t.get("stop", ""))}</div>'
    ex = date.fromisoformat(t["expiry"])
    left = max(0, (ex - today).days)
    tot = max(1, (ex - date.fromisoformat(t.get("posted") or r["date_added"])).days)
    return (f'<div class="ex">{e(fmt_date(t["expiry"]))}</div><div class="prog"><i style="width:{max(3, 100 * (tot - left) / tot):.0f}%">'
            f'</i></div><div class="sm">{left} days to go · Option expiry</div>')


def _open_card(r, today: date, mx: float) -> str:
    t = r["trade"]
    c = t["change"]
    lng = _is_long(r["direction"])
    res = r.get("research")
    ev = r.get("event") or {}
    if not res and ev.get("link") and _rel(ev["link"]) != ev["link"]:  # own-site research page
        res = {"url": ev["link"], "label": ev.get("link_label") or "Read our research"}
    link = f' <a href="{e(_rel(res["url"]))}">{e(res["label"])} \u2192</a>' if res else ""
    cav = (t.get("expression") or {}).get("caveat") or ""
    note = f'<div class="note">Note: {e(cav)}.</div>' if "open interest" in cav else ""
    return (f'<details class="ev" id="{e(r["id"])}" data-dir="{"L" if lng else "S"}" open><summary hidden></summary>'
            f'<article class="card {"cu" if c >= 0 else "cd"}">\n'
            f'<div class="tk"><div class="sym">{e(r["ticker"])}</div><div class="co">{e(r["company"])}</div>'
            f'<div class="added">Added {e(fmt_date(r["date_added"]))}</div></div>\n'
            f'<div class="why"><span class="chip {"lg" if lng else "sh"}">{e(r["direction"])}</span> <span class="exp">{_plain(r)}</span><br> '
            f'<span class="sm"><b>Paper trade:</b> {e(_paper(t))}</span><p>{e(r["reason"])}{link}</p>'
            f'<div class="sm"><b>What proves it:</b> {e(r["what_proves_it"])}</div>{note}</div>\n'
            f'<div class="exit"><div class="lbl">Expected exit</div>{_exit(r, today)}</div>\n'
            f'<div class="money"><div class="lbl">Allocated</div><div class="cost">{money(t["cost"])}</div>'
            f'<div class="lbl" style="margin-top:6px">Change</div><div class="chg {"up" if c >= 0 else "dn"}">{_sg(c)}</div>{_bar(c, mx)}</div>\n</article></details>')


def _closed_card(c) -> str:
    """Closed position: only what the data states (no computed results, $ only)."""
    word, cls = ENDED.get(c.get("ended"), (c.get("ended") or "Closed", "NONE"))
    money_html = f'<div class="lbl">Allocated</div><div class="cost">{money(c["allocated"])}</div>' if c.get("allocated") else ""
    usd, pct = c.get("result_usd"), c.get("result_pct")
    if usd is not None or pct is not None:
        sign = (usd if usd is not None else pct) >= 0
        pct_s = f'{"+" if pct >= 0 else MINUS}{abs(pct):.1f}%' if pct is not None else ""
        val = f"{_sg(usd)} ({pct_s})" if usd is not None and pct_s else (_sg(usd) if usd is not None else pct_s)
        money_html += (f'<div class="lbl" style="margin-top:6px">Result{" (approx.)" if c.get("approx") else ""}</div>'
                       f'<div class="chg {"up" if sign else "dn"}">{val}</div>')
    edge = {"RIGHT": "cu", "WRONG": "cd"}.get(cls, "cn")
    return (f'<article class="card closed {edge}"><div class="tk"><div class="sym">{e(c["ticker"])}</div>'
            f'<div class="co">{e(c["company"])}</div><div class="added">Added {e(fmt_date(c["opened"]))}</div></div>'
            f'<div class="why"><span class="chip {"sh" if "short" in c["direction"].lower() else "lg"}">{e(c["direction"])}</span>'
            f'<p>{e(c["call"])}</p></div><div class="exit"><div class="lbl">Closed</div><div class="ex">{e(fmt_date(c["closed"]))}</div>'
            f'<span class="badge {cls}">{e(word)}</span>'
            f'<div class="sm">{e(c["how"])}</div></div><div class="money">{money_html}</div></article>')


def render_page(d: dict, closed_extra=None) -> str:
    """Scorecard layout. Server-rendered from the JSON (no client script)."""
    T, B = d["totals"], d["benchmark"]
    today = _dt(d["quotes_as_of"]).date()
    open_rows = sorted((r for r in d["rows"] if r["status"] != "graded"),
                       key=lambda r: r["trade"].get("expiry") or "9999")
    closed = list(d.get("past_calls") or []) + list(_closed_extra() if closed_extra is None else closed_extra)
    spy_c = round(T["spy_value"] - sum(b["dollars"] for b in B["buys"]), 2)
    sc = max(abs(T["change"]), abs(spy_c)) or 1
    mx = max([abs(r["trade"]["change"]) for r in open_rows] or [1]) or 1
    ids = {r["id"] for r in d["rows"]}
    mv = {o: n for o, n in MOVED.items() if n in ids and o not in ids}
    moved = "".join(f'\n<details class="ev" id="{e(o)}" data-moved-to="{e(n)}" hidden></details>' for o, n in mv.items())
    cl = "".join(_closed_card(c) for c in closed) or \
        '<div class="empty">No closed positions yet. Trades move here once they are closed.</div>'
    up = lambda c: "up" if c >= 0 else "dn"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Trap Map</title>
<!-- Generated by pipeline/build_trap_map.py from site/data/trap_map.json. Do not edit by hand. -->
<style>
:root{{--bg1:#1a1a2e;--bg2:#16213e;--bg3:#0f3460;--card:rgba(255,255,255,.045);--line:rgba(255,255,255,.14);--ink:#eef2f8;--mute:#9aa7bd;--pos:#2ee59d;--neg:#ff5c6c;--acc:#00d4ff;--acc2:#7b2cbf}}
*{{box-sizing:border-box}}body{{margin:0;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);background:linear-gradient(135deg,var(--bg1),var(--bg2) 50%,var(--bg3));background-attachment:fixed;min-height:100vh}}
.wrap{{max-width:1180px;margin:0 auto;padding:28px 24px 40px}}a{{color:var(--acc)}}
.home{{font-size:13px;text-decoration:none}}h1{{margin:8px 0 2px;font-size:38px;background:linear-gradient(135deg,var(--acc),#b67cff);-webkit-background-clip:text;background-clip:text;color:transparent}}
.sub{{color:var(--mute);margin:0}}.asof{{display:inline-block;margin-top:10px;padding:4px 12px;border:1px solid var(--line);border-radius:99px;font-size:12.5px;color:var(--ink);background:rgba(0,0,0,.25)}}
.hero{{margin:22px 0 26px;padding:22px 24px;border:1px solid rgba(0,212,255,.35);border-radius:16px;background:linear-gradient(135deg,rgba(0,212,255,.10),rgba(123,44,191,.14));box-shadow:0 10px 40px rgba(0,0,0,.35)}}
.hgrid{{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:18px}}.k{{font-size:11.5px;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}}.v{{font-size:30px;font-weight:800}}.v.s{{font-size:22px;font-weight:700}}
.cmp{{margin-top:18px;display:grid;grid-template-columns:150px 1fr 110px;gap:8px 14px;align-items:center;font-size:14px}}
.verdict{{margin-top:14px;font-size:15px}}.verdict b{{color:var(--pos)}}
.gl{{position:relative;height:12px;border-radius:6px;background:rgba(255,255,255,.08);overflow:hidden}}.gl .mid{{position:absolute;left:50%;top:0;bottom:0;width:2px;background:rgba(255,255,255,.45)}}.gl i{{position:absolute;top:0;bottom:0;border-radius:6px}}.gl i.p{{background:linear-gradient(90deg,#14b87a,var(--pos))}}.gl i.n{{background:linear-gradient(90deg,var(--neg),#c9303f)}}
h2{{font-size:13px;letter-spacing:.1em;text-transform:uppercase;color:var(--mute);margin:28px 0 10px;border-bottom:1px solid var(--line);padding-bottom:6px}}
.card{{display:grid;grid-template-columns:170px 1fr 190px 200px;gap:20px;padding:18px 20px;margin-bottom:12px;border:1.5px solid rgba(255,255,255,.22);border-left:6px solid var(--pos);border-radius:12px;background:var(--card)}}.card.cd{{border-left-color:var(--neg)}}
.sym{{font-size:22px;font-weight:800;letter-spacing:.02em}}.co{{color:var(--mute);font-size:13px}}.added{{margin-top:8px;display:inline-block;font-size:12px;padding:2px 8px;border-radius:6px;background:rgba(0,212,255,.12);color:var(--acc);border:1px solid rgba(0,212,255,.3)}}
.why p{{margin:6px 0}}.sm{{font-size:12.5px;color:var(--mute)}}.sm b{{color:var(--ink)}}
.chip{{font-size:11.5px;font-weight:700;padding:2px 9px;border-radius:99px;border:1px solid}}.chip.sh{{color:#ff9aa5;border-color:rgba(255,92,108,.5);background:rgba(255,92,108,.12)}}.chip.lg{{color:#8ff3c9;border-color:rgba(46,229,157,.5);background:rgba(46,229,157,.12)}}
.ex{{font-weight:700;font-size:16px}}.prog{{height:6px;border-radius:3px;background:rgba(255,255,255,.1);margin:6px 0 4px;overflow:hidden}}.prog i{{display:block;height:100%;background:linear-gradient(90deg,var(--acc),var(--acc2))}}
.money{{text-align:right}}.lbl{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute)}}.cost{{font-size:15px}}.chg{{font-size:24px;font-weight:800;margin:0 0 6px}}.up{{color:var(--pos)}}.dn{{color:var(--neg)}}
.note{{margin-top:6px;font-size:12.5px;color:#ffd27a;border-left:3px solid #ffd27a;padding-left:8px}}.exp{{font-size:12.5px;color:var(--ink);font-weight:600}}.badge{{display:inline-block;margin:6px 0 4px;padding:3px 12px;border-radius:6px;font-weight:800;font-size:13px;letter-spacing:.06em}}.badge.RIGHT{{background:rgba(46,229,157,.18);color:var(--pos);border:1px solid var(--pos)}}.badge.WRONG{{background:rgba(255,92,108,.18);color:var(--neg);border:1px solid var(--neg)}}details.ev>summary{{display:none}}.card.closed{{opacity:.92}}.card.cn{{border-left-color:var(--mute)}}.badge.NONE{{background:rgba(255,255,255,.08);color:var(--mute);border:1px solid var(--line)}}.empty{{padding:16px 20px;border:1px dashed var(--line);border-radius:12px;color:var(--mute)}}
.how{{margin-top:26px;font-size:13px;color:var(--mute)}}.foot{{margin-top:22px;padding-top:12px;border-top:1px solid var(--line);font-size:12.5px;color:var(--mute);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}}
@media(max-width:760px){{.wrap{{padding:18px 14px}}h1{{font-size:30px}}.hgrid{{grid-template-columns:1fr 1fr}}.hgrid>div:first-child{{grid-column:1/-1}}.cmp{{grid-template-columns:90px 1fr 92px;font-size:13px}}
.card{{grid-template-columns:1fr auto;gap:10px 14px;padding:14px}}.card .tk{{grid-column:1}}.card .money{{grid-column:2;grid-row:1}}.card .why,.card .exit{{grid-column:1/-1}}.chg{{font-size:20px}}.money .gl{{width:120px;margin-left:auto}}}}
</style></head><body><div class="wrap" id="top">
<a class="home" href="index.html">\u2190 Home</a>
<h1>{e(d["title"])}</h1><p class="sub">{e(PAGE_SUBTITLE)}</p><span class="asof" id="asof">Quotes as of {e(_fmt_full(d["quotes_as_of"]))}</span>
<section class="hero" id="tot"><div class="hgrid">
<div><div class="k">Our trades are worth</div><div class="v">{money(T["value"])}</div><div class="sm">Allocated {money(T["cost"])}</div></div>
<div><div class="k">Our gain</div><div class="v s {up(T["change"])}">{_sg(T["change"])}</div></div>
<div><div class="k">Same money in the S&amp;P 500</div><div class="v s">{money(T["spy_value"])}</div><div class="sm {up(spy_c)}">{_sg(spy_c)}</div></div></div>
<div class="cmp"><div>Our trades</div>{_bar(T["change"], sc)}<div class="{up(T["change"])}" style="text-align:right;font-weight:700">{_sg(T["change"])}</div>
<div>S&amp;P 500</div>{_bar(spy_c, sc)}<div class="{up(spy_c)}" style="text-align:right;font-weight:700">{_sg(spy_c)}</div></div>
<div class="verdict sm">Each day a trade was added, the same dollars went into the S&amp;P 500 at that day's close.</div></section>
<h2>Open positions \u00b7 {len(open_rows)}</h2>{"".join(_open_card(r, today, mx) for r in open_rows)}{moved}
<h2>Closed positions \u00b7 {len(closed)}</h2>{cl}
<div class="foot"><span>This is our opinion, not advice. These are paper trades only. Prices from Yahoo Finance.</span><a href="#top">Back to top \u2191</a></div>
</div>
<script>
(function(){{var moved={json.dumps(mv)};function openLinked(){{var id=location.hash.slice(1);if(!id)return;id=moved[id]||id;
var el=document.getElementById(id);if(el){{el.open=true;el.scrollIntoView();}}}}
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
