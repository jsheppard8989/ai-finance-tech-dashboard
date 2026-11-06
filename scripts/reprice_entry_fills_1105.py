#!/usr/bin/env python3
"""Offline correction of four Oct 29 paper-entry debits; no quotes or DB access.

Evidence: /workspace/cos/runs/2026-11-05-entry-fill-audit.md, corroborated by
row_trades_2026-10-29.md lines 11-13 and MU's saved opt_open_2028-12-15.json.
Current marks, timestamps, counts, strikes and expiry exits are preserved.
Run from any directory; build_trap_map regenerates all existing derived outputs.
"""
from __future__ import annotations

import json
import sys
from fractions import Fraction as F
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# ticker: long bid/ask, short bid/ask, spreads, strikes, audited cost/max loss
OPENING = {
    "ASTS": ("3.30", "3.60", "1.03", "1.28", 7, 43, 37, "1670.67"),
    "FRMI": (".35", ".45", ".15", ".20", 60, 3, 2.5, "1500.00"),
    "TSAT": ("5.80", "6.60", "3.00", "3.50", 5, 40, 30, "1583.33"),
    "MU": ("108", "128", "40", "60", 1, 700, 500, "7466.67"),
}
CAVEATS = {
    "ASTS": "Modeled original-entry fill, not an actual execution.",
    "FRMI": "Few contracts trade; this modeled fill is not assured.",
    "TSAT": "Very little open interest at entry (40P: 2); this modeled fill is only a rough guide, not assured. Execution may be worse.",
    "MU": "Both markets were $20 wide and the last trades were from the previous day; modeled fills are not assured.",
}


def apply(d: dict) -> dict:
    """Idempotently change entry fields and their original-date benchmark lot only."""
    rows = {r["ticker"]: r for r in d["rows"]}
    calculated = {}
    # Verify every input before changing any row. Never infer a missing snapshot.
    for ticker, (lb, la, sb, sa, count, long_k, short_k, expected) in OPENING.items():
        t = rows[ticker]["trade"]
        expected_legs = [{"right": "P", "strike": long_k, "qty": 1},
                         {"right": "P", "strike": short_k, "qty": -1}]
        if t["contracts"] != count or t["legs"] != expected_legs or t["posted"] != "2026-10-29":
            raise ValueError(f"{ticker}: entry structure differs from saved evidence")
        if t["exit"] != {"type": "expiry", "date": t["expiry"]}:
            raise ValueError(f"{ticker}: must remain held to expiry")
        lb, la, sb, sa = map(F, (lb, la, sb, sa))
        buy, sell = la - (la - lb) / 3, sb + (sa - sb) / 3
        debit = buy - sell
        cost = round(float(debit * 100 * count), 2)
        if cost != float(expected):
            raise ValueError(f"{ticker}: recomputation disagrees with audited cost")
        profit = round(float((F(str(long_k)) - F(str(short_k)) - debit) * 100 * count), 2)
        breakeven = F(str(long_k)) - debit
        if ticker == "MU" and (round(float(breakeven), 2) != 625.33 or profit != 12533.33):
            raise ValueError("MU: recomputation disagrees with audited expiry terms")
        calculated[ticker] = (debit, cost, profit, breakeven, buy, sell)
    lots = [x for x in d["benchmark"]["buys"] if set(x["rows"]) == {rows[k]["id"] for k in OPENING}]
    if len(lots) != 1 or lots[0]["date"] != "2026-10-29" or lots[0]["price"] != 769.36:
        raise ValueError("Missing or changed original-date SPY benchmark lot; stop for review")

    for ticker, (debit, cost, profit, breakeven, buy, sell) in calculated.items():
        t = rows[ticker]["trade"]
        lb, la, sb, sa, count, long_k, short_k, _ = OPENING[ticker]
        stamp = "8:32 AM CT" if ticker == "MU" else "about 1:57 PM CT"
        display = f"{float(debit):.6f}".rstrip("0").rstrip(".")
        t.update(cost=cost, max_loss=f"${cost:,.2f}", entry_debit=float(debit),
                 breakeven=float(breakeven), max_profit=profit)
        t["entry_pricing"] = {
            "rule": "third_from_worst", "snapshot_date": "2026-10-29",
            "source": f"Saved Yahoo Finance opening bid/asks, Oct 29, 2026, {stamp}",
            "formula": "Buy at ask minus (ask minus bid)/3; sell at bid plus (ask minus bid)/3. Keep full precision until the total is rounded to cents.",
            "legs": [
                {"strike": long_k, "side": "buy", "bid": float(lb), "ask": float(la), "modeled_fill": float(buy)},
                {"strike": short_k, "side": "sell", "bid": float(sb), "ask": float(sa), "modeled_fill": float(sell)},
            ],
        }
        if ticker == "MU":
            t["entry_pricing"]["last_trades"] = "700P: Oct 28, 2026, 1:00:13 PM CT; 500P: Oct 28, 2026, 2:15:06 PM CT. Per-leg quote timestamps were not supplied."
        x = t["expression"]
        x["debit"] = f"${display} per share, modeled original entry"
        x["caveat"] = (f"{CAVEATS[ticker]} Original Yahoo bid/asks: Oct 29, 2026, {stamp}; "
                       "a third of each leg's spread in from the worst fill. Held to expiry")
        t["text"] = (f"{x['expiry']} {x['strikes'].replace(' / ', '/')} put debit spread, {count} {'spread' if count == 1 else 'spreads'}, "
                     f"${display} per-share modeled original-entry debit (stock {x['stock_then']}); "
                     f"total cost and maximum loss ${cost:,.2f}. {x['caveat']}")
    rows["MU"]["what_proves_it"] = "Memory prices and profit margins fall enough that Micron closes below $625.33 (the modeled expiry breakeven)."
    lot = lots[0]
    lot["dollars"] = round(sum(rows[k]["trade"]["cost"] for k in OPENING), 2)
    lot["shares"] = round(lot["dollars"] / lot["price"], 5)
    return d


def main():
    sys.path.insert(0, str(ROOT / "pipeline"))
    import build_trap_map
    path = build_trap_map.DATA
    d = apply(json.loads(path.read_text(encoding="utf-8")))
    path.write_text(json.dumps(d, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    build_trap_map.build()


if __name__ == "__main__":
    main()
