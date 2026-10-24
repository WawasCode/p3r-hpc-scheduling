"""Shared look for the thesis figures.

Colors are the first slots of a colorblind-validated categorical palette, in
fixed order. Two of them sit below 3:1 contrast on white, so every figure
labels its series directly, and each series also has its own marker shape so
the figures survive grayscale printing.
"""
from __future__ import annotations

import math
import statistics as st

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

LOADS = ["low", "medium", "high", "mixed"]
LAMBDAS = [0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
COLORS = {"low": "#2a78d6", "medium": "#eb6834", "high": "#1baf7a", "mixed": "#eda100"}
MARKERS = {"low": "o", "medium": "s", "high": "^", "mixed": "D"}
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#8a8984", "#e6e5e1"
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 9: 2.262, 19: 2.093}


def apply_rc() -> None:
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8,
        "axes.titlesize": 9,
        "axes.labelsize": 8,
        "xtick.labelsize": 7.5,
        "ytick.labelsize": 7.5,
        "axes.edgecolor": GRID,
        "axes.labelcolor": INK2,
        "xtick.color": INK2,
        "ytick.color": INK2,
        "xtick.major.size": 0,
        "ytick.major.size": 0,
        "axes.titlepad": 6,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.03,
        "pdf.fonttype": 42,
    })


def ci(values: list[float]) -> tuple[float, float]:
    n = len(values)
    mean = st.mean(values)
    if n < 2:
        return mean, 0.0
    return mean, T975.get(n - 1, 2.0) * st.stdev(values) / math.sqrt(n)


def style(ax, ygrid: bool = True) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    if ygrid:
        ax.yaxis.grid(True, color=GRID, linewidth=0.6)
    ax.set_axisbelow(True)


def title(ax, text: str) -> None:
    ax.set_title(text, loc="left", color=INK)


def line_with_band(ax, xs, means, halfwidths, color, marker, label=None):
    lo = [m - h for m, h in zip(means, halfwidths)]
    hi = [m + h for m, h in zip(means, halfwidths)]
    ax.fill_between(xs, lo, hi, color=color, alpha=0.14, linewidth=0)
    ax.plot(xs, means, color=color, linewidth=1.8, marker=marker, markersize=4.2,
            markeredgecolor="white", markeredgewidth=0.7, label=label, zorder=3)


def reference_line(ax, y: float = 0.0, text: str | None = "EASY") -> None:
    ax.axhline(y, color=MUTED, linewidth=0.9, linestyle=(0, (3, 2)), zorder=1)
    if text:
        ax.annotate(text, (1.0, y), xycoords=("axes fraction", "data"), xytext=(2, 0),
                    textcoords="offset points", va="center", ha="left", fontsize=7, color=MUTED)


def spread_labels(positions: dict[str, float], min_gap: float) -> dict[str, float]:
    """Nudge label y positions apart so none are closer than min_gap."""
    order = sorted(positions, key=positions.get)
    placed: dict[str, float] = {}
    last = -math.inf
    for key in order:
        y = max(positions[key], last + min_gap)
        placed[key] = y
        last = y
    shift = (sum(positions.values()) - sum(placed.values())) / len(placed)
    return {k: v + shift for k, v in placed.items()}


def direct_labels(ax, x: float, positions: dict[str, float], min_gap: float,
                  ha: str = "right", dx: float = -7) -> None:
    """Series names next to the line ends, in ink; the line itself carries the color."""
    for key, y in spread_labels(positions, min_gap).items():
        ax.annotate(key, (x, y), xytext=(dx, 0), textcoords="offset points", ha=ha, va="center",
                    fontsize=7.5, color=INK)


def lambda_axis(ax, show_label: bool = True) -> list[int]:
    xs = list(range(len(LAMBDAS)))
    ax.set_xticks(xs, [f"{v:g}" for v in LAMBDAS])
    ax.set_xlim(-0.35, len(LAMBDAS) - 0.65)
    if show_label:
        ax.set_xlabel("urgency parameter λ (unitless)")
    return xs


def plain_number(value: float, _pos=None) -> str:
    if value == 0:
        return "0"
    text = f"{value:,.0f}" if abs(value) >= 1 else f"{value:g}"
    return text.replace("-", "−")


PLAIN = FuncFormatter(plain_number)


def legend_row(fig, handles_labels, y: float = 1.0) -> None:
    handles, labels = zip(*handles_labels)
    fig.legend(handles, labels, loc="lower center", bbox_to_anchor=(0.5, y), ncol=len(labels),
               frameon=False, fontsize=8, handlelength=2.2, columnspacing=1.6)


def save(fig, path_without_ext: str) -> None:
    for ext in ("pdf", "png"):
        fig.savefig(f"{path_without_ext}.{ext}", dpi=220)
    plt.close(fig)
