"""LaTeX what-if table for the 6,600-core cluster (Section 6.2) from a runs.csv.

Usage: python make_whatif_table.py RUNS_CSV OUT_TEX

saving per year = P_full * u * T * p_mean * r * c, with u the mean active
utilization (active node-hours over N * T under EASY) and r the paired
paid-price reduction of the proposed policy at lambda = 0, both measured at
low and medium load. P_full, p_mean, and c are assumptions.
"""
from __future__ import annotations

import csv
import statistics as st
import sys
from collections import defaultdict

CORES = 6600
WATTS_PER_CORE = (5, 8, 12)
CHECKPOINTABLE = (1.0, 0.5)
HOURS = 8784
MEAN_PRICE = 78.5  # EUR/MWh, 2024 SMARD DE/LU


def measured(path):
    by = defaultdict(dict)
    for r in csv.DictReader(open(path, newline="")):
        k = r["policy"] if r["policy"] != "price_aware_preemptive" else float(r["delay_penalty_lambda"])
        by[(r["load_level"], int(r["seed"]))][k] = r
    out = {}
    for load in ("low", "medium"):
        rows = [d for (l, _), d in by.items() if l == load]
        easy = [d["easy_backfill"] for d in rows]
        u = st.mean(float(e["active_node_hours"]) / (float(e["capacity_nodes"]) * float(e["simulation_horizon_h"])) for e in easy)
        r = st.mean(1 - float(d[0.0]["mean_paid_price_eur_per_mwh"]) / float(d["easy_backfill"]["mean_paid_price_eur_per_mwh"]) for d in rows)
        out[load] = (u, r)
    return out


def main(runs, out_path):
    pairs = measured(runs)
    lines = [r"\begin{tabular}{@{}rrrrrrr@{}}", r"\toprule",
             r"Power & Full-load & Active & Price & Checkpointable & Active energy & Saving \\",
             r"(W/core) & power (kW) & utilization & reduction & share & (MWh/yr) & (kEUR/yr) \\",
             r"\midrule"]
    for watts in WATTS_PER_CORE:
        full_kw = CORES * watts / 1000
        for load in ("low", "medium"):
            u, r = pairs[load]
            energy = full_kw * u * HOURS / 1000
            for c in CHECKPOINTABLE:
                saving = energy * MEAN_PRICE * r * c / 1000
                lines.append(f"{watts} & {full_kw:.0f} & {u:.2f} & {100 * r:.0f}\\% & {100 * c:.0f}\\% & {energy:.0f} & {saving:.1f} \\\\")
    lines += [r"\bottomrule", r"\end{tabular}", ""]
    open(out_path, "w").write("\n".join(lines))
    print("wrote", out_path, {k: (round(u, 2), round(100 * r, 1)) for k, (u, r) in pairs.items()})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
