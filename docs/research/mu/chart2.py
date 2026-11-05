#!/usr/bin/env python3
"""Chart 2 v2: where the next downturn could bottom vs today. Data from jg_trough_model.csv
(floor_low/floor_high, no-downturn implied price) + paper-trade terms ($700/$500 strikes, $625.33 break-even)."""
import csv
from pathlib import Path
import chart_style as mc
plt = mc.plt
# NOTE: the 'neutral' row of jg_trough_model.csv carries one more field than the header (29 vs 28), so named lookups are shifted
# by one from 'floor_pb' on. Read floor_low/floor_high as the two fields after the header's floor_low position.
raw = list(csv.reader(open(Path(__file__).resolve().parent / "data/jg_trough_model.csv"))); hdr = raw[0]
rows = {r[0].split()[0]: r for r in raw[1:]}
iL = hdr.index("floor_low")
def f(c, k):
    r = rows[c]
    if k == "implied_price_fy28": return float([v for v in r if v][-1])
    # floor_low repeats floor_ps; floor_high follows it. Locate that repeated pair (robust to the shift).
    j = next(i for i in range(iL - 4, len(r) - 2) if r[i] and r[i] == r[i + 1])
    if k == "floor_low": return float(r[j + 1])
    if k == "floor_high": return float(r[j + 2])
    return float([v for v in r if v][-1])  # implied_price_fy28, last field
TODAY = 983.23  # Oct 28, 2026 close (FACT, Yahoo), the page's reference price
lo, hi = f("neutral", "floor_low"), f("neutral", "floor_high"); mid = (lo + hi) / 2
nd = f("no", "implied_price_fy28")
fig, ax = plt.subplots(figsize=(mc.WIDTH_IN, 6.75))
Y = {"today": 4, "nd": 3, "base": 2, "bull": 1, "bear": 0.4}
ax.barh(Y["base"], hi - lo, left=lo, height=0.42, color=mc.NAVY, alpha=0.85)
ax.plot([mid], [Y["base"]], "D", color="#6B3FA0", ms=12, zorder=5)
ax.annotate(f"Base-case bottom ~${int(mid + 0.5):,}, late Dec 2028 (ESTIMATE)\nrange ${lo:,.0f}–${hi:,.0f} from past-low price-to-sales and price-to-book",
            (hi, Y["base"]), xytext=(10, 0), textcoords="offset points", va="center", fontsize=10, color=mc.NAVY, fontweight="bold", bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
for c, lab in (("bull", "Bull stress test"), ("bear", "Bear stress test")):
    a, b = f(c, "floor_low"), f(c, "floor_high")
    ax.barh(Y[c], b - a, left=a, height=0.18, color=mc.GREY, alpha=0.7)
    ax.annotate(f"{lab}: ${a:,.0f}–${b:,.0f} (side note, ESTIMATE)", (b, Y[c]), xytext=(8, 0), textcoords="offset points", va="center", fontsize=9, color="#555555", bbox=dict(boxstyle="square,pad=0.15", fc="white", ec="none"))
ax.plot([TODAY], [Y["today"]], "o", color=mc.NAVY, ms=11)
ax.annotate(f"Oct 28, 2026 close ${TODAY:,.2f} (FACT)", (TODAY, Y["today"]), xytext=(0, 14), textcoords="offset points", ha="center", va="bottom", fontsize=10, color=mc.NAVY)
ax.plot([nd], [Y["nd"]], "D", color=mc.NAVY, mfc="white", ms=11, mew=1.8)
ax.annotate(f"No downturn through fiscal 2028: ~${nd:,.0f}\n(not a bottom; FY28 consensus × today's forward P/E, INFERENCE)", (nd, Y["nd"]),
            xytext=(-14, 0), textcoords="offset points", ha="right", va="center", fontsize=9.5, color=mc.NAVY)
for x, t, col in ((700, "$700 upper strike", mc.GREY), (625.33, "$625.33 break-even", mc.RED), (500, "$500 lower strike", mc.GREY)):
    ax.axvline(x, color=col, lw=1.2, ls="--", zorder=1)
    ax.text(x - 4, 4.62, t, rotation=90, ha="right", va="top", fontsize=9, color=col)
ax.set_xlim(0, 1300); ax.set_ylim(0, 4.7); ax.set_yticks([])
ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
ax.set_xlabel("MU share price ($)")
ax.set_title("Where the next downturn could bottom vs today", pad=14, color=mc.NAVY)
fig.subplots_adjust(left=0.03, right=0.98, top=0.91, bottom=0.2)
fig.text(0.01, 0.07, "Paper trade: Dec 15, 2028 $700/$500 put spread; it earns a net profit below $625.33 at expiry. Base-case bottom date is about 3.8 months after the modeled\n"
         "fiscal 2028 revenue peak. Bear and bull cases are stress tests, shown small for range only.", fontsize=9, color="#555555")
mc.footer(fig, "Source: Micron SEC filings and Q4 FY26 prepared remarks; Yahoo prices and analyst consensus (REPORTED). Bottoms are estimates, not forecasts.")
mc.save(fig, "02.png")
