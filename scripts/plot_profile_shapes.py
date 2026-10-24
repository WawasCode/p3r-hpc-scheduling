"""Figure: the seven synthetic profile shape families (Section 3.2).

Usage: python plot_profile_shapes.py OUT_DIR
Draws each shape for one example job with n_j = 8 requested nodes and a
runtime of 48 h, using the same shape rules as the workload generator.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

import figstyle as fs  # noqa: E402
from run_parallel_policy_report import make_profile  # noqa: E402

SHAPES = [("flat", "flat"), ("front_loaded", "front-loaded"), ("back_loaded", "back-loaded"), ("valley", "valley"),
          ("peak", "peak"), ("ramp_up", "ramp-up"), ("ramp_down", "ramp-down")]
NODES, HOURS = 8, 48
ACTIVE = "#2a78d6"


def main(out: str) -> None:
    fs.apply_rc()
    fig, axes = plt.subplots(2, 4, figsize=(6.3, 3.6))
    for ax, (shape, name) in zip(axes.flat, SHAPES):
        fs.style(ax)
        active = make_profile(shape, HOURS, NODES)
        hours = list(range(HOURS + 1))
        ax.step(hours, active + [active[-1]], where="post", color=ACTIVE, linewidth=1.8)
        ax.axhline(NODES, color=fs.MUTED, linewidth=1.0, linestyle=(0, (3, 2)))
        ax.set_xlim(0, HOURS)
        ax.set_ylim(0, NODES * 1.15)
        ax.set_xticks([0, 24, 48])
        ax.set_yticks([0, NODES // 2, NODES])
        ax.set_xlabel("runtime hour (h)")
        ax.set_ylabel("nodes")
        fs.title(ax, name)
    legend_ax = axes.flat[-1]
    legend_ax.axis("off")
    legend_ax.legend(
        [Line2D([], [], color=fs.MUTED, linewidth=1.0, linestyle=(0, (3, 2))), Line2D([], [], color=ACTIVE, linewidth=1.8)],
        ["reserved nodes $n_j$", "active nodes $a_j(k)$"], loc="center", frameon=False, fontsize=8)
    fig.tight_layout(h_pad=1.4, w_pad=0.8)
    fs.save(fig, f"{out}/profile_shapes")
    print("wrote", f"{out}/profile_shapes.pdf")


if __name__ == "__main__":
    main(sys.argv[1])
