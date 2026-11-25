#!/usr/bin/env python3
"""Build and tie-out site/data/scoreboard.json from the newest paper_book JSON and quotes.

Reads:
  - Newest dated /workspace/cos/paper_book/YYYY-MM-DD_book.json (or pipeline/state/paper_book.json)
  - Normalized quotes JSON (pipeline/state/scoreboard_quotes.json) from read-only Robinhood MCP
    pulls, falling back cleanly to saved_legs.csv / YYYY-MM-DD.csv quotes with explicit quote times.

Includes:
  - Every open and closed paper trade since the Nov 15, 2026 $100,000 reset
  - Plus LRCX (lrcx-put, closed Nov 5, 2026 at stop, realized -$1,043.33) per owner directive

Marks open positions on the closing side (a third of the spread from the worst price):
  - Long shares / long option legs: sell at bid + (ask - bid) / 3
  - Short option legs: buy back at ask - (ask - bid) / 3

Auto-closes open positions at expiry, stop, or target.
Enforces strict tie-out and copy gates ('bet' wording, grading words, retired naming).
Any row that fails tie-out or wording checks is held (omitted from output, logged) while valid rows ship.

Usage:
  python3 pipeline/build_scoreboard.py
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

import pull_scoreboard_quotes as pq  # noqa: E402
from site_text_sanitize import find_style_gate_hits  # noqa: E402

CT = ZoneInfo("America/Chicago")
ROOT = _HERE.parent
DEFAULT_OUT = ROOT / "site" / "data" / "scoreboard.json"
DEFAULT_QUOTES = ROOT / "pipeline" / "state" / "scoreboard_quotes.json"
DEFAULT_HELD_LOG = ROOT / "pipeline" / "state" / "scoreboard_held.log"
RESET_DATE = "2026-11-15"

GRADING_RE = re.compile(r"\b(?:grade|grades|grading|graded)\b", re.IGNORECASE)
RETIRED_NAME_RE = re.compile(r"\btrap[\s_-]?map\b|TRAP_STRIP", re.IGNORECASE)

# LRCX entry fill verification constants (from site/lrcx-paid-to-wait.html & decisions.md 2026-11-02 / 2026-11-05)
LRCX_ENTRY_BID = 5.00
LRCX_ENTRY_ASK = 6.70
LRCX_BUYBACK_PRICE = 16.00
LRCX_COLLATERAL = 21000.00
LRCX_EXPECTED_REALIZED = -1043.33
LRCX_EXPECTED_EXIT_VALUE = 19956.67


def buy_fill(bid: float, ask: float) -> float:
    """Buy fill (opening long or closing short): a third of the spread in from the ask."""
    return ask - (ask - bid) / 3.0


def sell_fill(bid: float, ask: float) -> float:
    """Sell fill (opening short or closing long): a third of the spread in from the bid."""
    return bid + (ask - bid) / 3.0


def fmt_date_short(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        d = date.fromisoformat(str(iso_str)[:10])
    except ValueError:
        return str(iso_str)
    out = f"{d.strftime('%b')} {d.day}"
    return out if d.year == 2026 else f"{out}, {d.year}"


def _parse_strikes(pos: dict[str, Any]) -> list[float]:
    raw = str(pos.get("strikes") or "")
    nums = re.findall(r"\d+(?:\.\d+)?", raw)
    return [float(x) for x in nums]


def _spread_right(pos: dict[str, Any]) -> str | None:
    s = f"{pos.get('structure', '')} {pos.get('name', '')}".lower()
    if "call" in s:
        return "call"
    if "put" in s:
        return "put"
    legs = pos.get("legs")
    if isinstance(legs, dict) and legs:
        k = next(iter(legs.keys())).upper()
        if k.endswith("C"):
            return "call"
        if k.endswith("P"):
            return "put"
    return None


def _normalized_legs(pos: dict[str, Any]) -> list[dict[str, Any]]:
    """Return list of {label, side, qty, strike, right, instrument_id, bid, ask, fill}."""
    legs = pos.get("legs")
    right = _spread_right(pos)
    out: list[dict[str, Any]] = []
    if isinstance(legs, dict):
        for label, info in legs.items():
            if not isinstance(info, dict):
                continue
            side = str(info.get("side") or "buy").lower()
            qty = 1 if side == "buy" else -1
            m = re.match(r"(\d+(?:\.\d+)?)([CP])?", str(label).strip(), re.I)
            strike = float(m.group(1)) if m else None
            lright = (
                "call"
                if (m and (m.group(2) or "").upper() == "C")
                else "put"
                if (m and (m.group(2) or "").upper() == "P")
                else right
            )
            out.append({
                "label": str(label),
                "side": side,
                "qty": qty,
                "strike": strike,
                "right": lright,
                "instrument_id": str(info.get("instrument_id") or "").strip(),
                "bid": pq._float(info.get("bid")),
                "ask": pq._float(info.get("ask")),
                "fill": pq._float(info.get("fill")),
            })
    elif isinstance(legs, list):
        for info in legs:
            if not isinstance(info, dict):
                continue
            side = str(info.get("side") or ("buy" if (info.get("qty", 1) > 0) else "sell")).lower()
            qty = 1 if side == "buy" else -1
            out.append({
                "label": str(info.get("label") or info.get("strike") or ""),
                "side": side,
                "qty": qty,
                "strike": pq._float(info.get("strike")),
                "right": str(info.get("right") or right or "").lower() or None,
                "instrument_id": str(info.get("instrument_id") or "").strip(),
                "bid": pq._float(info.get("bid")),
                "ask": pq._float(info.get("ask")),
                "fill": pq._float(info.get("fill")),
            })
    return out


def _wrong_if_text(pos: dict[str, Any]) -> str:
    if pos.get("proved_wrong"):
        return str(pos["proved_wrong"]).strip()
    pid = str(pos.get("id") or "")
    if pid == "strc-park":
        return "Cash park: sold in 9:00–11:00 AM CT window only if a new approved trade exceeds the cash sleeve (Nov 16, 2026 rule)"
    if pid == "lrcx-put":
        return "LRCX below $200 by Dec 4, 2026 (traded through $200 at open on Nov 5, 2026)"
    expiry = pos.get("expiry")
    breakeven = pq._float(pos.get("breakeven"))
    ticker = str(pos.get("ticker") or "").upper()
    right = _spread_right(pos)
    if ticker and expiry and breakeven is not None:
        exp_lbl = fmt_date_short(expiry)
        if right == "put":
            return f"{ticker} closes at or above ${breakeven:.2f} on {exp_lbl} (held to expiry)"
        return f"{ticker} closes at or below ${breakeven:.2f} on {exp_lbl} (held to expiry)"
    stop = str(pos.get("stop") or "").strip()
    if stop:
        return f"{stop} ({fmt_date_short(expiry)} expiry)" if expiry else stop
    return f"Review at {fmt_date_short(expiry)} expiry" if expiry else "No fixed expiry"


def _strike_label(pos: dict[str, Any]) -> str:
    pid = str(pos.get("id") or "")
    if pid == "strc-park" or (pos.get("shares") and not pos.get("strikes")):
        return "— (shares)"
    if pid == "lrcx-put":
        return "$210 put"
    strikes = str(pos.get("strikes") or "").strip()
    right = _spread_right(pos)
    contracts = pos.get("contracts")
    if strikes:
        r_lbl = f" {right}s" if right else ""
        c_lbl = f" ×{contracts}" if contracts else ""
        return f"{strikes}{r_lbl}{c_lbl}"
    return str(pos.get("structure") or "—")


def _intrinsic_spread_mark(pos: dict[str, Any], legs: list[dict[str, Any]], spot: float) -> float | None:
    if not legs or spot is None:
        return None
    total = 0.0
    for leg in legs:
        strike = leg.get("strike")
        right = leg.get("right")
        if strike is None or right not in ("call", "put"):
            return None
        val = max(0.0, spot - strike) if right == "call" else max(0.0, strike - spot)
        total += leg["qty"] * val
    return total


def _check_auto_close(
    pos: dict[str, Any],
    legs: list[dict[str, Any]],
    current_mark: float | None,
    current_value: float | None,
    eq_quote: dict[str, Any] | None,
    now_ct: datetime,
) -> tuple[str, str, str | None, float | None]:
    """Return (status, status_label, closed_date, exit_value) using auto-close rules."""
    spot = pq._float((eq_quote or {}).get("last")) or pq._float((eq_quote or {}).get("previous_close"))
    cost = float(pos.get("cost") or 0.0)

    # 1. Explicit stop rules (underlying or mark)
    stop_below = pq._float(pos.get("stop_below"))
    stop_above = pq._float(pos.get("stop_above"))
    stop_mark_below = pq._float(pos.get("stop_mark_below"))
    stop_mark_above = pq._float(pos.get("stop_mark_above"))
    if stop_below is not None and spot is not None and spot < stop_below:
        return "closed_stop", "Closed at stop", now_ct.date().isoformat(), current_value
    if stop_above is not None and spot is not None and spot > stop_above:
        return "closed_stop", "Closed at stop", now_ct.date().isoformat(), current_value
    if stop_mark_below is not None and current_mark is not None and current_mark <= stop_mark_below:
        return "closed_stop", "Closed at stop", now_ct.date().isoformat(), current_value
    if stop_mark_above is not None and current_mark is not None and current_mark >= stop_mark_above:
        return "closed_stop", "Closed at stop", now_ct.date().isoformat(), current_value

    # 2. Explicit target rules
    target_above = pq._float(pos.get("target_above"))
    target_below = pq._float(pos.get("target_below"))
    target_mark_above = pq._float(pos.get("target_mark_above"))
    target_mark_below = pq._float(pos.get("target_mark_below"))
    if target_above is not None and spot is not None and spot >= target_above:
        return "closed_target", "Closed at target", now_ct.date().isoformat(), current_value
    if target_below is not None and spot is not None and spot <= target_below:
        return "closed_target", "Closed at target", now_ct.date().isoformat(), current_value
    if target_mark_above is not None and current_mark is not None and current_mark >= target_mark_above:
        return "closed_target", "Closed at target", now_ct.date().isoformat(), current_value
    if target_mark_below is not None and current_mark is not None and current_mark <= target_mark_below:
        return "closed_target", "Closed at target", now_ct.date().isoformat(), current_value

    # 3. Expiry auto-close (after 3:00 PM CT on expiry day, or on any subsequent day)
    exp_str = pos.get("expiry")
    if exp_str:
        try:
            exp_date = date.fromisoformat(str(exp_str)[:10])
        except ValueError:
            exp_date = None
        if exp_date is not None and (
            now_ct.date() > exp_date or (now_ct.date() == exp_date and now_ct.hour >= 15)
        ):
            exit_val = current_value
            if exit_val is None and spot is not None and legs and pos.get("contracts"):
                intr = _intrinsic_spread_mark(pos, legs, spot)
                if intr is not None:
                    exit_val = round(intr * float(pos["contracts"]) * 100.0, 2)
            if exit_val is None:
                exit_val = cost
            return "closed_expiry", "Closed at expiry", exp_date.isoformat(), exit_val

    is_park = str(pos.get("id") or "") == "strc-park" or (
        pos.get("shares") and not pos.get("official_weekly_trade")
    )
    return "open", ("Cash park" if is_park else "Open"), None, None


def _scan_banned_wording(obj: Any, path: str = "") -> list[str]:
    """Return list of wording violations ('bet' in own voice, grading words, retired Trap Map)."""
    violations: list[str] = []
    for p, snip in find_style_gate_hits(obj):
        violations.append(f"style gate 'bet' wording at {path}{p}: {snip}")

    def walk(node: Any, cur: str) -> None:
        if isinstance(node, str):
            if GRADING_RE.search(node):
                violations.append(f"grading wording at {cur}: {node!r}")
            if RETIRED_NAME_RE.search(node):
                violations.append(f"retired Trap Map wording at {cur}: {node!r}")
        elif isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{cur}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{cur}[{i}]")

    walk(obj, path or "root")
    return violations


def _tie_out_open_row(pos: dict[str, Any], row: dict[str, Any], quote_legs: list[dict[str, Any]]) -> list[str]:
    """Verify entry fill math, cost, max_loss, breakeven, and closing-side mark math."""
    errs: list[str] = []
    pid = str(pos.get("id") or row.get("id") or "?")

    # 1. Entry tie-out
    if pos.get("shares"):
        shares = float(pos["shares"])
        bid = pq._float(pos.get("bid"))
        ask = pq._float(pos.get("ask"))
        if bid is None or ask is None:
            errs.append(f"{pid}: missing entry bid/ask")
        else:
            expected_fill = buy_fill(bid, ask)
            book_fill = pq._float(pos.get("fill"))
            if book_fill is not None and abs(book_fill - expected_fill) > 0.001:
                errs.append(f"{pid}: entry fill {book_fill} != expected {expected_fill:.6f}")
            expected_cost = round(shares * expected_fill, 2)
            book_cost = float(pos.get("cost") or 0.0)
            if abs(book_cost - expected_cost) > 0.02:
                errs.append(f"{pid}: entry cost {book_cost:.2f} != expected {expected_cost:.2f}")
    else:
        legs = _normalized_legs(pos)
        if legs and pos.get("contracts"):
            contracts = float(pos["contracts"])
            net_debit = 0.0
            for leg in legs:
                b, a = leg.get("bid"), leg.get("ask")
                if b is None or a is None:
                    errs.append(f"{pid} {leg['label']}: missing entry bid/ask")
                    continue
                exp_fill = buy_fill(b, a) if leg["side"] == "buy" else sell_fill(b, a)
                if leg.get("fill") is not None and abs(leg["fill"] - exp_fill) > 0.001:
                    errs.append(f"{pid} {leg['label']}: fill {leg['fill']} != expected {exp_fill:.6f}")
                net_debit += leg["qty"] * exp_fill
            if not errs:
                book_debit = pq._float(pos.get("debit_per_spread"))
                if book_debit is not None and abs(book_debit - net_debit) > 0.001:
                    errs.append(f"{pid}: debit_per_spread {book_debit} != expected {net_debit:.6f}")
                expected_cost = round(net_debit * contracts * 100.0, 2)
                book_cost = float(pos.get("cost") or 0.0)
                if abs(book_cost - expected_cost) > 0.02:
                    errs.append(f"{pid}: entry cost {book_cost:.2f} != expected {expected_cost:.2f}")
                max_loss = pq._float(pos.get("max_loss"))
                if max_loss is not None and abs(max_loss - expected_cost) > 0.02:
                    errs.append(f"{pid}: max_loss {max_loss:.2f} != expected {expected_cost:.2f}")
                breakeven = pq._float(pos.get("breakeven"))
                long_legs = [l for l in legs if l["qty"] > 0 and l.get("strike") is not None]
                if breakeven is not None and len(long_legs) == 1:
                    k_long = long_legs[0]["strike"]
                    exp_be = k_long + net_debit if long_legs[0].get("right") == "call" else k_long - net_debit
                    if abs(breakeven - exp_be) > 0.01:
                        errs.append(f"{pid}: breakeven {breakeven} != expected {exp_be:.4f}")

    # 2. Closing-side mark tie-out (if live/saved quotes used)
    if quote_legs:
        if pos.get("shares"):
            q = quote_legs[0]
            exp_mark = sell_fill(q["bid"], q["ask"])
            exp_val = round(float(pos["shares"]) * exp_mark, 2)
        else:
            exp_mark = sum(
                q["qty"] * (sell_fill(q["bid"], q["ask"]) if q["qty"] > 0 else buy_fill(q["bid"], q["ask"]))
                for q in quote_legs
            )
            exp_val = round(exp_mark * float(pos["contracts"]) * 100.0, 2)
        if abs(float(row["current_mark"]) - exp_mark) > 0.001:
            errs.append(f"{pid}: current_mark {row['current_mark']} != expected {exp_mark:.6f}")
        if abs(float(row["current_value"]) - exp_val) > 0.02:
            errs.append(f"{pid}: current_value {row['current_value']} != expected {exp_val:.2f}")
        exp_pnl = round(exp_val - float(row["cost"]), 2)
        if row["status"] == "open" and abs(float(row["unrealized_pnl"]) - exp_pnl) > 0.02:
            errs.append(f"{pid}: unrealized_pnl {row['unrealized_pnl']} != expected {exp_pnl:.2f}")

    return errs


def _tie_out_closed_row(pos: dict[str, Any], row: dict[str, Any]) -> list[str]:
    errs: list[str] = []
    pid = str(pos.get("id") or row.get("id") or "?")
    cost = pq._float(row.get("cost"))
    exit_val = pq._float(row.get("exit_value"))
    realized = pq._float(row.get("realized_pnl"))
    if cost is None or exit_val is None or realized is None:
        return [f"{pid}: missing cost/exit_value/realized_pnl"]
    if abs((exit_val - cost) - realized) > 0.02:
        errs.append(f"{pid}: exit_value ({exit_val:.2f}) - cost ({cost:.2f}) != realized ({realized:.2f})")

    if pid == "lrcx-put":
        entry_credit_per_share = sell_fill(LRCX_ENTRY_BID, LRCX_ENTRY_ASK)
        expected_credit = round(entry_credit_per_share * 100.0, 2)
        expected_buyback = round(LRCX_BUYBACK_PRICE * 100.0, 2)
        expected_realized = round(expected_credit - expected_buyback, 2)
        expected_exit_val = round(LRCX_COLLATERAL + expected_realized, 2)
        if str(row.get("ticker")).upper() != "LRCX":
            errs.append("lrcx-put: ticker must be LRCX")
        if "210" not in str(row.get("strike")):
            errs.append("lrcx-put: strike must show $210 put")
        if row.get("expiry") != "2026-12-04":
            errs.append(f"lrcx-put: expiry {row.get('expiry')} != 2026-12-04")
        if row.get("closed") != "2026-11-05":
            errs.append(f"lrcx-put: closed {row.get('closed')} != 2026-11-05")
        if row.get("status") != "closed_stop":
            errs.append(f"lrcx-put: status {row.get('status')} != closed_stop")
        if abs(cost - LRCX_COLLATERAL) > 0.02:
            errs.append(f"lrcx-put: cost {cost} != {LRCX_COLLATERAL}")
        if abs(exit_val - expected_exit_val) > 0.02 or abs(exit_val - LRCX_EXPECTED_EXIT_VALUE) > 0.02:
            errs.append(f"lrcx-put: exit_value {exit_val} != {LRCX_EXPECTED_EXIT_VALUE}")
        if abs(realized - expected_realized) > 0.02 or abs(realized - LRCX_EXPECTED_REALIZED) > 0.02:
            errs.append(f"lrcx-put: realized {realized} != {LRCX_EXPECTED_REALIZED}")
        if "$16" not in str(row.get("exit_detail") or ""):
            errs.append("lrcx-put: exit_detail must show $16 buyback")
    return errs


def _is_post_reset_closed(pos: dict[str, Any]) -> bool:
    opened = str(pos.get("opened") or "")[:10]
    closed = str(pos.get("closed") or "")[:10]
    return (opened >= RESET_DATE) or (closed > RESET_DATE)


def _format_closed_row(pos: dict[str, Any]) -> dict[str, Any]:
    pid = str(pos.get("id") or "")
    ticker = str(pos.get("ticker") or "").upper()
    cost = round(float(pos.get("cost") or 0.0), 2)
    exit_val = round(float(pos.get("exit_value") or 0.0), 2)
    realized = round(float(pos.get("realized") if pos.get("realized") is not None else (exit_val - cost)), 2)
    exit_text = str(pos.get("exit") or "")
    low_exit = exit_text.lower()

    if "stop" in low_exit:
        status, status_label = "closed_stop", "Closed at stop"
    elif "expiry" in low_exit or "expired" in low_exit:
        status, status_label = "closed_expiry", "Closed at expiry"
    elif "target" in low_exit:
        status, status_label = "closed_target", "Closed at target"
    else:
        status, status_label = "closed", "Closed"

    if pid == "lrcx-put":
        entry_fill = round(sell_fill(LRCX_ENTRY_BID, LRCX_ENTRY_ASK), 4)
        entry_credit = round(sell_fill(LRCX_ENTRY_BID, LRCX_ENTRY_ASK) * 100.0, 2)
        return {
            "id": pid,
            "ticker": "LRCX",
            "structure": "Short Dec 4, 2026 $210 put ×1",
            "owner": "Research",
            "pre_reset": True,
            "is_cash_park": False,
            "status": status,
            "status_label": status_label,
            "opened": str(pos.get("opened") or "2026-11-02"),
            "closed": str(pos.get("closed") or "2026-11-05"),
            "strike": "$210 put",
            "expiry": "2026-12-04",
            "expiry_note": "Closed early Nov 5",
            "contracts": 1,
            "entry_fill": entry_fill,
            "entry_detail": f"Nov 2 · ${entry_fill:.2f} credit (${entry_credit:,.2f} on $21,000 collateral)",
            "cost": cost,
            "max_loss": round(cost - entry_credit, 2),
            "exit_fill": LRCX_BUYBACK_PRICE,
            "exit_detail": "Nov 5 · Bought back at $16.00 ($1,600.00)",
            "exit_value": exit_val,
            "realized_pnl": realized,
            "return_pct": round(100.0 * realized / cost, 2) if cost else 0.0,
            "wrong_if": _wrong_if_text(pos),
            "research_url": "lrcx-paid-to-wait.html",
            "price_type": str(pos.get("price_type") or "owner-stated paper fill"),
        }

    ret_pct = round(100.0 * realized / cost, 2) if cost else 0.0
    return {
        "id": pid,
        "ticker": ticker,
        "structure": str(pos.get("structure") or pos.get("name") or ticker),
        "owner": str(pos.get("owner") or "Team"),
        "pre_reset": False,
        "is_cash_park": pid == "strc-park",
        "status": status,
        "status_label": status_label,
        "opened": str(pos.get("opened") or ""),
        "closed": str(pos.get("closed") or ""),
        "strike": _strike_label(pos),
        "expiry": pos.get("expiry"),
        "contracts": pos.get("contracts"),
        "shares": pos.get("shares"),
        "entry_fill": pq._float(pos.get("debit_per_spread") or pos.get("fill")),
        "entry_detail": f"{fmt_date_short(pos.get('opened'))} · ${cost:,.2f}",
        "cost": cost,
        "max_loss": round(float(pos.get("max_loss") if pos.get("max_loss") is not None else cost), 2),
        "exit_fill": pq._float(pos.get("exit_fill")),
        "exit_detail": exit_text,
        "exit_value": exit_val,
        "realized_pnl": realized,
        "return_pct": ret_pct,
        "wrong_if": _wrong_if_text(pos),
        "research_url": pos.get("research_url"),
        "price_type": str(pos.get("price_type") or "closing fill rule"),
    }


def build_scoreboard(
    book: dict[str, Any],
    quotes: dict[str, Any],
    prev_scoreboard: dict[str, Any] | None = None,
    now_ct: datetime | None = None,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Generate scoreboard dict + list of held rows [{id, ticker, reason}]."""
    now_ct = (now_ct or datetime.now(CT)).astimezone(CT)
    prev_by_id: dict[str, dict[str, Any]] = {}
    if isinstance(prev_scoreboard, dict):
        for r in (prev_scoreboard.get("open") or []) + (prev_scoreboard.get("closed") or []):
            if isinstance(r, dict) and r.get("id"):
                prev_by_id[str(r["id"])] = r

    eq_quotes = quotes.get("equity") or {}
    opt_quotes = quotes.get("options") or {}

    open_rows: list[dict[str, Any]] = []
    closed_rows: list[dict[str, Any]] = []
    held_rows: list[dict[str, str]] = []

    book_meta = book.get("book") or {}
    starting_cash = round(float(book_meta.get("starting_cash") or 100000.0), 2)
    cash = round(float(book_meta.get("cash") or 0.0), 2)
    auto_closed_cash_add = 0.0

    # Process open positions
    for pos in book.get("open") or []:
        pid = str(pos.get("id") or "")
        ticker = str(pos.get("ticker") or "").upper()
        cost = round(float(pos.get("cost") or 0.0), 2)
        max_loss = round(float(pos.get("max_loss") if pos.get("max_loss") is not None else cost), 2)
        is_cash_park = pid == "strc-park" or (bool(pos.get("shares")) and not pos.get("official_weekly_trade"))
        eq_q = eq_quotes.get(ticker)

        quote_legs_used: list[dict[str, Any]] = []
        quote_flags: list[str] = []
        current_mark: float | None = None
        current_value: float | None = None
        row_quote_time_ct: str | None = None
        row_quote_label: str = ""
        row_quote_source: str = ""
        row_is_fallback = bool(quotes.get("is_fallback"))

        if pos.get("shares"):
            shares = float(pos["shares"])
            if eq_q and not pq.quote_problems(ticker, eq_q, now_ct):
                mark = sell_fill(float(eq_q["bid"]), float(eq_q["ask"]))
                current_mark = round(mark, 4)
                current_value = round(shares * mark, 2)
                row_quote_time_ct = eq_q.get("quote_time_ct")
                row_quote_label = str(eq_q.get("quote_time_label") or "")
                row_quote_source = str(eq_q.get("quote_source") or quotes.get("quote_source") or "")
                row_is_fallback = bool(eq_q.get("is_fallback"))
                quote_legs_used.append({"bid": float(eq_q["bid"]), "ask": float(eq_q["ask"]), "qty": 1})
            else:
                if eq_q:
                    quote_flags.extend(pq.quote_problems(ticker, eq_q, now_ct))
                else:
                    quote_flags.append(f"{ticker}: no quote available")
        else:
            legs = _normalized_legs(pos)
            contracts = float(pos.get("contracts") or 0)
            leg_marks: list[tuple[int, float, dict[str, Any]]] = []
            leg_times: list[datetime] = []
            leg_sources: set[str] = set()
            leg_fallbacks: list[bool] = []
            for leg in legs:
                uid = leg.get("instrument_id") or ""
                oq = opt_quotes.get(uid)
                if oq is None:
                    # Try fallback lookup by symbol_leg text matching strike & right
                    for cand in opt_quotes.values():
                        desc = str(cand.get("symbol_leg") or "").upper()
                        strike_int = str(int(leg["strike"])) if leg.get("strike") and float(leg["strike"]).is_integer() else str(leg.get("strike") or "")
                        if ticker in desc and strike_int and f"${strike_int}" in desc and (leg.get("right") or "").upper() in desc:
                            oq = cand
                            break
                if not oq:
                    quote_flags.append(f"{pid} {leg['label']}: missing quote")
                    continue
                probs = pq.quote_problems(f"{pid} {leg['label']}", oq, now_ct)
                if probs:
                    quote_flags.extend(probs)
                    continue
                b, a = float(oq["bid"]), float(oq["ask"])
                cfill = sell_fill(b, a) if leg["qty"] > 0 else buy_fill(b, a)
                leg_marks.append((leg["qty"], cfill, {"bid": b, "ask": a, "qty": leg["qty"]}))
                ts = pq.parse_ct_timestamp(oq.get("quote_time_ct"))
                if ts:
                    leg_times.append(ts)
                if oq.get("quote_source"):
                    leg_sources.add(str(oq["quote_source"]))
                leg_fallbacks.append(bool(oq.get("is_fallback")))

            if len(leg_marks) == len(legs) and len(legs) > 0 and contracts > 0 and not quote_flags:
                exact_mark = sum(q * f for q, f, _ in leg_marks)
                current_mark = round(exact_mark, 4)
                current_value = round(exact_mark * contracts * 100.0, 2)
                quote_legs_used = [info for _, _, info in leg_marks]
                newest_leg_ts = max(leg_times) if leg_times else now_ct
                row_quote_time_ct = newest_leg_ts.isoformat(timespec="seconds")
                row_quote_label = pq.format_ct_label(newest_leg_ts)
                row_is_fallback = any(leg_fallbacks)
                row_quote_source = (
                    f"Saved quote fallback ({row_quote_label})"
                    if row_is_fallback
                    else (next(iter(leg_sources)) if len(leg_sources) == 1 else f"Robinhood read-only ({row_quote_label})")
                )

        # Fail-closed fallback to last good mark from previous scoreboard.json, then entry cost
        if current_value is None:
            prev = prev_by_id.get(pid)
            if prev and pq._float(prev.get("current_value")) is not None:
                current_mark = pq._float(prev.get("current_mark"))
                current_value = round(float(prev["current_value"]), 2)
                row_quote_time_ct = prev.get("quote_time_ct")
                row_quote_label = str(prev.get("quote_time_label") or "")
                row_quote_source = str(prev.get("quote_source") or "Prior mark") + " (kept after quote flag)"
                row_is_fallback = True
            else:
                current_mark = pq._float(pos.get("debit_per_spread") or pos.get("fill"))
                current_value = round(float(pos.get("value_at_entry") if pos.get("value_at_entry") is not None else cost), 2)
                row_quote_time_ct = pos.get("quote_at_ct") or pos.get("opened_at_ct")
                dt_fb = pq.parse_ct_timestamp(row_quote_time_ct)
                row_quote_label = pq.format_ct_label(dt_fb)
                row_quote_source = f"Entry mark fallback ({row_quote_label})" if row_quote_label else "Entry mark fallback"
                row_is_fallback = True

        legs_norm = _normalized_legs(pos)
        status, status_label, closed_date, auto_exit_val = _check_auto_close(
            pos, legs_norm, current_mark, current_value, eq_q, now_ct
        )

        if status != "open":
            exit_val = round(float(auto_exit_val if auto_exit_val is not None else current_value), 2)
            realized = round(exit_val - cost, 2)
            auto_closed_cash_add += exit_val
            entry_fill_num = pq._float(pos.get("debit_per_spread") or pos.get("fill"))
            entry_detail = (
                f"{fmt_date_short(pos.get('opened'))} · "
                + (f"${entry_fill_num:.2f} (${cost:,.2f})" if entry_fill_num is not None else f"${cost:,.2f}")
            )
            row_obj: dict[str, Any] = {
                "id": pid,
                "ticker": ticker,
                "structure": str(pos.get("structure") or pos.get("name") or ticker),
                "owner": str(pos.get("owner") or ("Cash park" if is_cash_park else "Team")),
                "pre_reset": False,
                "is_cash_park": is_cash_park,
                "status": status,
                "status_label": status_label,
                "opened": str(pos.get("opened") or ""),
                "closed": closed_date,
                "strike": _strike_label(pos),
                "expiry": pos.get("expiry"),
                "contracts": pos.get("contracts"),
                "shares": pos.get("shares"),
                "entry_fill": entry_fill_num,
                "entry_detail": entry_detail,
                "cost": cost,
                "max_loss": max_loss,
                "current_mark": current_mark,
                "current_value": exit_val,
                "exit_fill": current_mark,
                "exit_detail": f"{fmt_date_short(closed_date)} · {status_label} (${exit_val:,.2f})",
                "exit_value": exit_val,
                "realized_pnl": realized,
                "return_pct": round(100.0 * realized / cost, 2) if cost else 0.0,
                "wrong_if": _wrong_if_text(pos),
                "quote_time_ct": row_quote_time_ct,
                "quote_time_label": row_quote_label,
                "quote_source": row_quote_source,
                "is_fallback_quote": row_is_fallback,
                "quote_flags": quote_flags,
                "research_url": pos.get("research_url"),
            }
            tie_errs = _tie_out_open_row(pos, row_obj, quote_legs_used)
            word_errs = _scan_banned_wording(row_obj, pid)
            if tie_errs or word_errs:
                held_rows.append({"id": pid, "ticker": ticker, "reason": "; ".join(tie_errs + word_errs)})
            else:
                closed_rows.append(row_obj)
        else:
            unrealized = round(current_value - cost, 2)
            entry_fill_num = pq._float(pos.get("debit_per_spread") or pos.get("fill"))
            if is_cash_park and pos.get("shares") and entry_fill_num is not None:
                entry_detail = f"{fmt_date_short(pos.get('opened'))} · {int(pos['shares'])} sh @ ${entry_fill_num:.2f} (${cost:,.2f})"
            elif entry_fill_num is not None:
                entry_detail = f"{fmt_date_short(pos.get('opened'))} · ${entry_fill_num:.2f} debit (${cost:,.2f})"
            else:
                entry_detail = f"{fmt_date_short(pos.get('opened'))} · ${cost:,.2f}"

            row_obj = {
                "id": pid,
                "ticker": ticker,
                "structure": str(pos.get("structure") or pos.get("name") or ticker),
                "owner": str(pos.get("owner") or ("Cash park" if is_cash_park else "Team")),
                "pre_reset": False,
                "is_cash_park": is_cash_park,
                "status": "open",
                "status_label": status_label,
                "opened": str(pos.get("opened") or ""),
                "strike": _strike_label(pos),
                "expiry": pos.get("expiry"),
                "contracts": pos.get("contracts"),
                "shares": pos.get("shares"),
                "entry_fill": entry_fill_num,
                "entry_detail": entry_detail,
                "cost": cost,
                "max_loss": max_loss,
                "max_gain": pq._float(pos.get("max_gain")),
                "breakeven": pq._float(pos.get("breakeven")),
                "current_mark": current_mark,
                "current_value": current_value,
                "unrealized_pnl": unrealized,
                "return_pct": round(100.0 * unrealized / cost, 2) if cost else 0.0,
                "wrong_if": _wrong_if_text(pos),
                "quote_time_ct": row_quote_time_ct,
                "quote_time_label": row_quote_label,
                "quote_source": row_quote_source,
                "is_fallback_quote": row_is_fallback,
                "quote_flags": quote_flags,
                "research_url": pos.get("research_url"),
            }
            tie_errs = _tie_out_open_row(pos, row_obj, quote_legs_used)
            word_errs = _scan_banned_wording(row_obj, pid)
            if tie_errs or word_errs:
                held_rows.append({"id": pid, "ticker": ticker, "reason": "; ".join(tie_errs + word_errs)})
            else:
                open_rows.append(row_obj)

    # Process closed positions since Nov 15 reset + LRCX
    for pos in book.get("closed") or []:
        pid = str(pos.get("id") or "")
        if pid != "lrcx-put" and not _is_post_reset_closed(pos):
            continue
        row_obj = _format_closed_row(pos)
        tie_errs = _tie_out_closed_row(pos, row_obj)
        word_errs = _scan_banned_wording(row_obj, pid)
        if tie_errs or word_errs:
            held_rows.append({"id": pid, "ticker": row_obj["ticker"], "reason": "; ".join(tie_errs + word_errs)})
        else:
            closed_rows.append(row_obj)

    # Sort open: official trades newest first, cash park after
    open_rows.sort(key=lambda r: (1 if r.get("is_cash_park") else 0, r.get("opened") or ""), reverse=False)
    # Put official weekly trades newest-first, cash park last
    official_open = sorted([r for r in open_rows if not r.get("is_cash_park")], key=lambda r: r.get("opened") or "", reverse=True)
    park_open = [r for r in open_rows if r.get("is_cash_park")]
    open_rows = official_open + park_open

    # Sort closed: post-reset newest first, then pre-reset (LRCX)
    closed_rows.sort(key=lambda r: (1 if r.get("pre_reset") else 0, -(int(str(r.get("closed") or "0000-00-00").replace("-", "")) if re.match(r"\d{4}-\d{2}-\d{2}", str(r.get("closed") or "")) else 0)))

    # Running totals for the post-Nov 15 $100,000 reset book
    eff_cash = round(cash + auto_closed_cash_add, 2)
    allocated_cost = round(sum(float(r["cost"]) for r in open_rows), 2)
    open_value = round(sum(float(r["current_value"]) for r in open_rows), 2)
    book_value = round(eff_cash + open_value, 2)
    unrealized_total = round(open_value - allocated_cost, 2)
    post_reset_closed = [r for r in closed_rows if not r.get("pre_reset")]
    realized_since_reset = round(sum(float(r["realized_pnl"]) for r in post_reset_closed), 2)
    total_pnl_since_reset = round(unrealized_total + realized_since_reset, 2)
    total_return_pct = round(100.0 * total_pnl_since_reset / starting_cash, 2) if starting_cash else 0.0

    # Book-level tie-out sanity check (only when no open rows were held)
    if not held_rows:
        expected_book_cash_plus_cost = round(starting_cash + realized_since_reset, 2)
        actual_cash_plus_cost = round(eff_cash + allocated_cost, 2)
        if abs(expected_book_cash_plus_cost - actual_cash_plus_cost) > 0.05:
            held_rows.append({
                "id": "_book_totals",
                "ticker": "BOOK",
                "reason": f"Book cash + open cost ({actual_cash_plus_cost:.2f}) != starting_cash + realized ({expected_book_cash_plus_cost:.2f})",
            })

    wl = book.get("wins_losses") or {}
    prior_realized = round(float(book.get("prior_book_inception_realized_pnl") or 0.0), 2)
    prior_cap = round(float(book.get("prior_book_starting_capital") or 0.0), 2)

    all_quote_fallback = bool(quotes.get("is_fallback")) or any(r.get("is_fallback_quote") for r in open_rows)
    row_times = [
        pq.parse_ct_timestamp(r.get("quote_time_ct"))
        for r in open_rows
        if r.get("quote_time_ct")
    ]
    row_times = [t for t in row_times if t is not None]
    newest_q_dt = max(row_times) if row_times else pq.parse_ct_timestamp(quotes.get("quote_time_ct")) or now_ct
    quote_time_label = pq.format_ct_label(newest_q_dt)
    quote_source_label = (
        f"Saved quotes ({quote_time_label})"
        if all_quote_fallback
        else f"Robinhood read-only ({quote_time_label})"
    )

    scoreboard = {
        "schema_version": 1,
        "paper_only": True,
        "generated_at_ct": now_ct.isoformat(timespec="seconds"),
        "generated_at_label": pq.format_ct_label(now_ct),
        "book_as_of_ct": book.get("as_of_ct"),
        "reset_date": RESET_DATE,
        "fill_rule": "Buys at ask - (ask - bid)/3; sells at bid + (ask - bid)/3; open marks priced on the closing side.",
        "quote_time_ct": newest_q_dt.isoformat(timespec="seconds"),
        "quote_time_label": quote_time_label,
        "quote_source": quote_source_label,
        "is_fallback_quote": all_quote_fallback,
        "totals": {
            "starting_cash": starting_cash,
            "cash": eff_cash,
            "allocated_cost": allocated_cost,
            "open_value": open_value,
            "book_value": book_value,
            "unrealized_pnl": unrealized_total,
            "realized_pnl_since_reset": realized_since_reset,
            "total_pnl_since_reset": total_pnl_since_reset,
            "total_return_pct": total_return_pct,
            "open_count": len(open_rows),
            "open_official_count": len([r for r in open_rows if not r.get("is_cash_park")]),
            "cash_park_count": len([r for r in open_rows if r.get("is_cash_park")]),
            "closed_since_reset_count": len(post_reset_closed),
            "historical_shown_count": len([r for r in closed_rows if r.get("pre_reset")]),
            "held_count": len(held_rows),
            "prior_book_realized_pnl": prior_realized,
            "prior_book_starting_capital": prior_cap,
            "prior_book_closed_wins": int(wl.get("closed_wins") or 0),
            "prior_book_closed_losses": int(wl.get("closed_losses") or 0),
        },
        "open": open_rows,
        "closed": closed_rows,
    }

    # Final full-payload wording scan
    payload_word_errs = _scan_banned_wording(scoreboard, "scoreboard")
    if payload_word_errs:
        raise ValueError("Scoreboard payload failed wording check: " + "; ".join(payload_word_errs))

    return scoreboard, held_rows


def _write_held_log(path: Path, held_rows: list[dict[str, str]], now_ct: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not held_rows:
        return
    with path.open("a", encoding="utf-8") as f:
        for h in held_rows:
            f.write(json.dumps({
                "at_ct": now_ct.isoformat(timespec="seconds"),
                "id": h["id"],
                "ticker": h["ticker"],
                "reason": h["reason"],
            }) + "\n")


def verify_existing_scoreboard(scoreboard: dict[str, Any], book: dict[str, Any]) -> list[str]:
    """Run tie-out & wording checks on an already-written scoreboard.json."""
    errs: list[str] = []
    errs.extend(_scan_banned_wording(scoreboard, "scoreboard"))

    open_by_id = {str(p.get("id")): p for p in (book.get("open") or []) if p.get("id")}
    closed_by_id = {str(p.get("id")): p for p in (book.get("closed") or []) if p.get("id")}

    for r in scoreboard.get("open") or []:
        pid = str(r.get("id") or "")
        pos = open_by_id.get(pid)
        if not pos:
            errs.append(f"{pid}: open row missing from book")
            continue
        errs.extend(_tie_out_open_row(pos, r, []))

    closed_ids = {str(r.get("id") or "") for r in (scoreboard.get("closed") or [])}
    if "lrcx-put" not in closed_ids:
        errs.append("lrcx-put: required LRCX closed row missing from scoreboard")
    for r in scoreboard.get("closed") or []:
        pid = str(r.get("id") or "")
        pos = closed_by_id.get(pid) or open_by_id.get(pid)
        if not pos:
            errs.append(f"{pid}: closed row missing from book")
            continue
        errs.extend(_tie_out_closed_row(pos, r))

    t = scoreboard.get("totals") or {}
    if abs(round(float(t.get("cash", 0)) + float(t.get("open_value", 0)), 2) - float(t.get("book_value", 0))) > 0.02:
        errs.append("totals: cash + open_value != book_value")
    if abs(round(float(t.get("open_value", 0)) - float(t.get("allocated_cost", 0)), 2) - float(t.get("unrealized_pnl", 0))) > 0.02:
        errs.append("totals: open_value - allocated_cost != unrealized_pnl")
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build & tie-out site/data/scoreboard.json.")
    ap.add_argument("--book", type=Path, default=None, help="Paper book JSON path")
    ap.add_argument("--quotes", type=Path, default=DEFAULT_QUOTES, help="Normalized quotes JSON path")
    ap.add_argument("--saved-legs", type=Path, default=pq.DEFAULT_SAVED_LEGS, help="saved_legs.csv path")
    ap.add_argument("--fallback-csv", type=Path, default=pq.DEFAULT_FALLBACK_CSV, help="Fallback dated quotes CSV")
    ap.add_argument("--quotes-dir", type=Path, default=pq.COS_QUOTES_DIR, help="Directory with YYYY-MM-DD.csv")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output scoreboard JSON path")
    ap.add_argument("--held-log", type=Path, default=DEFAULT_HELD_LOG, help="Held rows log path")
    ap.add_argument("--verify-only", action="store_true", help="Verify existing --out against --book and exit")
    ap.add_argument("--strict", action="store_true", help="Exit 1 if any row was held during build")
    args = ap.parse_args(argv)

    book_path = pq.resolve_book_path(args.book)
    if not book_path.is_file():
        print(f"ERROR: paper book not found: {book_path}", file=sys.stderr)
        return 1
    book = json.loads(book_path.read_text(encoding="utf-8"))

    if args.verify_only:
        if not args.out.is_file():
            print(f"ERROR: scoreboard JSON not found: {args.out}", file=sys.stderr)
            return 1
        sb = json.loads(args.out.read_text(encoding="utf-8"))
        errs = verify_existing_scoreboard(sb, book)
        if errs:
            for e in errs:
                print(f"TIE-OUT FAIL: {e}", file=sys.stderr)
            return 1
        print(
            f"✓ Scoreboard tie-out OK: {len(sb.get('open') or [])} open, "
            f"{len(sb.get('closed') or [])} closed, book=${sb['totals']['book_value']:,.2f}, "
            f"source={sb['quote_source']}"
        )
        return 0

    now_ct = datetime.now(CT)
    if args.quotes.is_file():
        quotes = json.loads(args.quotes.read_text(encoding="utf-8"))
    else:
        saved_legs_path = args.saved_legs
        if not saved_legs_path.is_file() and (pq.COS_QUOTES_DIR / "saved_legs.csv").is_file():
            saved_legs_path = pq.COS_QUOTES_DIR / "saved_legs.csv"
        quotes = pq.normalize_quotes(
            book=book,
            saved_legs_path=saved_legs_path,
            fallback_csv_path=args.fallback_csv,
            quotes_dir=args.quotes_dir,
            now=now_ct,
        )

    prev_sb = None
    if args.out.is_file():
        try:
            prev_sb = json.loads(args.out.read_text(encoding="utf-8"))
        except Exception:
            prev_sb = None

    scoreboard, held_rows = build_scoreboard(book, quotes, prev_scoreboard=prev_sb, now_ct=now_ct)
    if held_rows:
        _write_held_log(args.held_log, held_rows, now_ct)
        for h in held_rows:
            print(f"HELD ROW {h['id']} ({h['ticker']}): {h['reason']}", file=sys.stderr)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(scoreboard, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(args.out)

    t = scoreboard["totals"]
    print(
        f"Wrote {args.out}: {len(scoreboard['open'])} open, {len(scoreboard['closed'])} closed, "
        f"held={len(held_rows)}, book=${t['book_value']:,.2f}, unrealized=${t['unrealized_pnl']:+,.2f}, "
        f"quotes={scoreboard['quote_source']}"
    )
    if args.strict and held_rows:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
