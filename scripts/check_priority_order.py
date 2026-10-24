"""Check how much the results depend on the policy's priority order.

The policy admits jobs each hour in the order of ``_preemptive_priority``:
mandatory before opportunistic, then earlier deadline, smaller slack, lower
current-step cost, lower job id (Section 4.4.4 of the thesis). This script
reruns the full-year experiment with the same workloads and prices under
three orders and compares them with EASY:

* ``deadline``  the order used in the thesis (reproduces run #15 exactly),
* ``alt_ties``  same primary keys (urgency class, deadline) but the
                remaining ties broken the other way round: higher
                current-step cost first, then higher job id, slack ignored,
* ``arrival``   plain arrival order (submit time, job id), no urgency class.

``arrival`` at lambda = 1 is close to a first-fit scheduler without
reservations and without price awareness, so comparing it with EASY and
with ``deadline`` separates the effect of the admission rule from the
effect of the deadline order.

Usage:
    python3 scripts/check_priority_order.py --out-dir experiments/results/priority-order-check
"""

from __future__ import annotations

import argparse
import csv
import math
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from statistics import mean, stdev

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

LOAD_LEVELS = ["low", "medium", "high", "mixed"]
VARIANTS = ["deadline", "alt_ties", "arrival"]
T_95_9DF = 2.262  # two-sided 95 % t quantile, 9 degrees of freedom


def workload_seed(seed: int, load: str) -> int:
    # Same convention as scripts/run_parallel_policy_report.py.
    return seed + LOAD_LEVELS.index(load) * 1000


def _priority_alt_ties(state, now, prices, mandatory):
    active_nodes = state.job.active_nodes_at(state.progress)
    current_cost = active_nodes * float(prices[now])
    return (0 if mandatory else 1, state.deadline, -current_cost, -state.job.job_id)


def _priority_arrival(state, now, prices, mandatory):
    return (state.job.submit_time, state.job.job_id)


def run_task(task: dict) -> dict:
    from bachelor26 import generate_workload, load_prices, simulate
    import bachelor26.simulator as sim

    original = sim.__dict__.setdefault("_original_preemptive_priority", sim._preemptive_priority)
    sim._preemptive_priority = {
        "deadline": original,
        "alt_ties": _priority_alt_ties,
        "arrival": _priority_arrival,
        "easy": original,
    }[task["variant"]]

    prices = tuple(load_prices(ROOT / "data/prices/smard_de_lu_2024_hourly.csv", limit=task["horizon"], offset=0))
    jobs = generate_workload(task["load"], horizon_hours=task["horizon"], seed=workload_seed(task["seed"], task["load"]))
    if task["variant"] == "easy":
        result = simulate(jobs, prices, "easy_backfill", load_level=task["load"])
    else:
        result = simulate(
            jobs, prices, "price_aware_preemptive", load_level=task["load"], delay_penalty_lambda=task["lam"]
        )
    row = result.as_dict()
    # Same definition as scripts/run_parallel_policy_report.py.
    row["qos_violation_rate_percent"] = 100.0 * row["qos_violations"] / row["total_jobs"] if row["total_jobs"] else 0.0
    row.update(variant=task["variant"], seed=task["seed"], lam=task["lam"], load=task["load"])
    return row


def ci(values: list[float]) -> tuple[float, float]:
    return mean(values), T_95_9DF * stdev(values) / math.sqrt(len(values))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="experiments/results/priority-order-check")
    parser.add_argument("--horizon", type=int, default=8784)
    parser.add_argument("--seeds", default="1,2,3,4,5,6,7,8,9,10")
    parser.add_argument("--lambdas", default="0,1")
    parser.add_argument("--workers", type=int, default=max(1, min(os.cpu_count() or 1, 10)))
    args = parser.parse_args()

    seeds = [int(s) for s in args.seeds.split(",")]
    lambdas = [float(x) for x in args.lambdas.split(",")]
    tasks = [
        {"variant": "easy", "seed": s, "lam": -1.0, "load": load, "horizon": args.horizon}
        for load in LOAD_LEVELS
        for s in seeds
    ]
    tasks += [
        {"variant": v, "seed": s, "lam": lam, "load": load, "horizon": args.horizon}
        for load in LOAD_LEVELS
        for s in seeds
        for v in VARIANTS
        for lam in lambdas
    ]
    print(f"Running {len(tasks)} simulations with {args.workers} workers...", flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(run_task, t) for t in tasks]
        for i, fut in enumerate(as_completed(futures), 1):
            rows.append(fut.result())
            if i % 20 == 0:
                print(f"  {i}/{len(tasks)} done", flush=True)

    out = ROOT / args.out_dir
    out.mkdir(parents=True, exist_ok=True)
    keys = ["load", "variant", "lam", "seed", "mean_paid_price_eur_per_mwh", "qos_violation_rate_percent",
            "avg_wait_h", "scheduled_jobs", "total_jobs", "suspended_job_hours"]
    rows.sort(key=lambda r: (LOAD_LEVELS.index(r["load"]), r["variant"], r["lam"], r["seed"]))
    with open(out / "runs.csv", "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    by = {(r["load"], r["variant"], r["lam"], r["seed"]): r for r in rows}
    lines = ["| load | variant | lambda | paid price (EUR/MWh) | price vs EASY (%) | violations (%) | "
             "violations vs EASY (points) | violations vs deadline order (points) | mean wait (h) |",
             "|---|---|---|---|---|---|---|---|---|"]
    for load in LOAD_LEVELS:
        easy = {s: by[(load, "easy", -1.0, s)] for s in seeds}
        lines.append(
            f"| {load} | EASY | | {mean(float(e['mean_paid_price_eur_per_mwh']) for e in easy.values()):.1f} | | "
            f"{mean(float(e['qos_violation_rate_percent']) for e in easy.values()):.1f} | | | "
            f"{mean(float(e['avg_wait_h']) for e in easy.values()):.1f} |"
        )
        for lam in lambdas:
            ref = {s: by[(load, "deadline", lam, s)] for s in seeds}
            for v in VARIANTS:
                cur = {s: by[(load, v, lam, s)] for s in seeds}
                price = [float(cur[s]["mean_paid_price_eur_per_mwh"]) for s in seeds]
                red = [
                    (float(cur[s]["mean_paid_price_eur_per_mwh"]) - float(easy[s]["mean_paid_price_eur_per_mwh"]))
                    / float(easy[s]["mean_paid_price_eur_per_mwh"]) * 100
                    for s in seeds
                ]
                viol = [float(cur[s]["qos_violation_rate_percent"]) for s in seeds]
                dv_easy = [viol[i] - float(easy[s]["qos_violation_rate_percent"]) for i, s in enumerate(seeds)]
                dv_ref = [viol[i] - float(ref[s]["qos_violation_rate_percent"]) for i, s in enumerate(seeds)]
                wait = [float(cur[s]["avg_wait_h"]) for s in seeds]
                lines.append(
                    f"| {load} | {v} | {lam:g} | {mean(price):.1f} | {ci(red)[0]:+.1f} ± {ci(red)[1]:.1f} | "
                    f"{mean(viol):.1f} | {ci(dv_easy)[0]:+.1f} ± {ci(dv_easy)[1]:.1f} | "
                    f"{ci(dv_ref)[0]:+.1f} ± {ci(dv_ref)[1]:.1f} | {mean(wait):.1f} |"
                )
    summary = "\n".join(lines)
    (out / "summary.md").write_text(
        "# Priority-order check (full year 2024, seeds " + args.seeds + ")\n\n"
        "Paired per seed; ± is the 95 % t confidence half-width over ten seeds.\n\n" + summary + "\n"
    )
    print(summary)


if __name__ == "__main__":
    main()
