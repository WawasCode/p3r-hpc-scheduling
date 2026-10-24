"""Thesis figures from a runs.csv: paired lambda sweep and cost/QoS trade-off.

Usage: python plot_thesis_figures.py RUNS_CSV OUT_DIR TAG
Writes OUT_DIR/lambda_sweep_TAG.pdf and OUT_DIR/tradeoff_TAG.pdf (plus .png).
All statistics are paired per (load, seed) against EASY backfilling on the
identical workload; bands are t-based 95% confidence intervals.
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


def load(path):
    by = defaultdict(dict)
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            key = r["policy"] if r["policy"] != "price_aware_preemptive" else float(r["delay_penalty_lambda"])
            by[(r["load_level"], int(r["seed"]))][key] = r
    return by


def paired(by, load_name, lam, f):
    return [f(d[lam], d["easy_backfill"]) for (l, _), d in by.items() if l == load_name and lam in d]


def mean_of(by, load_name, policy, key):
    return fs.ci([float(d[policy][key]) for (l, _), d in by.items() if l == load_name])[0]


def sweep(by, out, tag):
    fig, axes = plt.subplots(2, 2, figsize=(6.3, 5.6))
    panels = [
        (axes[0, 0], "(a) Paid price vs. EASY", "paid price change\nvs. EASY (%)",
         lambda p, e: 100 * (float(p["mean_paid_price_eur_per_mwh"]) / float(e["mean_paid_price_eur_per_mwh"]) - 1)),
        (axes[0, 1], "(b) Mean waiting time vs. EASY", "mean waiting time change\nvs. EASY (h)",
         lambda p, e: float(p["avg_wait_h"]) - float(e["avg_wait_h"])),
        (axes[1, 0], "(c) Deadline misses vs. EASY", "deadline-miss rate change\nvs. EASY (percentage points)",
         lambda p, e: float(p["qos_violation_rate_percent"]) - float(e["qos_violation_rate_percent"])),
        (axes[1, 1], "(d) Suspended job-hours", "suspended time\n(thousand job-hours)",
         lambda p, e: float(p["suspended_job_hours"]) / 1000),
    ]
    xs = list(range(len(fs.LAMBDAS)))
    for ax, text, ylabel, f in panels:
        fs.style(ax)
        ax.set_ylabel(ylabel)
        for load_name in fs.LOADS:
            ms, hs = zip(*(fs.ci(paired(by, load_name, lam, f)) for lam in fs.LAMBDAS))
            fs.line_with_band(ax, xs, ms, hs, fs.COLORS[load_name], fs.MARKERS[load_name], label=load_name)
        if ax is not axes[1, 1]:
            fs.reference_line(ax, 0.0, "EASY")
        fs.lambda_axis(ax, show_label=True)
        fs.title(ax, text)

    # (b) spans hours to hundreds of hours: linear within ±10 h, logarithmic beyond.
    axes[0, 1].set_yscale("symlog", linthresh=10, linscale=1.2)
    axes[0, 1].set_yticks([-500, -100, -10, 0, 10])
    axes[0, 1].yaxis.set_major_formatter(fs.PLAIN)
    axes[1, 1].set_ylim(bottom=0)

    # Direct labels on panel (a), at the price-seeking end where the curves are apart.
    ax = axes[0, 0]
    ends = {name: fs.ci(paired(by, name, 0.0, panels[0][3]))[0] for name in fs.LOADS}
    span = ax.get_ylim()[1] - ax.get_ylim()[0]
    fs.direct_labels(ax, 0, ends, min_gap=0.075 * span)
    ax.set_xlim(-1.75, len(fs.LAMBDAS) - 0.65)
    ax.tick_params(axis="x", labelsize=6.8)

    handles = [(Line2D([], [], color=fs.COLORS[n], marker=fs.MARKERS[n], markersize=4.2, linewidth=1.8,
                       markeredgecolor="white", markeredgewidth=0.7), f"{n} load") for n in fs.LOADS]
    fs.legend_row(fig, handles, y=0.995)
    fig.tight_layout(h_pad=1.6, w_pad=1.4, rect=(0, 0, 1, 0.97))
    fs.save(fig, f"{out}/lambda_sweep_{tag}")


def tradeoff(by, out, tag):
    fig, axes = plt.subplots(2, 2, figsize=(6.3, 5.0))
    for ax, load_name in zip(axes.flat, fs.LOADS):
        fs.style(ax)
        ax.xaxis.grid(True, color=fs.GRID, linewidth=0.6)
        color, marker = fs.COLORS[load_name], fs.MARKERS[load_name]
        pts = [(mean_of(by, load_name, lam, "avg_wait_h"), mean_of(by, load_name, lam, "mean_paid_price_eur_per_mwh"))
               for lam in fs.LAMBDAS]
        ax.plot(*zip(*pts), color=color, linewidth=1.8, marker=marker, markersize=4.6,
                markeredgecolor="white", markeredgewidth=0.7, zorder=3)
        overloaded = load_name in ("high", "mixed")
        zero_label = (7, 0, "left") if load_name == "high" else (-7, 0, "right")
        labels = {0.0: zero_label, 1.0: (-7, 0, "right")} if overloaded else \
                 {0.0: (7, 0, "left"), 0.25: (7, 0, "left"), 1.0: (0, -11, "center")}
        for lam, (dx, dy, ha) in labels.items():
            w, p = pts[fs.LAMBDAS.index(lam)]
            ax.annotate(f"λ={lam:g}", (w, p), xytext=(dx, dy), textcoords="offset points",
                        fontsize=7, color=fs.INK2, va="center", ha=ha)
        base_w = {pol: mean_of(by, load_name, pol, "avg_wait_h") for pol in ("easy_backfill", "fcfs")}
        x_span = max([w for w, _ in pts] + list(base_w.values())) or 1.0
        close = abs(base_w["fcfs"] - base_w["easy_backfill"]) < 0.08 * x_span
        for policy, text, sym, size in (("easy_backfill", "EASY", "*", 11), ("fcfs", "FCFS", "o", 5.5)):
            w, p = mean_of(by, load_name, policy, "avg_wait_h"), mean_of(by, load_name, policy, "mean_paid_price_eur_per_mwh")
            face = fs.INK2 if policy == "easy_backfill" else "white"
            ax.plot([w], [p], marker=sym, markersize=size, color=fs.INK2, markerfacecolor=face,
                    markeredgewidth=1.0, linestyle="none", zorder=4)
            # When the two baselines sit on top of each other, put FCFS's label to the right.
            dx, dy, ha = (9, 0, "left") if (close and policy == "fcfs") else (0, 8, "center")
            ax.annotate(text, (w, p), xytext=(dx, dy), textcoords="offset points", ha=ha,
                        va="center" if dy == 0 else "baseline", fontsize=7, color=fs.INK2)
        ys = [p for _, p in pts]
        lo, hi = min(ys), max(ys + [mean_of(by, load_name, "easy_backfill", "mean_paid_price_eur_per_mwh")])
        pad = max(0.4, 0.12 * (hi - lo))
        ax.set_ylim(lo - pad, hi + 2.2 * pad)
        # The headroom above the data holds the marker labels; keep ticks inside the data range.
        ticks = [t for t in ax.get_yticks() if lo - pad <= t <= hi + pad]
        ax.set_yticks(ticks)
        ax.set_xlim(left=0, right=1.1 * max(w for w, _ in pts + [(mean_of(by, load_name, "fcfs", "avg_wait_h"), 0)]))
        ax.xaxis.set_major_formatter(fs.PLAIN)
        fs.title(ax, f"{load_name} load")
        ax.set_xlabel("mean waiting time (h)")
        ax.set_ylabel("paid price (EUR/MWh)")
    fig.tight_layout(h_pad=1.8, w_pad=1.6)
    fs.save(fig, f"{out}/tradeoff_{tag}")


if __name__ == "__main__":
    runs, out, tag = sys.argv[1:4]
    fs.apply_rc()
    data = load(runs)
    sweep(data, out, tag)
    tradeoff(data, out, tag)
    print("wrote", f"{out}/lambda_sweep_{tag}.pdf", f"{out}/tradeoff_{tag}.pdf")
