"""Waiting times and never-started jobs by requested node count.

Compares P3R at lambda = 0 and lambda = 1 with EASY on the workloads and prices
of the full-year experiment (seeds 1-10, medium and high load). Only jobs whose
deadline lies inside the year are counted, so end-of-year jobs do not inflate
the numbers. A job that never starts counts with a wait until the end of 2024.

Usage:
    python3 scripts/check_wide_job_waits.py > experiments/results/wide-job-waits/summary.txt
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from collections import defaultdict
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT + "/src")
LOADS = ["low", "medium", "high", "mixed"]

def run(t):
    import bachelor26.simulator as sim
    from bachelor26 import generate_workload, load_prices
    load, seed, pol = t
    prices = tuple(load_prices(ROOT + "/data/prices/smard_de_lu_2024_hourly.csv", limit=8784, offset=0))
    jobs = generate_workload(load, horizon_hours=8784, seed=seed + LOADS.index(load) * 1000)
    starts = {}
    if pol == "easy":
        orig = sim.__dict__.setdefault("_orig_start", sim._start)
        def rec(job, start, running, scheduled):
            starts[job.job_id] = start; orig(job, start, running, scheduled)
        sim._start = rec
        sim.simulate(jobs, prices, "easy_backfill", load_level=load)
        sim._start = orig
    else:
        made = []
        Base = sim.__dict__.setdefault("_OrigState", sim.PreemptiveJobState)
        class Rec(Base):
            def __init__(self, *a, **k):
                super().__init__(*a, **k); made.append(self)
        sim.PreemptiveJobState = Rec
        sim.simulate(jobs, prices, "price_aware_preemptive", load_level=load, delay_penalty_lambda=pol)
        sim.PreemptiveJobState = Base
        starts = {s.job.job_id: s.first_start for s in made}
    Base = sim.__dict__.get("_OrigState", sim.PreemptiveJobState)
    return t, [(j.nodes, j.submit_time, Base(j).deadline, starts.get(j.job_id)) for j in jobs]

if __name__ == "__main__":
    tasks = [(l, s, p) for l in ("medium", "high") for s in range(1, 11) for p in ("easy", 0.0, 1.0)]
    with ProcessPoolExecutor() as pool:
        res = list(pool.map(run, tasks))
    agg = defaultdict(lambda: defaultdict(list))
    for (load, seed, pol), rows in res:
        for nodes, sub, dl, start in rows:
            if dl > 8783: continue
            agg[(load, str(pol))][nodes].append((start is None, (start if start is not None else 8784) - sub))
    for key in sorted(agg):
        print(f"\n{key[0]} load, policy={key[1]} (10 seeds)")
        print("  nodes   jobs  never-started  max-wait(h)  median-wait(h)  mean-wait(h)")
        for n in sorted(agg[key]):
            v = agg[key][n]; ws = sorted(w for _, w in v)
            print(f"  {n:>5} {len(v):>6} {sum(x[0] for x in v):>14} {ws[-1]:>12} {ws[len(ws)//2]:>15} {sum(ws)/len(ws):>13.0f}")
