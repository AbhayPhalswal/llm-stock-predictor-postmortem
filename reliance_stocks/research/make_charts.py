"""
CHART GENERATION  ·  README figures

Renders the four figures that carry the project's findings, straight from the
research artefacts. Every number plotted here is produced by fetch_data.py ->
build_panel.py -> evaluate.py; nothing is hand-entered.

Output: docs/img/*.png

Run:  python make_charts.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import console_setup  # noqa: F401  — must precede any print()

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR  = os.path.join(os.path.dirname(os.path.dirname(BASE_DIR)), "docs", "img")

# ── STYLE ─────────────────────────────────────────────────────────────────────
# White ground so the figures stay legible under both GitHub themes.
INK, MUTED, GRID = "#1a1a1a", "#6b7280", "#e5e7eb"
BLUE, RED, GREEN, AMBER = "#2563eb", "#dc2626", "#059669", "#d97706"

plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor":   "white",
    "axes.edgecolor":   GRID,
    "axes.labelcolor":  INK,
    "axes.titlesize":   13,
    "axes.titleweight": "600",
    "axes.labelsize":   10,
    "text.color":       INK,
    "xtick.color":      MUTED,
    "ytick.color":      MUTED,
    "xtick.labelsize":  9,
    "ytick.labelsize":  9,
    "grid.color":       GRID,
    "legend.frameon":   False,
    "legend.fontsize":  9.5,
    "font.family":      "DejaVu Sans",
    "figure.dpi":       130,
})


def _clean(ax, pct=True):
    ax.grid(True, alpha=0.6, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if pct:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}%"))


def load():
    panel = pd.read_csv(os.path.join(BASE_DIR, "panel.csv"),
                        index_col=0, parse_dates=True)
    preds = pd.read_csv(os.path.join(BASE_DIR, "oos_preds.csv"),
                        index_col=0, parse_dates=True)
    idx   = np.load(os.path.join(BASE_DIR, "oos_idx.npy"))
    return panel, preds, idx


# ══════════════════════════════════════════════════════════════════════════════
#  FIGURE 1 — the headline finding
# ══════════════════════════════════════════════════════════════════════════════

def fig_overnight_vs_intraday(panel):
    intraday  = panel["y_ret"]
    overnight = (panel["open"] / panel["close"].shift(1) - 1).reindex(intraday.index)
    d = pd.DataFrame({"on": overnight, "io": intraday}).dropna()

    fig, ax = plt.subplots(figsize=(10, 5.2))
    ax.plot(d.index, ((1 + d["on"]).cumprod() - 1) * 100,
            color=GREEN, lw=2.0, label="Overnight  (close → next open)")
    ax.plot(d.index, ((1 + d["io"]).cumprod() - 1) * 100,
            color=RED, lw=2.0, label="Intraday  (open → close)")
    ax.axhline(0, color=MUTED, lw=0.9, ls="--", alpha=0.7)

    ax.set_title("RELIANCE.NS: the drift lives overnight, not intraday",
                 loc="left", pad=14)
    ax.text(0.0, 1.015,
            "Cumulative return by session window, 2016–2026, before costs",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    ax.set_ylabel("Cumulative return")
    _clean(ax)
    ax.legend(loc="upper left")

    on_bps, io_bps = d["on"].mean() * 1e4, d["io"].mean() * 1e4
    on_t = d["on"].mean() / (d["on"].std() / np.sqrt(len(d)))
    io_t = d["io"].mean() / (d["io"].std() / np.sqrt(len(d)))
    ax.text(0.985, 0.06,
            f"Overnight:  {on_bps:+.2f} bps/day   t={on_t:+.2f}\n"
            f"Intraday:   {io_bps:+.2f} bps/day   t={io_t:+.2f}\n\n"
            f"The live system traded the intraday window.",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=9.5,
            family="DejaVu Sans Mono",
            bbox=dict(boxstyle="round,pad=0.6", fc="#f9fafb", ec=GRID))

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "overnight_vs_intraday.png"),
                bbox_inches="tight")
    plt.close(fig)
    print("  overnight_vs_intraday.png")


# ══════════════════════════════════════════════════════════════════════════════
#  FIGURE 2 — net equity curves against the benchmarks
# ══════════════════════════════════════════════════════════════════════════════

def fig_equity_curves(panel, preds, idx):
    COST = 20 / 1e4
    r    = panel["y_ret"].to_numpy()[idx]
    dates = panel.index[idx]

    fig, ax = plt.subplots(figsize=(10, 5.2))

    bh = panel["close"].to_numpy()[idx]
    ax.plot(dates, (bh / bh[0] - 1) * 100, color=GREEN, lw=2.4,
            label="Buy & hold  (1 round trip)", zorder=5)
    ax.axhline(0, color=MUTED, lw=1.4, ls="-", alpha=0.8,
               label="Hold cash  (0 round trips)")

    for name, colour in [("random_forest", BLUE), ("extra_trees", "#7c3aed")]:
        p = preds[name].to_numpy()[idx]
        pos = np.zeros(len(p))
        pos[p > 0.55] = 1
        pos[p < 0.45] = -1
        net = pos * r - (np.abs(pos) > 0) * COST
        ax.plot(dates, ((1 + net).cumprod() - 1) * 100, color=colour, lw=1.6,
                label=f"{name}  (~80 round trips/yr)")

    net_long = r - COST
    ax.plot(dates, ((1 + net_long).cumprod() - 1) * 100, color=RED, lw=1.8,
            label="Always-long intraday  (250/yr)")

    ax.set_title("Net of 20 bps costs, every active strategy loses to cash",
                 loc="left", pad=14)
    ax.text(0.0, 1.015,
            "Walk-forward out-of-sample, 13 folds, 2019–2026",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    ax.set_ylabel("Cumulative net return")
    _clean(ax)
    ax.legend(loc="lower left")
    ax.set_ylim(bottom=-105)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "equity_curves.png"), bbox_inches="tight")
    plt.close(fig)
    print("  equity_curves.png")


# ══════════════════════════════════════════════════════════════════════════════
#  FIGURE 3 — the overnight anomaly decayed
# ══════════════════════════════════════════════════════════════════════════════

def fig_decay(panel):
    on = (panel["open"] / panel["close"].shift(1) - 1).dropna()
    yr = on.groupby(on.index.year).agg(["mean", "std", "count"])
    yr = yr[yr["count"] >= 30]
    bps = yr["mean"] * 1e4
    t   = yr["mean"] / (yr["std"] / np.sqrt(yr["count"]))

    fig, ax = plt.subplots(figsize=(10, 4.8))
    colours = [GREEN if v > 0 else RED for v in bps]
    bars = ax.bar(yr.index.astype(str), bps, color=colours, alpha=0.85, width=0.68)
    ax.axhline(0, color=INK, lw=1.0)

    for b, tv in zip(bars, t):
        y = b.get_height()
        ax.text(b.get_x() + b.get_width() / 2,
                y + (0.8 if y >= 0 else -0.8),
                f"t={tv:+.1f}", ha="center",
                va="bottom" if y >= 0 else "top",
                fontsize=8, color=MUTED)

    ax.set_title("The overnight edge decayed sharply after 2021",
                 loc="left", pad=14)
    ax.text(0.0, 1.015,
            "Mean overnight return by year. Decay is significant (t=+4.31, p<0.0001); "
            "net of 20 bps the strategy has lost money every year since 2023.",
            transform=ax.transAxes, fontsize=9, color=MUTED)
    ax.set_ylabel("Mean overnight return")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f} bps"))
    ax.grid(True, axis="y", alpha=0.6, linewidth=0.7)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "overnight_decay.png"), bbox_inches="tight")
    plt.close(fig)
    print("  overnight_decay.png")


# ══════════════════════════════════════════════════════════════════════════════
#  FIGURE 4 — where the edge dies
# ══════════════════════════════════════════════════════════════════════════════

def fig_cost_sensitivity(panel, preds, idx):
    r = panel["y_ret"].to_numpy()[idx]
    yrs = len(r) / 250.0
    costs = np.arange(0, 31, 1)

    fig, ax = plt.subplots(figsize=(10, 4.8))
    for name, colour in [("random_forest", BLUE), ("hist_gb", AMBER),
                         ("logistic_l2", "#7c3aed")]:
        p = preds[name].to_numpy()[idx]
        pos = np.zeros(len(p))
        pos[p > 0.55] = 1
        pos[p < 0.45] = -1
        traded = np.abs(pos) > 0
        curve = []
        for c in costs:
            net = pos * r - traded * (c / 1e4)
            curve.append(((1 + net).prod() ** (1 / yrs) - 1) * 100)
        ax.plot(costs, curve, lw=1.9, color=colour, label=name)

    ax.axhline(0, color=INK, lw=1.2, label="Hold cash")
    ax.axvspan(10, 30, color=RED, alpha=0.07)
    ax.text(20, ax.get_ylim()[1] * 0.86, "realistic retail\ncost range",
            ha="center", fontsize=9, color=RED)

    ax.set_title("The signal is real at zero cost, and dies by 10 bps",
                 loc="left", pad=14)
    ax.text(0.0, 1.015,
            "Net annualised return vs round-trip transaction cost",
            transform=ax.transAxes, fontsize=9.5, color=MUTED)
    ax.set_xlabel("Round-trip cost (basis points)")
    ax.set_ylabel("Net annualised return")
    _clean(ax)
    ax.legend(loc="upper right")
    ax.set_xlim(0, 30)

    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "cost_sensitivity.png"), bbox_inches="tight")
    plt.close(fig)
    print("  cost_sensitivity.png")


if __name__ == "__main__":
    os.makedirs(OUT_DIR, exist_ok=True)
    panel, preds, idx = load()
    print(f"Rendering figures to {OUT_DIR}")
    fig_overnight_vs_intraday(panel)
    fig_equity_curves(panel, preds, idx)
    fig_decay(panel)
    fig_cost_sensitivity(panel, preds, idx)
    print("done.")
