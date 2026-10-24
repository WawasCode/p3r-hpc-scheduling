"""Figure: the 2024 SMARD DE/LU hourly price trace with two enlarged weeks."""
from __future__ import annotations

import csv
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

INK, INK2, GRID, BLUE = "#0b0b0b", "#52514e", "#e6e5e1", "#2a78d6"


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def main(csv_path: str, out: str) -> None:
    ts, p = [], []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            ts.append(datetime.strptime(r["timestamp_utc"], "%Y-%m-%dT%H:%M:%SZ"))
            p.append(float(r["price_eur_per_mwh"]))
    fig = plt.figure(figsize=(6.3, 4.8))
    gs = fig.add_gridspec(2, 2, height_ratios=[1.4, 1], hspace=0.7, wspace=0.35)
    top = fig.add_subplot(gs[0, :])
    style(top)
    top.plot(ts, p, color=BLUE, linewidth=0.35)
    top.axhline(0, color=INK2, linewidth=0.6, linestyle=":")
    top.set_title("(a) Hourly day-ahead price, DE/LU, 2024", fontsize=8.5, color=INK, loc="left")
    top.set_ylabel("price (EUR/MWh)", fontsize=8, color=INK2)
    top.set_xlabel("month of 2024", fontsize=8, color=INK2)
    top.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    top.set_ylim(-150, 500)
    for i, (start, label) in enumerate(((datetime(2024, 1, 15), "(b) week of 15 January 2024"), (datetime(2024, 7, 15), "(c) week of 15 July 2024"))):
        ax = fig.add_subplot(gs[1, i])
        style(ax)
        idx = [k for k, t in enumerate(ts) if 0 <= (t - start).total_seconds() < 7 * 86400]
        ax.plot([ts[k] for k in idx], [p[k] for k in idx], color=BLUE, linewidth=1.2)
        ax.axhline(0, color=INK2, linewidth=0.6, linestyle=":")
        ax.set_title(label, fontsize=8.5, color=INK, loc="left")
        ax.set_ylabel("price (EUR/MWh)", fontsize=8, color=INK2)
        ax.set_xlabel("day of week (UTC)", fontsize=8, color=INK2)
        ax.xaxis.set_major_locator(mdates.DayLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%a"))
        ax.set_ylim(-100, 250)
        top.axvspan(start, ts[idx[-1]], color=BLUE, alpha=0.12, linewidth=0)
    for ext in ("pdf", "png"):
        fig.savefig(f"{out}/price_trace_2024.{ext}", dpi=200, bbox_inches="tight")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
