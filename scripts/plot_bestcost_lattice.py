"""Figure: the BestCost dynamic-programming table for the chapter 4 example."""
from __future__ import annotations

import math
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch

INK, INK2, GRID, BLUE, ORANGE = "#0b0b0b", "#52514e", "#e6e5e1", "#2a78d6", "#eb6834"
A = [4, 2, 4]
P = [100, 40, 120, 30, 90]


def table():
    m, n = len(A), len(P)
    B = [[math.inf] * (n + 2) for _ in range(m + 2)]
    choice = [[None] * (n + 2) for _ in range(m + 2)]
    for h in range(1, n + 2):
        B[m + 1][h] = 0.0
    for i in range(m, 0, -1):
        for h in range(n, 0, -1):
            if n - h + 1 < m - i + 1:
                continue
            run = A[i - 1] * P[h - 1] + B[i + 1][h + 1]
            idle = B[i][h + 1] if n - h >= m - i + 1 else math.inf
            B[i][h], choice[i][h] = (run, "run") if run <= idle else (idle, "idle")
    return B, choice


def main(out: str) -> None:
    B, choice = table()
    m, n = len(A), len(P)
    fig, ax = plt.subplots(figsize=(6.3, 3.0))
    ax.set_xlim(0.4, n + 1.6)
    ax.set_ylim(m + 1.6, 0.4)
    ax.set_xticks(range(1, n + 2), [f"h={h}\n{P[h-1]}" for h in range(1, n + 1)] + ["h=6\n(end)"], fontsize=8, color=INK2)
    ax.set_yticks(range(1, m + 2), [f"i={i}\nA={A[i-1]}" for i in range(1, m + 1)] + ["i=4\n(done)"], fontsize=8, color=INK2)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    # optimal path from (1,1)
    path = set()
    i, h = 1, 1
    while i <= m and h <= n and choice[i][h]:
        path.add((i, h))
        if choice[i][h] == "run":
            i, h = i + 1, h + 1
        else:
            h += 1
    path.add((i, h))
    for i in range(1, m + 2):
        for h in range(1, n + 2):
            v = B[i][h]
            if v == math.inf:
                continue
            on = (i, h) in path
            ax.add_patch(plt.Rectangle((h - 0.42, i - 0.32), 0.84, 0.64, facecolor=BLUE if on else "white",
                                       edgecolor=BLUE if on else GRID, linewidth=1.0))
            ax.text(h, i, f"{v:.0f}", ha="center", va="center", fontsize=8.5, color="white" if on else INK)
            if i <= m and choice[i][h]:
                if choice[i][h] == "run":
                    ax.add_patch(FancyArrowPatch((h + 0.3, i + 0.28), (h + 0.72, i + 0.7), arrowstyle="-|>", mutation_scale=7,
                                                 color=ORANGE if on else GRID, linewidth=1.0 if on else 0.7))
                else:
                    ax.add_patch(FancyArrowPatch((h + 0.44, i), (h + 0.56, i), arrowstyle="-|>", mutation_scale=7,
                                                 color=ORANGE if on else GRID, linewidth=1.0 if on else 0.7))
    ax.text(0.45, 0.55, "cell value B(i, h): cheapest cost of placing steps i..3 into hours h..5 (active nodes × EUR/MWh)",
            fontsize=8, color=INK2, va="center")
    ax.set_xlabel("window hour h, with its price P(h) in EUR/MWh", fontsize=8, color=INK2)
    ax.set_ylabel("profile step i, with its active nodes A(i)", fontsize=8, color=INK2)
    fig.tight_layout()
    for ext in ("pdf", "png"):
        fig.savefig(f"{out}/bestcost_lattice.{ext}", dpi=200, bbox_inches="tight")
    print("B(1,1) =", B[1][1], "path", sorted(path))


if __name__ == "__main__":
    main(sys.argv[1])
