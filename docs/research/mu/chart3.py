#!/usr/bin/env python3
"""Chart 3: MU price path vs our modeled bottom, with past-cycle paths overlaid
by months after the revenue peak. Data only from mu_data CSVs (+ trade terms)."""
import csv, datetime as dt
from pathlib import Path
import chart_style as mc  # style (rcParams, colors, footer, save)
plt, mdates = mc.plt, mc.mdates
D = Path(__file__).resolve().parent / "data"
P = lambda s: dt.datetime.strptime(s[:10], "%Y-%m-%d")

pts = {}
for r in csv.DictReader(open(f"{D}/mu_cycle.csv")):
    if r["quarter_end"] >= "2025-01-01" and r["price_at_quarter_end"]:
        pts[P(r["quarter_end"])] = float(r["price_at_quarter_end"])
for r in csv.DictReader(open(f"{D}/mu_cycle_turns.csv")):
    if r["cycle"] == "E current" and r["price_date"] >= "2025-01-01":
        pts[P(r["price_date"])] = float(r["price_close"])
ov = list(csv.DictReader(open(f"{D}/cycle_overlay.csv")))
for r in ov:
    if r["cycle"].startswith("2026 current"):
        pts[P(r["date"])] = float(r["close"])
xs = sorted(pts); ys = [pts[x] for x in xs]

anchor_close = [float(r["close"]) for r in ov if r["cycle"].startswith("2026 current") and r["month_offset"] == "0"][0]
anchor_date = dt.datetime(2026, 9, 30)
def addm(d, m):
    y, mo = divmod(d.month - 1 + m, 12); return dt.datetime(d.year + y, mo + 1, 28)
series = {"2018 (FQ4 FY18 revenue peak)": ("2018 (FQ4 FY18", mc.ORANGE), "2022 (FQ3 FY22 revenue peak)": ("2022 (FQ3 FY22", mc.GREEN)}

fig, ax = plt.subplots(figsize=(mc.WIDTH_IN, 6.75))
EXP = dt.datetime(2028, 12, 15); END = dt.datetime(2029, 3, 31)
for lbl, (pref, col) in series.items():
    rows = [r for r in ov if r["cycle"].startswith(pref) and int(r["month_offset"]) <= 9]
    ox = [addm(anchor_date, int(r["month_offset"])) for r in rows]
    oy = [anchor_close * float(r["pct_of_peak_close"]) / 100 for r in rows]
    ax.plot(ox, oy, color=col, lw=1.6, ls=":", label=f"{lbl[:4]} path after revenue peak, scaled")
    i = min(range(len(oy)), key=lambda k: oy[k])
    ax.plot([ox[i]], [oy[i]], "o", color=col, ms=6, mfc="white")
    ax.annotate(f"{lbl[:4]} low: {float(rows[i]['pct_of_peak_close']):.1f}% of peak month,\n+{rows[i]['month_offset']} months",
                (ox[i], oy[i]), xytext=(dt.datetime(2027, 10, 1), 1060 if pref.startswith("2022") else 900), textcoords="data", fontsize=9, color=col,
                bbox=dict(boxstyle="square,pad=0.2", fc="white", ec="none"), arrowprops=dict(arrowstyle="-", color=col, lw=0.8))
ax.plot(xs, ys, color=mc.NAVY, lw=2.4, marker="o", ms=4, label="MU close (quarter-end and dated closes)")
for y, txt, col, ls in [(700, "$700 upper strike", mc.GREY, "--"), (625.33, "Paper trade break-even, $625.33", mc.RED, "--"),
                        (609, "$609 = 2022-size drop (-49.8%) from $1,213.56", mc.BLUE, "-."),
                        (562, "$562 = 2018-size drop (-53.7%) from $1,213.56", mc.BLUE, "-."),
                        (500, "$500 lower strike", mc.GREY, "--")]:
    ax.plot([dt.datetime(2026, 9, 1), EXP], [y, y], color=col, lw=1.2, ls=ls)
    dy = {700: 6, 625.33: 14, 609: -2, 562: -14, 500: -6}[y]
    ax.annotate(txt, (EXP, y), xytext=(-6, dy), textcoords="offset points", ha="right", va="center", fontsize=9, color=col,
                bbox=dict(boxstyle="square,pad=0.1", fc="white", ec="none", alpha=0.85))
ax.axvline(EXP, color=mc.RED, lw=1.2)
ax.text(EXP, 1270, "Expiry Dec 15, 2028  ", ha="right", va="top", fontsize=9, color=mc.RED)
bot = dt.datetime(2028, 12, 25)
ax.plot([bot], [305], marker="D", color="#6B3FA0", ms=10)
ax.plot([xs[-1], bot], [ys[-1], 305], color="#6B3FA0", lw=1.4, ls="--", label="Our modeled path (ESTIMATE)")
ax.annotate("Our modeled bottom: ~$305, late Dec 2028\n(about Dec 25, 10 days after expiry; ESTIMATE)", (bot, 305),
            xytext=(-14, -40), textcoords="offset points", ha="right", fontsize=10, color="#6B3FA0", fontweight="bold")
for d, v, t, off in [(dt.datetime(2026, 6, 25), 1213.56, "High $1,213.56\nJun 25, 2026", (-95, -6)),
                     (dt.datetime(2026, 7, 29), 739.00, "Low $739.00\nJul 29, 2026", (-92, -8)),
                     (dt.datetime(2026, 10, 29), 957.72, "Paper-trade entry $957.72\nOct 29, 2026, 8:32 AM CT", None)]:
    ax.plot([d], [v], "o", color=mc.NAVY, ms=7)
    if off is None:
        ax.annotate(t, (d, v), xytext=(dt.datetime(2025, 7, 15), 1010), textcoords="data", fontsize=9, color=mc.NAVY,
                    arrowprops=dict(arrowstyle="-", color=mc.NAVY, lw=0.8, connectionstyle="arc3,rad=-0.15"))
    else:
        ax.annotate(t, (d, v), xytext=off, textcoords="offset points", fontsize=9, color=mc.NAVY)
ax.set_xlim(dt.datetime(2025, 1, 1), END); ax.set_ylim(0, 1300)
ax.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 7])); ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"${v:,.0f}"))
ax.set_ylabel("MU share price ($)")
ax.set_title("MU price path vs our modeled bottom", pad=14, color=mc.NAVY)
ax.legend(loc="upper left", bbox_to_anchor=(0.36, 0.34), fontsize=8.5)
fig.subplots_adjust(left=0.085, right=0.98, top=0.91, bottom=0.17)
fig.text(0.01, 0.06, "Past-cycle paths are anchored at the revenue-peak quarter (month 0 = month containing the quarter end) and scaled to MU's Sep 30, 2026 close ($1,065.11),\n"
         "the current-cycle anchor (FQ4 FY26), which is PROVISIONAL. Monthly closes. In 2022 the stock fell before the revenue peak, so its path from the anchor is shallow.", fontsize=9, color="#555555")
mc.footer(fig, "Source: Yahoo closes (price); Micron SEC filings (revenue peaks). The bottom point is our estimate, not a forecast.")
mc.save(fig, "03.png")
