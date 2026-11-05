"""Original MU chart style, with repository-relative output and corrected terms."""
from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# 12 x 6.75 in at 100 dpi = 1200 x 675 px
DPI = 100
WIDTH_IN = 12.0
NAVY, BLUE, ORANGE, GREY, RED, GREEN = "#1F3A5F", "#4A7FB5", "#D9822B", "#8A8F98", "#B03A2E", "#2E7D4F"
UNSOURCED_NOTE = "some values unsourced, see report"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "font.size": 12,
    "axes.titlesize": 17,
    "axes.titleweight": "bold",
    "axes.titlelocation": "left",
    "axes.labelsize": 12,
    "axes.edgecolor": "#444444",
    "axes.linewidth": 0.8,
    "axes.spines.top": False,
    "axes.grid": True,
    "grid.color": "#E3E5E8",
    "grid.linewidth": 0.8,
    "xtick.labelsize": 11,
    "ytick.labelsize": 11,
    "legend.fontsize": 11,
    "legend.frameon": False,
    "savefig.facecolor": "white",
    "text.parse_math": False,  # treat "$" literally in labels
})



def footer(fig, text):
    fig.text(0.01, 0.012, text, ha="left", va="bottom", fontsize=10, color="#555555")


def save(fig, fname):
    path = Path(__file__).resolve().parents[3] / "site/charts/mu" / fname
    fig.savefig(path, dpi=DPI, metadata={"Description": "MU original-entry model: $74.666667 debit/share, $7,466.67 maximum loss, $12,533.33 maximum net profit, $625.33 expiry breakeven (rounded)."})
    plt.close(fig)
    print(f"Wrote {path}")
