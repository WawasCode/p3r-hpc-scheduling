"""LaTeX results table (means with 95% CIs) from a runs.csv.

Usage: python make_results_table.py RUNS_CSV OUT_TEX
"""
from __future__ import annotations

import csv
import math
import statistics as st
import sys
from collections import defaultdict

COLS = [("mean_paid_price_eur_per_mwh", 1), ("scheduled_jobs", 0), ("qos_violation_rate_percent", 1),
        ("avg_wait_h", 1), ("p95_wait_h", 0), ("suspended_job_hours", 0)]
ORDER = ["FCFS", "EASY", "$\\lambda=0$", "$\\lambda=0.1$", "$\\lambda=0.25$", "$\\lambda=0.5$", "$\\lambda=1$"]


def ci(v):
    m = st.mean(v)
    return m, 2.262 * st.stdev(v) / math.sqrt(len(v))


def main(runs: str, out: str) -> None:
    g = defaultdict(list)
    for r in csv.DictReader(open(runs, newline="")):
        v = "FCFS" if r["policy"] == "fcfs" else ("EASY" if r["policy"] == "easy_backfill" else f"$\\lambda={float(r['delay_penalty_lambda']):g}$")
        g[(r["load_level"], v)].append(r)
    lines = ["\\begin{tabular}{@{}llrrrrrr@{}}", "\\toprule",
             "Load & Policy & Paid price & Completed & QoS viol. & Mean wait & p95 wait & Suspended \\\\",
             " & & (EUR/MWh) & (jobs) & (\\%) & (h) & (h) & (job-h) \\\\", "\\midrule"]
    for load in ["low", "medium", "high", "mixed"]:
        for i, v in enumerate(ORDER):
            cells = []
            for c, d in COLS:
                m, h = ci([float(r[c]) for r in g[(load, v)]])
                cells.append(f"{m:.{d}f} $\\pm$ {h:.{d}f}")
            lines.append(f"{load if i == 0 else ''} & {v} & " + " & ".join(cells) + " \\\\")
        if load != "mixed":
            lines.append("\\addlinespace")
    lines += ["\\bottomrule", "\\end{tabular}"]
    open(out, "w").write("\n".join(lines) + "\n")
    print("wrote", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
