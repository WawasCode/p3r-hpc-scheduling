"""Figure: paid-price reduction vs lambda for the winter window, the summer
window, and the full year, at low and medium load. Paired against EASY.

Usage: python plot_seasonal.py WINTER_RUNS SUMMER_RUNS FULL_RUNS OUT_DIR
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import figstyle as fs  # noqa: E402

# Three series: the first three palette slots, which stay distinguishable in every pairing.
SERIES = [("winter window (Jan–Feb)", "winter", "#2a78d6", "o"),
          ("summer window (Jul–Aug)", "summer", "#eb6834", "s"),
          ("full year", "full year", "#1baf7a", "^")]


def by_of(path):
    by = defaultdict(dict)
    for r in csv.DictReader(open(path, newline="")):
        k = r["policy"] if r["policy"] != "price_aware_preemptive" else float(r["delay_penalty_lambda"])
        by[(r["load_level"], int(r["seed"]))][k] = r
    return by


def reduction(by, load, lam):
    return fs.ci([100 * (float(d[lam]["mean_paid_price_eur_per_mwh"]) / float(d["easy_backfill"]["mean_paid_price_eur_per_mwh"]) - 1)
                  for (l, _), d in by.items() if l == load])


def main(winter, summer, full, out):
    fs.apply_rc()
    data = [by_of(winter), by_of(summer), by_of(full)]
    fig, axes = plt.subplots(1, 2, figsize=(6.3, 3.1))
    xs = list(range(len(fs.LAMBDAS)))
    for ax, load in zip(axes, ["low", "medium"]):
        fs.style(ax)
        ends = {}
        for (_, short, color, marker), by in zip(SERIES, data):
            ms, hs = zip(*(reduction(by, load, lam) for lam in fs.LAMBDAS))
            fs.line_with_band(ax, xs, ms, hs, color, marker)
            ends[short] = ms[0]
        fs.reference_line(ax, 0.0, "EASY" if ax is axes[1] else None)
        fs.lambda_axis(ax)
        fs.title(ax, f"{load} load")
        ax.set_xlim(-2.5, len(fs.LAMBDAS) - 0.65)
        span = 34
        fs.direct_labels(ax, 0, ends, min_gap=0.075 * span)
    # Common lower limit from the data, including the confidence bands.
    lowest = min(a.dataLim.y0 for a in axes)
    for ax in axes:
        ax.set_ylabel("paid price change vs. EASY (%)")
        ax.set_ylim(lowest - 1.5, 2)
    handles = [(Line2D([], [], color=c, marker=m, markersize=4.2, linewidth=1.8, markeredgecolor="white",
                       markeredgewidth=0.7), label) for label, _, c, m in SERIES]
    fs.legend_row(fig, handles, y=0.99)
    fig.tight_layout(w_pad=1.4, rect=(0, 0, 1, 0.93))
    fs.save(fig, f"{out}/seasonal")
    print("wrote", f"{out}/seasonal.pdf")


if __name__ == "__main__":
    main(*sys.argv[1:5])
