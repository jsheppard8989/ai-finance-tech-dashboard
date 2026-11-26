#!/usr/bin/env python3
"""Build and tie out site/data/scoreboard.json (schema 2) from the paper book and quotes.

Inputs (box paths by default; tests pass fixtures):
  * newest /workspace/cos/paper_book/YYYY-MM-DD_book.json (the official paper book)
  * /workspace/cos/quotes/YYYY-MM-DD.csv three-a-day reads, plus an optional normalized
    live pull (pull_scoreboard_quotes.py --out), newest usable quote per leg wins
  * /workspace/cos/quotes/saved_legs.csv (option instrument ids per open position)
  * /workspace/cos/quotes/spy_closes.csv (SPY official daily closes, benchmark line)

What it publishes:
  * record: EVERY closed trade in the book (pre- and post-reset) and every official
    open trade, with wins/losses, win rate, realized P&L, average P&L as % of max loss
  * the STRC cash park on its own line, outside the trade record
  * one % basis on every row: P&L as % of max loss
  * per-row "mark as of" time and a stale flag (a newer NYSE session has closed with no newer quote)
  * per-row audit: leg bid/ask, quote times and the fill arithmetic
  * the $100,000 book since the Nov 15 reset vs SPY over the same dates

Marks use the closing side of the house fill rule (buys at ask - (ask-bid)/3,
sells at bid + (ask-bid)/3). Every row is tied back to the book; a row that does
not tie is HELD (left out and logged) and the build reports it. Private book notes
(decision text, owner remarks) are never exported.

Usage:
  python3 pipeline/build_scoreboard.py [--live-quotes pipeline/state/scoreboard_quotes.json]
  python3 pipeline/build_scoreboard.py --verify-only
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import market_calendar as mc  # noqa: E402
import pull_scoreboard_quotes as pq  # noqa: E402
from site_text_sanitize import find_style_gate_hits  # noqa: E402

CT = ZoneInfo("America/Chicago")
ROOT = _HERE.parent
DEFAULT_OUT = ROOT / "site" / "data" / "scoreboard.json"
DEFAULT_HELD_LOG = ROOT / "pipeline" / "state" / "scoreboard_held.log"
RESET_DATE = "2026-11-15"
BENCHMARK_BASE_DATE = "2026-11-13"  # last close before the Nov 15 reset
SCHEMA_VERSION = 2
TOL = 0.02

GRADING_RE = re.compile(r"\b(?:grade|grades|grading|graded)\b|\bA\+", re.IGNORECASE)
RETIRED_NAME_RE = re.compile(r"\btrap[\s_-]?map\b|TRAP_STRIP", re.IGNORECASE)

FILL_RULE = ("Buys fill at ask - (ask - bid)/3 and sells at bid + (ask - bid)/3. "
             "Open trades are marked on the closing side of the same rule.")

# Public write-ups per trade id. None = no public write-up yet.
WRITEUPS: dict[str, str | None] = {
    "lrcx-put": "lrcx-paid-to-wait.html",
    "mu-cycle": "mu-memory-cycle.html",
    "gev-power": "power-bottleneck.html",
    "healthcare-five": "healthcare.html",
    "ric-1123-tlt": "tlt-call-spread.html",
    "scout-1117-googl": "googl-call-spread.html",
}

# Entry quotes for pre-reset trades whose entry legs are not inside the book JSON.
# Source: /workspace/cos/paper_book/closeout_2026-11-15.md section 2 (TSAT, MU, GEV)
# and site/lrcx-paid-to-wait.html (LRCX). Each is tied to the book cost below.
PRE_RESET_ENTRY_LEGS: dict[str, dict[str, Any]] = {
    "tsat-notes": {
        "at": "Oct 29, 2026, about 1:57 PM CT", "source": "saved Yahoo bid/ask (modeled fill)",
        "contracts": 5, "legs": [("40P", "buy", 5.80, 6.60), ("30P", "sell", 3.00, 3.50)],
    },
    "mu-cycle": {
        "at": "Oct 29, 2026, 8:32 AM CT", "source": "saved Yahoo bid/ask (modeled fill)",
        "contracts": 1, "legs": [("700P", "buy", 108.0, 128.0), ("500P", "sell", 40.0, 60.0)],
    },
    "gev-power": {
        "at": "Nov 5, 2026, about 2:35 PM CT", "source": "Yahoo bid/ask (modeled fill)",
        "contracts": 1, "legs": [("860C", "buy", 42.0, 48.0), ("900C", "sell", 30.30, 34.80)],
    },
    "lrcx-put": {
        "at": "Nov 2, 2026, 11:11 AM CT", "source": "Yahoo option chain",
        "contracts": 1, "legs": [("210P", "sell", 5.00, 6.70)],
    },
}
LRCX_BUYBACK = 16.00
LRCX_STRIKE = 210.0

# Exit arithmetic for expiry closes the book records without leg quotes.
EXPIRY_EXITS: dict[str, dict[str, Any]] = {
    "asts-q3": {"long": 43.0, "short": 37.0, "right": "put", "contracts": 7, "settle": 32.60},
    "frmi-q3": {"long": 3.00, "short": 2.50, "right": "put", "contracts": 60, "settle": 2.61},
}


# --------------------------------------------------------------------------- helpers
def buy_fill(bid: float, ask: float) -> float:
    return ask - (ask - bid) / 3.0


def sell_fill(bid: float, ask: float) -> float:
    return bid + (ask - bid) / 3.0


def r2(x: float) -> float:
    return round(float(x) + 0.0, 2)


def pct(num: float, den: float) -> float | None:
    return round(100.0 * num / den, 2) if den else None


def fmt_date(iso: str | None, year_always: bool = False) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(str(iso)[:10])
    s = f"{d.strftime('%b')} {d.day}"
    return f"{s}, {d.year}" if (year_always or d.year != 2026) else s


def money(x: float) -> str:
    return f"${x:,.2f}"


def _rn(x: float, n: int) -> float:
    return round(float(x) + 0.0, n)


def _cents_equal(a: float, b: float) -> bool:
    return r2(a) == r2(b)


def choose_unit_places(price: float, dollars: float, multiplier: float) -> tuple[int, bool]:
    """2 decimals if that price × multiplier ties to dollars; else 4; else 4 + rounded."""
    dollars = r2(dollars)
    for n in (2, 4):
        if _cents_equal(_rn(price, n) * multiplier, dollars):
            return n, False
    return 4, True


def choose_net_places(fills: list[float], contracts: float, dollars: float) -> tuple[int, bool]:
    """Same rule for a debit net (first fill minus the rest) × contracts × 100."""
    dollars = r2(dollars)
    mult = float(contracts) * 100.0
    for n in (2, 4):
        shown = [_rn(f, n) for f in fills]
        net = shown[0] - sum(shown[1:])
        if _cents_equal(net * mult, dollars):
            return n, False
    return 4, True


def format_unit_price(price: float, dollars: float, multiplier: float, *, currency: bool = True) -> tuple[str, bool]:
    """Display a per-share / per-contract price. Returns (text, rounded_label)."""
    n, rounded = choose_unit_places(price, dollars, multiplier)
    p = _rn(price, n)
    text = f"${p:,.{n}f}" if currency else f"{p:.{n}f}"
    return text, rounded


def rounded_suffix(rounded: bool) -> str:
    return " (rounded)" if rounded else ""


def format_displayed_fill(fill: float) -> str:
    """The same 2-or-4 places a leg fill uses in the math row."""
    n = choose_leg_places(fill)
    return f"{_rn(fill, n):.{n}f}"


def format_share_product(shares: float, price: float, dollars: float) -> str:
    """Product uses the same displayed fill as the share leg above it."""
    shown = format_displayed_fill(price)
    rounded = not _cents_equal(float(shown) * float(shares), r2(dollars))
    return f"{int(shares)} sh × {shown} = {money(dollars)}" + rounded_suffix(rounded)


def format_option_product(fills: list[float], contracts: float, dollars: float) -> str:
    """Product operands are the displayed leg fills, not a separately rounded net."""
    texts = [format_displayed_fill(f) for f in fills]
    shown = [float(s) for s in texts]
    net = shown[0] - sum(shown[1:]) if len(shown) > 1 else shown[0]
    rounded = not _cents_equal(net * float(contracts) * 100.0, r2(dollars))
    if len(texts) == 1:
        body = f"{texts[0]} × {int(contracts)} × 100"
    else:
        body = f"({' - '.join(texts)}) × {int(contracts)} × 100"
    return f"{body} = {money(dollars)}" + rounded_suffix(rounded)


def format_single_fill_product(price: float, multiplier: float, dollars: float, *, leading: str = "") -> str:
    """e.g. 5.5667 × 100 = $556.67 or $16.00 × 100 = $1,600.00."""
    shown = format_displayed_fill(price)
    rounded = not _cents_equal(float(shown) * float(multiplier), r2(dollars))
    if leading.startswith("$"):
        body = f"{leading}{shown} × {int(multiplier)}"
    else:
        body = f"{shown} × {int(multiplier)}"
    return f"{body} = {money(dollars)}" + rounded_suffix(rounded)


def choose_leg_places(fill: float) -> int:
    """2 decimals only when the /3 fill comes out even at 2 dp; otherwise 4."""
    return 2 if _rn(fill, 4) == _rn(fill, 2) else 4


def leg_fill_math(leg: dict[str, Any]) -> str:
    """Show the bid/ask fill-rule result. Independent of the net/unit 2-or-4 tie rule."""
    bid, ask = float(leg["bid"]), float(leg["ask"])
    buy_side = str(leg.get("side") or "").lower().startswith("buy")
    raw = buy_fill(bid, ask) if buy_side else sell_fill(bid, ask)
    places = choose_leg_places(raw)
    result = f"{_rn(raw, places):.{places}f}"
    if buy_side:
        return f"{ask:.2f} - ({ask:.2f} - {bid:.2f})/3 = {result}"
    return f"{bid:.2f} + ({ask:.2f} - {bid:.2f})/3 = {result}"


def apply_leg_math(legs: list[dict[str, Any]]) -> None:
    for leg in legs:
        if "bid" in leg and "ask" in leg and "fill" in leg:
            leg["math"] = leg_fill_math(leg)

def _structure_label(pos: dict[str, Any]) -> str:
    s = str(pos.get("name") or pos.get("structure") or pos.get("ticker") or "")
    if pos.get("contracts") and f"x{pos['contracts']}" not in s and f"×{pos['contracts']}" not in s:
        s = f"{s} ×{pos['contracts']}"
    return s.replace(" x", " ×") if re.search(r" x\d", s) else s


def _parse_leg_label(label: str) -> tuple[float | None, str | None]:
    m = re.match(r"^\s*(\d+(?:\.\d+)?)\s*([CP])\s*$", str(label), re.I)
    if not m:
        return None, None
    return float(m.group(1)), ("call" if m.group(2).upper() == "C" else "put")


def _leg_instrument_id(pos: dict[str, Any], label: str, info: dict[str, Any], saved_legs: list[dict[str, str]]) -> str:
    uid = str(info.get("instrument_id") or "").strip()
    if uid:
        return uid
    strike, right = _parse_leg_label(label)
    if strike is None:
        return ""
    k = f"${int(strike)}" if float(strike).is_integer() else f"${strike}"
    for row in saved_legs:
        if str(row.get("position_id") or "") != str(pos.get("id") or ""):
            continue
        desc = str(row.get("leg_description") or "").lower()
        if f"{k} {right}".lower() in desc:
            return str(row.get("instrument_id") or "").strip()
    return ""


def _scan_wording(obj: Any, path: str) -> list[str]:
    out = [f"'bet' wording at {path}{p}: {s}" for p, s in find_style_gate_hits(obj)]

    def walk(node: Any, cur: str) -> None:
        if isinstance(node, str):
            if GRADING_RE.search(node):
                out.append(f"grading wording at {cur}: {node!r}")
            if RETIRED_NAME_RE.search(node):
                out.append(f"retired name at {cur}: {node!r}")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{cur}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{cur}[{i}]")

    walk(obj, path)
    return out


def _freshness(ts: datetime | None, now: datetime, kind: str = "share") -> dict[str, Any]:
    """Session-based freshness: stale once a regular session newer than the mark's has closed."""
    if ts is None:
        return {"mark_time_ct": None, "mark_label": "no quote", "stale_after_ct": None,
                "is_stale": True, "mark_kind": kind}
    sa = mc.stale_after(ts, kind)
    stale = mc.is_stale(ts, now, kind)
    assert stale == (now > sa), "calendar stale rule and stale_after disagree"
    return {
        "mark_time_ct": ts.isoformat(timespec="seconds"),
        "mark_label": pq.format_ct_label(ts),
        "stale_after_ct": sa.isoformat(timespec="seconds"),
        "stale_after_label": pq.format_ct_label(sa),
        "is_stale": stale,
        "mark_kind": kind,
    }


# --------------------------------------------------------------------------- open rows
def _mark_open_position(
    pos: dict[str, Any], quotes: dict[str, Any], saved_legs: list[dict[str, str]]
) -> tuple[dict[str, Any] | None, list[str]]:
    """Closing-side mark for one open position. Returns (mark dict, errors)."""
    errs: list[str] = []
    eqq = quotes.get("equity") or {}
    opq = quotes.get("options") or {}
    pid = str(pos.get("id") or "")
    if pos.get("shares"):
        sym = str(pos.get("ticker") or "").upper()
        q = eqq.get(sym)
        if not q or pq.quote_problems(sym, q):
            return None, [f"{pid}: no usable regular-session quote for {sym}"]
        mark = sell_fill(q["bid"], q["ask"])
        shares = float(pos["shares"])
        ts = pq.parse_ct_timestamp(q.get("quote_time_ct"))
        value = r2(shares * mark)
        n, _ = choose_unit_places(mark, value, shares)
        legs = [{
            "leg": f"{sym} shares", "side": "sell to close", "bid": q["bid"], "ask": q["ask"],
            "quote_time_ct": q.get("quote_time_ct"), "quote_label": pq.format_ct_label(ts),
            "fill": round(mark, 6),
            "source": q.get("source"),
        }]
        apply_leg_math(legs)
        return {
            "per_unit": round(mark, 6),
            "value": value,
            "time": ts,
            "legs": legs,
            "math": format_share_product(shares, mark, value),
        }, []
    legs = pos.get("legs") or {}
    contracts = float(pos.get("contracts") or 0)
    net = 0.0
    out_legs, times = [], []
    for label, info in legs.items():
        uid = _leg_instrument_id(pos, label, info, saved_legs)
        q = opq.get(uid) if uid else None
        if not q or pq.quote_problems(label, q):
            errs.append(f"{pid} {label}: no usable regular-session quote")
            continue
        is_long = str(info.get("side") or "buy").lower() == "buy"
        f = sell_fill(q["bid"], q["ask"]) if is_long else buy_fill(q["bid"], q["ask"])
        net += f if is_long else -f
        ts = pq.parse_ct_timestamp(q.get("quote_time_ct"))
        times.append(ts)
        out_legs.append({
            "leg": label, "side": "sell to close" if is_long else "buy to close",
            "bid": q["bid"], "ask": q["ask"], "quote_time_ct": q.get("quote_time_ct"),
            "quote_label": pq.format_ct_label(ts), "fill": round(f, 6),
            "math": (f"{q['bid']:.2f} + ({q['ask']:.2f} - {q['bid']:.2f})/3 = {f:.4f}" if is_long
                     else f"{q['ask']:.2f} - ({q['ask']:.2f} - {q['bid']:.2f})/3 = {f:.4f}"),
            "source": q.get("source"),
        })
    if errs or not out_legs or contracts <= 0:
        return None, errs or [f"{pid}: no legs to mark"]
    value = r2(net * contracts * 100.0)
    fills = [float(l["fill"]) for l in out_legs]
    n, _ = choose_net_places(fills, contracts, value)
    apply_leg_math(out_legs)
    return {
        "per_unit": round(net, 6),
        "value": value,
        "time": min(times),  # a spread is only as fresh as its oldest leg
        "legs": out_legs,
        "math": format_option_product(fills, contracts, value),
    }, []


def _entry_audit_open(pos: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    errs: list[str] = []
    pid = str(pos.get("id") or "")
    entry_ts = pq.parse_ct_timestamp(pos.get("quote_at_ct") or pos.get("quote_bid_ask_at") or pos.get("opened_at_ct"))
    if pos.get("shares"):
        bid, ask = float(pos["bid"]), float(pos["ask"])
        f = buy_fill(bid, ask)
        shares = float(pos["shares"])
        cost = r2(shares * f)
        if abs(float(pos.get("fill") or f) - f) > 0.001:
            errs.append(f"{pid}: entry fill {pos.get('fill')} != {f:.6f}")
        if abs(cost - float(pos["cost"])) > TOL:
            errs.append(f"{pid}: cost {pos['cost']} != {cost}")
        n, _ = choose_unit_places(f, cost, shares)
        legs = [{"leg": f"{pos.get('ticker')} shares", "side": "buy", "bid": bid, "ask": ask,
                 "fill": round(f, 6)}]
        apply_leg_math(legs)
        return {
            "at_label": pq.format_ct_label(entry_ts),
            "legs": legs,
            "math": format_share_product(shares, f, cost),
            "source": "Robinhood read-only quote",
        }, errs
    contracts = float(pos.get("contracts") or 0)
    net = 0.0
    legs = []
    for label, info in (pos.get("legs") or {}).items():
        bid, ask = float(info["bid"]), float(info["ask"])
        is_buy = str(info.get("side") or "buy").lower() == "buy"
        f = buy_fill(bid, ask) if is_buy else sell_fill(bid, ask)
        if info.get("fill") is not None and abs(float(info["fill"]) - f) > 0.001:
            errs.append(f"{pid} {label}: entry fill {info['fill']} != {f:.6f}")
        net += f if is_buy else -f
        legs.append({"leg": label, "side": "buy" if is_buy else "sell", "bid": bid, "ask": ask,
                     "fill": round(f, 6)})
    cost = r2(net * contracts * 100.0)
    fills = [float(l["fill"]) for l in legs]
    n, _ = choose_net_places(fills, contracts, cost)
    apply_leg_math(legs)
    if abs(cost - float(pos["cost"])) > TOL:
        errs.append(f"{pid}: cost {pos['cost']} != {cost}")
    if pos.get("max_loss") is not None and abs(float(pos["max_loss"]) - cost) > TOL:
        errs.append(f"{pid}: max_loss {pos['max_loss']} != {cost}")
    if pos.get("debit_per_spread") is not None and abs(float(pos["debit_per_spread"]) - net) > 0.001:
        errs.append(f"{pid}: debit {pos['debit_per_spread']} != {net:.6f}")
    strikes = [(_parse_leg_label(l)[0], i) for l, i in (pos.get("legs") or {}).items()]
    longs = [k for k, i in strikes if str(i.get("side")).lower() == "buy" and k is not None]
    shorts = [k for k, i in strikes if str(i.get("side")).lower() != "buy" and k is not None]
    if pos.get("max_gain") is not None and longs and shorts:
        width = abs(shorts[0] - longs[0])
        mg = r2((width - net) * contracts * 100.0)
        if abs(mg - float(pos["max_gain"])) > TOL:
            errs.append(f"{pid}: max_gain {pos['max_gain']} != {mg}")
    return {
        "at_label": pq.format_ct_label(entry_ts),
        "legs": legs,
        "math": format_option_product(fills, contracts, cost),
        "source": "Robinhood read-only quote",
    }, errs


def _open_row(pos: dict[str, Any], quotes: dict[str, Any], saved_legs: list[dict[str, str]], now: datetime) -> tuple[dict[str, Any] | None, list[str]]:
    pid = str(pos.get("id") or "")
    entry, errs = _entry_audit_open(pos)
    mark, merrs = _mark_open_position(pos, quotes, saved_legs)
    if errs:
        return None, errs
    cost = r2(pos["cost"])
    max_loss = r2(pos.get("max_loss") if pos.get("max_loss") is not None else cost)
    is_park = pid == "strc-park" or (bool(pos.get("shares")) and not pos.get("official_weekly_trade"))
    if mark is None:
        return None, merrs
    pnl = r2(mark["value"] - cost)
    fresh = _freshness(mark["time"], now, "share" if pos.get("shares") else "option")
    if pos.get("shares"):
        shares = float(pos["shares"])
        entry_p, entry_r = format_unit_price(float(pos["fill"]), cost, shares)
        mark_p, mark_r = format_unit_price(mark["per_unit"], mark["value"], shares)
        entry_text = f"{int(shares)} sh at {entry_p}" + rounded_suffix(entry_r)
        mark_text = mark_p + rounded_suffix(mark_r)
    else:
        contracts = float(pos.get("contracts") or 0)
        mult = contracts * 100.0
        entry_p, entry_r = format_unit_price(float(pos["debit_per_spread"]), cost, mult)
        mark_p, mark_r = format_unit_price(mark["per_unit"], mark["value"], mult)
        entry_text = f"{entry_p} debit" + rounded_suffix(entry_r)
        mark_text = mark_p + rounded_suffix(mark_r)
    row = {
        "id": pid,
        "ticker": str(pos.get("ticker") or "").upper(),
        "owner": pos.get("owner"),
        "structure": _structure_label(pos),
        "is_cash_park": is_park,
        "opened": str(pos.get("opened") or ""),
        "opened_label": fmt_date(pos.get("opened")),
        "expiry": pos.get("expiry"),
        "expiry_label": fmt_date(pos.get("expiry"), year_always=True) if pos.get("expiry") else "",
        "entry_text": entry_text,
        "cost": cost,
        "max_loss": max_loss,
        "max_gain": pos.get("max_gain"),
        "breakeven": round(float(pos["breakeven"]), 2) if pos.get("breakeven") is not None else None,
        "wrong_if": (str(pos.get("proved_wrong")).strip() if pos.get("proved_wrong") else
                     (f"{str(pos.get('ticker')).upper()} closes at or below {money(float(pos['breakeven']))} on "
                      f"{fmt_date(pos.get('expiry'), True)} (held to expiry)" if pos.get("breakeven") and pos.get("expiry")
                      else None)),
        "mark_text": mark_text,
        "mark_per_unit": mark["per_unit"],
        "value": mark["value"],
        "pnl": pnl,
        "pnl_pct_max_loss": pct(pnl, max_loss),
        **fresh,
        "writeup_url": WRITEUPS.get(pid),
        "audit": {"entry": entry, "mark": {"legs": mark["legs"], "math": mark["math"],
                                           "pnl_math": f"{money(mark['value'])} - {money(cost)} = {money(pnl) if pnl >= 0 else '-' + money(-pnl)}; "
                                                       f"{'+' if pnl >= 0 else ''}{pct(pnl, max_loss):.2f}% of {money(max_loss)} max loss"}},
    }
    if is_park:
        row["park_rule"] = ("Cash parked in STRC between official trades. It is sold only when a new approved trade "
                            "needs more than the cash on hand, in the 9:00 to 11:00 AM CT window, or when we decide to flatten it.")
    return row, []


# --------------------------------------------------------------------------- closed rows
def _closed_max_loss(pos: dict[str, Any]) -> tuple[float, str]:
    pid = str(pos.get("id") or "")
    if pos.get("max_loss") is not None:
        return r2(pos["max_loss"]), "book max loss"
    if pid == "lrcx-put":
        credit = r2(sell_fill(5.00, 6.70) * 100.0)
        return r2(LRCX_STRIKE * 100.0 - credit), f"$21,000.00 collateral - {money(credit)} credit"
    structure = str(pos.get("structure") or "").lower()
    if "debit" in structure or "long basket" in structure:
        return r2(pos["cost"]), "debit paid (cost)"
    raise ValueError(f"{pid}: cannot derive max loss from structure {structure!r}")


def _closed_status(exit_text: str) -> str:
    t = exit_text.lower()
    if t.startswith("stop"):
        return "Closed at stop"
    if t.startswith("expiry"):
        return "Closed at expiry"
    if "fair close" in t:
        return "Closed at reset"
    return "Closed"


def _closed_audit(pos: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    pid = str(pos.get("id") or "")
    errs: list[str] = []
    audit: dict[str, Any] = {"entry": None, "exit": None}
    cost = r2(pos["cost"])
    spec = PRE_RESET_ENTRY_LEGS.get(pid)
    if spec:
        net, legs = 0.0, []
        for label, side, bid, ask in spec["legs"]:
            f = buy_fill(bid, ask) if side == "buy" else sell_fill(bid, ask)
            net += f if side == "buy" else -f
            legs.append({"leg": label, "side": side, "bid": bid, "ask": ask, "fill": round(f, 6)})
        total = r2(net * spec["contracts"] * 100.0)
        if pid == "lrcx-put":
            credit = -total
            if abs(credit - 556.67) > TOL:
                errs.append(f"{pid}: entry credit {credit} != 556.67")
            n, _ = choose_unit_places(-net, credit, 100.0)
            apply_leg_math(legs)
            math = format_single_fill_product(-net, 100.0, credit) + f" credit on {money(cost)} cash collateral"
        else:
            if abs(total - cost) > TOL:
                errs.append(f"{pid}: entry legs give {total}, book cost {cost}")
            fills = [float(l["fill"]) for l in legs]
            n, _ = choose_net_places(fills, spec["contracts"], total)
            apply_leg_math(legs)
            math = format_option_product(fills, spec["contracts"], total)
        audit["entry"] = {"at_label": spec["at"], "source": spec["source"], "legs": legs, "math": math}
    else:
        audit["entry"] = {"at_label": fmt_date(pos.get("opened"), True), "source": "modeled fill",
                          "legs": [], "math": f"Cost {money(cost)}. The book records this entry as a modeled fill without leg bid/ask."}

    exit_val = r2(pos["exit_value"])
    if pos.get("legs_quote") and pos.get("fill_per_share"):
        legs = []
        net = 0.0
        contracts = int(re.search(r"x(\d+)", str(pos.get("structure"))).group(1))
        for label, (bid, ask) in pos["legs_quote"].items():
            key_sell = f"{label}_sell"
            is_long = key_sell in pos["fill_per_share"]
            f = sell_fill(bid, ask) if is_long else buy_fill(bid, ask)
            net += f if is_long else -f
            legs.append({"leg": label, "side": "sell to close" if is_long else "buy to close", "bid": bid, "ask": ask,
                         "fill": round(f, 6)})
        total = r2(net * contracts * 100.0)
        if abs(total - exit_val) > TOL:
            errs.append(f"{pid}: exit legs give {total}, book exit {exit_val}")
        fills = [float(l["fill"]) for l in legs]
        n, _ = choose_net_places(fills, contracts, total)
        apply_leg_math(legs)
        audit["exit"] = {"at_label": "Fri Nov 13, 2026, 2:59:59 PM CT (last regular-session bid/ask)",
                         "source": "Robinhood read-only quote", "legs": legs,
                         "math": format_option_product(fills, contracts, total)}
    elif pid in EXPIRY_EXITS:
        e = EXPIRY_EXITS[pid]
        long_k, short_k, s = e["long"], e["short"], e["settle"]
        per = max(0.0, long_k - s) - max(0.0, short_k - s)
        total = r2(per * e["contracts"] * 100.0)
        if abs(total - exit_val) > TOL:
            errs.append(f"{pid}: expiry value {total} != book exit {exit_val}")
        n, rounded = choose_unit_places(per, total, e["contracts"] * 100.0)
        worth = f"${_rn(per, n):.{n}f}"
        audit["exit"] = {"at_label": fmt_date(pos.get("closed"), True) + " expiry", "source": "official close",
                         "legs": [],
                         "math": (f"Close ${s:.2f}: {_k(long_k, short_k)}/{_k(short_k, long_k)} put spread worth "
                                  f"{worth} × {e['contracts']} × 100 = {money(total)}" + rounded_suffix(rounded))}
    elif pid == "lrcx-put":
        total = r2(LRCX_BUYBACK * 100.0)
        realized = r2(556.67 - total)
        if abs(realized - float(pos["realized"])) > TOL:
            errs.append(f"{pid}: realized {pos['realized']} != {realized}")
        buyback = format_single_fill_product(LRCX_BUYBACK, 100.0, total, leading="$")
        audit["exit"] = {"at_label": "Nov 5, 2026 (stop)", "source": "owner-stated paper fill", "legs": [],
                         "math": f"Bought back at {buyback}; $556.67 credit - $1,600.00 = {money(realized) if realized >= 0 else '-' + money(-realized)}"}
    else:
        audit["exit"] = {"at_label": fmt_date(pos.get("closed"), True), "source": str(pos.get("price_type") or ""),
                         "legs": [], "math": f"Exit value {money(exit_val)} ({pos.get('price_type')})."}
    return audit, errs


def _k(x: float, other: float | None = None) -> str:
    whole = float(x).is_integer() and (other is None or float(other).is_integer())
    return f"{x:g}" if whole else f"{x:.2f}"


def _closed_row(pos: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    pid = str(pos.get("id") or "")
    errs: list[str] = []
    cost, exit_val, realized = r2(pos["cost"]), r2(pos["exit_value"]), r2(pos["realized"])
    if abs((exit_val - cost) - realized) > TOL:
        errs.append(f"{pid}: exit {exit_val} - cost {cost} != realized {realized}")
    try:
        max_loss, ml_basis = _closed_max_loss(pos)
    except ValueError as e:
        return None, [str(e)]
    audit, aerrs = _closed_audit(pos)
    errs.extend(aerrs)
    if errs:
        return None, errs
    closed_iso = str(pos.get("closed") or "")
    return {
        "id": pid,
        "ticker": str(pos.get("ticker") or "").upper(),
        "owner": pos.get("owner"),
        "structure": str(pos.get("structure") or "").replace(" x", " ×"),
        "pre_reset": closed_iso <= RESET_DATE,
        "opened": str(pos.get("opened") or ""),
        "opened_label": fmt_date(pos.get("opened")),
        "closed": closed_iso,
        "closed_label": fmt_date(closed_iso),
        "status_label": _closed_status(str(pos.get("exit") or "")),
        "how_closed": str(pos.get("exit") or ""),
        "exit_basis": str(pos.get("price_type") or ""),
        "owner_stated": "owner-stated" in str(pos.get("price_type") or ""),
        "cost": cost,
        "max_loss": max_loss,
        "max_loss_basis": ml_basis,
        "exit_value": exit_val,
        "pnl": realized,
        "pnl_pct_max_loss": pct(realized, max_loss),
        "writeup_url": WRITEUPS.get(pid),
        "audit": audit,
    }, []


# --------------------------------------------------------------------------- curve
def build_equity_curve(
    book: dict[str, Any],
    history: list[dict[str, Any]],
    saved_legs: list[dict[str, str]],
    spy_closes: dict[str, float],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Book value at each session's last complete read vs $100,000 in SPY at the reset."""
    start_cash = float((book.get("book") or {}).get("starting_cash") or 100000.0)
    base = spy_closes.get(BENCHMARK_BASE_DATE)
    positions = [p for p in book.get("open") or []]
    by_read: dict[str, list[dict[str, Any]]] = {}
    for rec in history:
        key = rec.get("read_time_ct") or rec.get("quote_time_ct")
        if key:
            by_read.setdefault(key, []).append(rec)
    points: dict[str, dict[str, Any]] = {}
    gaps: list[str] = []
    for read_key in sorted(by_read):
        recs = by_read[read_key]
        read_ts = pq.parse_ct_timestamp(read_key)
        usable = [r for r in recs if not pq.quote_problems("x", r)]
        if not usable:
            continue
        days = {pq.parse_ct_timestamp(r["quote_time_ct"]).date() for r in usable}
        if len(days) != 1:
            continue
        d = days.pop()
        if d.isoformat() <= RESET_DATE:
            continue
        quotes = {"equity": {}, "options": {}}
        for r in usable:
            if r.get("instrument_id"):
                quotes["options"][r["instrument_id"]] = r
            elif r.get("symbol"):
                quotes["equity"][r["symbol"]] = r
        held = [p for p in positions if pq.parse_ct_timestamp(p.get("opened_at_ct")) and
                pq.parse_ct_timestamp(p.get("opened_at_ct")) <= read_ts]
        cash = start_cash - sum(float(p["cost"]) for p in held)
        value = cash
        ok = True
        for p in held:
            m, e = _mark_open_position(p, quotes, saved_legs)
            if m is None:
                ok = False
                break
            value += m["value"]
        if not ok:
            continue
        points[d.isoformat()] = {"date": d.isoformat(), "label": fmt_date(d.isoformat()),
                                 "read_label": pq.format_ct_label(read_ts), "book_value": r2(value)}
    out_points = []
    for d in sorted(points):
        p = points[d]
        c = spy_closes.get(d)
        if base and c:
            p["spy_close"] = c
            p["spy_value"] = r2(start_cash * c / base)
            out_points.append(p)
        else:
            gaps.append(f"{d}: no SPY close")
    # Trading days since the reset with no complete read.
    if out_points:
        d = date.fromisoformat("2026-11-16")
        now_l = (now or datetime.now(CT)).astimezone(CT)
        last = now_l.date() if (mc.is_trading_day(now_l.date()) and now_l >= mc.session_close(now_l.date())) \
            else mc.previous_trading_day(now_l.date())
        while d <= last:
            if mc.is_trading_day(d) and d.isoformat() not in points:
                gaps.append(f"{fmt_date(d.isoformat())}: no complete regular-session read")
            d = mc.next_trading_day(d)
    first = {"date": RESET_DATE, "label": "Nov 15 reset", "book_value": r2(start_cash),
             "spy_value": r2(start_cash) if base else None, "spy_close": base,
             "read_label": f"SPY close Fri Nov 13 ({base})" if base else ""}
    return {
        "base_date": BENCHMARK_BASE_DATE,
        "base_spy_close": base,
        "note": ("Book: $100,000 paper book since the Nov 15 reset, including the STRC cash park, valued at each "
                 "session's last complete quote read with the closing-side fill rule. SPY: $100,000 at the Nov 13 "
                 "official close, valued at each official daily close."),
        "points": [first] + out_points,
        "gaps": gaps,
    }


# --------------------------------------------------------------------------- build
def build_scoreboard(
    book: dict[str, Any],
    quotes: dict[str, Any],
    saved_legs: list[dict[str, str]] | None = None,
    history: list[dict[str, Any]] | None = None,
    spy_closes: dict[str, float] | None = None,
    now_ct: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    now = (now_ct or datetime.now(CT)).astimezone(CT)
    saved_legs = saved_legs or []
    held: list[dict[str, str]] = []

    open_rows, park_rows = [], []
    for pos in book.get("open") or []:
        row, errs = _open_row(pos, quotes, saved_legs, now)
        errs += _scan_wording(row, pos.get("id", "?")) if row else []
        if errs or row is None:
            held.append({"id": str(pos.get("id")), "ticker": str(pos.get("ticker")), "reason": "; ".join(errs)})
            continue
        (park_rows if row["is_cash_park"] else open_rows).append(row)
    open_rows.sort(key=lambda r: r["opened"], reverse=True)

    closed_rows = []
    for pos in book.get("closed") or []:
        row, errs = _closed_row(pos)
        errs += _scan_wording(row, pos.get("id", "?")) if row else []
        if errs or row is None:
            held.append({"id": str(pos.get("id")), "ticker": str(pos.get("ticker")), "reason": "; ".join(errs)})
            continue
        closed_rows.append(row)
    closed_rows.sort(key=lambda r: (r["closed"], r["opened"]), reverse=True)

    # ---- record (official trades only; the park is excluded)
    wins = [r for r in closed_rows if r["pnl"] > 0]
    losses = [r for r in closed_rows if r["pnl"] <= 0]
    realized = r2(sum(r["pnl"] for r in closed_rows))
    avg_pct = round(sum(r["pnl_pct_max_loss"] for r in closed_rows) / len(closed_rows), 2) if closed_rows else None
    open_pnl = r2(sum(r["pnl"] for r in open_rows))
    open_ml = r2(sum(r["max_loss"] for r in open_rows))
    # Headline freshness follows the open row that goes stale first.
    dated = [r for r in open_rows if r.get("mark_time_ct")]
    first = min(dated, key=lambda r: (pq.parse_ct_timestamp(r["stale_after_ct"]), pq.parse_ct_timestamp(r["mark_time_ct"]))) if dated else None
    record_fresh = _freshness(pq.parse_ct_timestamp(first["mark_time_ct"]) if first else None, now,
                              first.get("mark_kind", "option") if first else "option")

    # ---- book (since reset)
    meta = book.get("book") or {}
    start_cash = r2(meta.get("starting_cash") or 100000.0)
    cash = r2(meta.get("cash") or 0.0)
    post_reset_realized = r2(sum(r["pnl"] for r in closed_rows if not r["pre_reset"]))
    all_open = open_rows + park_rows
    open_value = r2(sum(r["value"] for r in all_open))
    open_cost = r2(sum(r["cost"] for r in all_open))
    book_value = r2(cash + open_value)
    park_pnl = r2(sum(r["pnl"] for r in park_rows))
    total_pnl = r2(book_value - start_cash)

    # ---- tie-outs against the book (only meaningful when nothing was held)
    if not held:
        wl = book.get("wins_losses") or {}
        if wl and (len(wins) != int(wl.get("closed_wins", -1)) or len(losses) != int(wl.get("closed_losses", -1))):
            held.append({"id": "_record", "ticker": "BOOK",
                         "reason": f"wins/losses {len(wins)}/{len(losses)} != book {wl.get('closed_wins')}/{wl.get('closed_losses')}"})
        prior = book.get("prior_book_inception_realized_pnl")
        pre_realized = r2(sum(r["pnl"] for r in closed_rows if r["pre_reset"]))
        if prior is not None and abs(pre_realized - float(prior)) > TOL:
            held.append({"id": "_record", "ticker": "BOOK", "reason": f"pre-reset realized {pre_realized} != book {prior}"})
        if abs((cash + open_cost) - (start_cash + post_reset_realized)) > 0.05:
            held.append({"id": "_book", "ticker": "BOOK",
                         "reason": f"cash {cash} + open cost {open_cost} != start {start_cash} + realized {post_reset_realized}"})
        if abs(total_pnl - r2(open_value - open_cost + post_reset_realized)) > 0.05:
            held.append({"id": "_book", "ticker": "BOOK", "reason": "book P&L does not tie to rows"})

    curve = build_equity_curve(book, history or [], saved_legs, spy_closes or {}, now)

    scoreboard = {
        "schema_version": SCHEMA_VERSION,
        "paper_only": True,
        "generated_at_ct": now.isoformat(timespec="seconds"),
        "generated_at_label": pq.format_ct_label(now),
        "book_as_of_ct": book.get("as_of_ct"),
        "reset_date": RESET_DATE,
        "fill_rule": FILL_RULE,
        "stale_rule": "A mark turns red once a regular session newer than the mark's has closed with no newer quote: NYSE trading days only (weekends and full holidays skipped), closes at 3:15 PM CT for options and 3:00 PM CT for shares, 12:15 / 12:00 PM CT on half days.",
        "record": {
            "closed_count": len(closed_rows),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate_pct": pct(len(wins), len(closed_rows)),
            "realized_pnl": realized,
            "avg_pnl_pct_max_loss": avg_pct,
            "first_opened": min((r["opened"] for r in closed_rows), default=None),
            "closed_since_reset_count": len([r for r in closed_rows if not r["pre_reset"]]),
            "open_count": len(open_rows),
            "open_pnl": open_pnl,
            "open_max_loss": open_ml,
            "open_pnl_pct_max_loss": pct(open_pnl, open_ml),
            **{f"open_{k}": v for k, v in record_fresh.items()},
        },
        "book": {
            "starting_cash": start_cash,
            "cash": cash,
            "open_value": open_value,
            "book_value": book_value,
            "total_pnl": total_pnl,
            "total_return_pct": pct(total_pnl, start_cash),
            "trades_pnl": r2(open_pnl + post_reset_realized),
            "park_pnl": park_pnl,
        },
        "cash_park": park_rows[0] if park_rows else None,
        "open": open_rows,
        "closed": closed_rows,
        "equity_curve": curve,
        "held_count": len(held),
    }
    errs = _scan_wording(scoreboard, "scoreboard")
    if errs:
        raise ValueError("Scoreboard failed wording check: " + "; ".join(errs))
    return scoreboard, held


def verify_existing_scoreboard(sb: dict[str, Any], book: dict[str, Any]) -> list[str]:
    """Re-tie a written scoreboard.json against the book (no quotes needed)."""
    errs = _scan_wording(sb, "scoreboard")
    closed_book = {str(p.get("id")): p for p in book.get("closed") or []}
    open_book = {str(p.get("id")): p for p in book.get("open") or []}
    ids = {r["id"] for r in sb.get("closed") or []}
    missing = set(closed_book) - ids
    if missing:
        errs.append(f"closed trades missing from scoreboard: {sorted(missing)}")
    for r in sb.get("closed") or []:
        p = closed_book.get(r["id"])
        if not p:
            errs.append(f"{r['id']}: not in book")
            continue
        if abs(r["pnl"] - float(p["realized"])) > TOL or abs(r["cost"] - float(p["cost"])) > TOL:
            errs.append(f"{r['id']}: cost/realized differ from book")
        if abs(r["pnl_pct_max_loss"] - 100.0 * r["pnl"] / r["max_loss"]) > 0.01:
            errs.append(f"{r['id']}: % of max loss does not tie")
    rows = (sb.get("open") or []) + ([sb["cash_park"]] if sb.get("cash_park") else [])
    for r in rows:
        p = open_book.get(r["id"])
        if not p:
            errs.append(f"{r['id']}: open row not in book")
            continue
        if abs(r["cost"] - float(p["cost"])) > TOL:
            errs.append(f"{r['id']}: cost differs from book")
        if abs(r["pnl"] - (r["value"] - r["cost"])) > TOL:
            errs.append(f"{r['id']}: pnl != value - cost")
    rec, bk = sb.get("record") or {}, sb.get("book") or {}
    if abs(rec.get("realized_pnl", 0) - sum(r["pnl"] for r in sb.get("closed") or [])) > TOL:
        errs.append("record realized != sum of closed rows")
    if abs(bk.get("book_value", 0) - (bk.get("cash", 0) + bk.get("open_value", 0))) > TOL:
        errs.append("book value != cash + open value")
    if "Today's" in json.dumps(sb):
        errs.append("'Today's' label present")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build & tie out site/data/scoreboard.json.")
    ap.add_argument("--book", type=Path, default=None)
    ap.add_argument("--quotes-dir", type=Path, default=pq.COS_QUOTES_DIR)
    ap.add_argument("--live-quotes", type=Path, default=None, help="normalized JSON from pull_scoreboard_quotes.py")
    ap.add_argument("--saved-legs", type=Path, default=None)
    ap.add_argument("--spy-closes", type=Path, default=None)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--held-log", type=Path, default=DEFAULT_HELD_LOG)
    ap.add_argument("--now", default=None, help="ISO time to build as of (tests)")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any row is held")
    args = ap.parse_args(argv)

    book_path = pq.resolve_book_path(args.book)
    if not book_path.is_file():
        print(f"ERROR: paper book not found: {book_path}", file=sys.stderr)
        return 1
    book = json.loads(book_path.read_text(encoding="utf-8"))
    if args.verify_only:
        sb = json.loads(args.out.read_text(encoding="utf-8"))
        errs = verify_existing_scoreboard(sb, book)
        for e in errs:
            print(f"TIE-OUT FAIL: {e}", file=sys.stderr)
        if not errs:
            print(f"Scoreboard tie-out OK: {len(sb['open'])} open, {len(sb['closed'])} closed, book {money(sb['book']['book_value'])}")
        return 1 if errs else 0

    now = pq.parse_ct_timestamp(args.now) if args.now else datetime.now(CT)
    saved = pq.load_saved_legs(args.saved_legs or (args.quotes_dir / "saved_legs.csv"))
    if args.live_quotes and args.live_quotes.is_file():
        quotes = json.loads(args.live_quotes.read_text(encoding="utf-8"))
    else:
        quotes = pq.normalize_quotes(book, quotes_dir=args.quotes_dir, now=now, saved_legs=saved)
    history = pq.load_csv_history(args.quotes_dir)
    spy = pq.load_closes(args.spy_closes or (args.quotes_dir / "spy_closes.csv"))
    sb, held = build_scoreboard(book, quotes, saved, history, spy, now)
    if held:
        args.held_log.parent.mkdir(parents=True, exist_ok=True)
        with args.held_log.open("a", encoding="utf-8") as f:
            for h in held:
                f.write(json.dumps({"at_ct": now.isoformat(timespec="seconds"), **h}) + "\n")
                print(f"HELD {h['id']} ({h['ticker']}): {h['reason']}", file=sys.stderr)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(sb, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(args.out)
    rec, bk = sb["record"], sb["book"]
    print(f"Wrote {args.out}: closed {rec['closed_count']} ({rec['wins']}W/{rec['losses']}L), "
          f"realized {money(rec['realized_pnl'])}, open {rec['open_count']} P&L {rec['open_pnl']:+,.2f}, "
          f"book {money(bk['book_value'])}, held {len(held)}, mark as of {rec['open_mark_label']}")
    return 1 if (args.strict and held) else 0


if __name__ == "__main__":
    raise SystemExit(main())
