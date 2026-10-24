"""Aggregate per-seed runs into means with 95% confidence intervals.

Reads a runs.csv written by run_parallel_policy_report.py and prints, per
load level and policy variant, the mean and half-width of a t-based 95%
confidence interval for the key thesis metrics. Optionally writes a LaTeX
table. Pure standard library.
"""
from __future__ import annotations

import argparse
import csv
import math
import statistics as st
from collections import defaultdict

# two-sided t quantiles (0.975) for n-1 degrees of freedom, n = 2..30
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 29: 2.045}

METRICS = [
    ("mean_paid_price_eur_per_mwh", "paid EUR/MWh"),
    ("total_cost_eur", "cost EUR"),
    ("cost_per_completed_job_eur", "cost/job EUR"),
    ("scheduled_jobs", "completed"),
    ("qos_violation_rate_percent", "QoS %"),
    ("avg_wait_h", "wait h"),
    ("p95_wait_h", "p95 wait h"),
    ("avg_bounded_slowdown", "slowdown"),
    ("utilization", "util"),
    ("suspended_job_hours", "susp h"),
    ("preempted_jobs", "preempted"),
]
LOADS = ["low", "medium", "high", "mixed"]


def ci(values: list[float]) -> tuple[float, float]:
    n = len(values)
    m = st.mean(values)
    if n < 2:
        return m, float("nan")
    t = T975.get(n - 1) or T975[max(k for k in T975 if k <= n - 1)]
    return m, t * st.stdev(values) / math.sqrt(n)


def variant(row: dict[str, str]) -> str:
    if row["policy"] == "price_aware_preemptive":
        return f"lambda={float(row['delay_penalty_lambda']):g}"
    return row["policy"]


def load_runs(path: str) -> dict[tuple[str, str], list[dict[str, str]]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if "qos_violation_rate_percent" not in row:
                row["qos_violation_rate_percent"] = str(100.0 * float(row["qos_violations"]) / max(1, float(row["total_jobs"])))
            if "cost_per_completed_job_eur" not in row:
                row["cost_per_completed_job_eur"] = str(float(row["total_cost_eur"]) / max(1, float(row["scheduled_jobs"])))
            groups[(row["load_level"], variant(row))].append(row)
    return groups


def variant_order(v: str) -> tuple[int, float]:
    if v == "fcfs":
        return (0, 0.0)
    if v == "easy_backfill":
        return (1, 0.0)
    return (2, float(v.split("=")[1]))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs_csv")
    ap.add_argument("--metrics", default=",".join(m for m, _ in METRICS[:6]))
    ap.add_argument("--latex", help="write a LaTeX table to this path")
    args = ap.parse_args()
    wanted = [(m, lbl) for m, lbl in METRICS if m in args.metrics.split(",")]
    groups = load_runs(args.runs_csv)
    lines = []
    header = f"{'load':7} {'variant':14} n  " + "  ".join(f"{lbl:>16}" for _, lbl in wanted)
    print(header)
    for load in LOADS:
        for (l, v), rows in sorted(((k, r) for k, r in groups.items() if k[0] == load), key=lambda kv: variant_order(kv[0][1])):
            cells = []
            tex = []
            for m, _ in wanted:
                mean, hw = ci([float(r[m]) for r in rows])
                cells.append(f"{mean:9.2f} ± {hw:5.2f}")
                tex.append(f"{mean:.1f} $\\pm$ {hw:.1f}")
            print(f"{load:7} {v:14} {len(rows):<2} " + "  ".join(f"{c:>16}" for c in cells))
            lines.append(f"{load} & {v.replace('lambda=', '$\\lambda=$')} & " + " & ".join(tex) + r" \\")
        print()
    if args.latex:
        with open(args.latex, "w") as f:
            f.write("\\begin{tabular}{@{}ll" + "r" * len(wanted) + "@{}}\n\\toprule\n")
            f.write("Load & Policy & " + " & ".join(lbl for _, lbl in wanted) + r" \\" + "\n\\midrule\n")
            f.write("\n".join(lines) + "\n\\bottomrule\n\\end{tabular}\n")


if __name__ == "__main__":
    main()
