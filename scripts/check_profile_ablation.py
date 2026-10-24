"""Profile ablation: does P3R gain from knowing the job profiles?

Reruns P3R on the workloads and prices of the full-year experiment (seeds 1-10,
low and medium load, lambda = 0 and 0.5) with two planners:

* ``profile``  the planner of the thesis, which sees the true active-node profile,
* ``flat``     a profile-blind planner that assumes all n_j reserved nodes are
               active in every remaining hour (also in the urgency penalty).

Cost is always charged for the true profile. Each variant is paired against
EASY on the same workload; the output reports the paid-price reduction against
EASY, the difference profile - flat with a 95 % t interval (9 degrees of
freedom), the violation rate, and the suspended job-hours.

Usage:
    python3 scripts/check_profile_ablation.py > experiments/results/profile-ablation/summary.txt
"""
import sys, statistics as st
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
ROOT = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, ROOT + "/src")
LOADS = ["low", "medium", "high", "mixed"]

def run(t):
    import bachelor26.simulator as sim
    from bachelor26 import generate_workload, load_prices
    load, seed, variant, lam = t
    orig = sim.__dict__.setdefault("_orig_lookahead", sim._profile_lookahead_should_run)
    sim._profile_lookahead_should_run = orig
    if variant == "flat":
        def blind(state, now, prices, delay_penalty_lambda):
            job = state.job
            window_end = min(state.deadline, len(prices))
            if now >= window_end or state.remaining >= window_end - now:
                return True
            window = [float(prices[h]) for h in range(now, window_end)]
            rem = [job.nodes] * (job.duration - state.progress)
            if len(rem) >= len(window):
                return True
            r, s = sim._run_and_skip_costs(rem, window)
            pen = delay_penalty_lambda * (max(window) - min(window)) * max(1.0, float(job.nodes))
            return r <= s + pen
        sim._profile_lookahead_should_run = blind
    prices = tuple(load_prices(ROOT + "/data/prices/smard_de_lu_2024_hourly.csv", limit=8784, offset=0))
    jobs = generate_workload(load, horizon_hours=8784, seed=seed + LOADS.index(load) * 1000)
    if variant == "easy":
        r = sim.simulate(jobs, prices, "easy_backfill", load_level=load)
    else:
        r = sim.simulate(jobs, prices, "price_aware_preemptive", load_level=load, delay_penalty_lambda=lam)
    d = r.as_dict()
    return t, d["mean_paid_price_eur_per_mwh"], 100 * d["qos_violations"] / d["total_jobs"], d["suspended_job_hours"]

if __name__ == "__main__":
    tasks = []
    for load in ("low", "medium"):
        for s in range(1, 11):
            tasks.append((load, s, "easy", -1))
            for lam in (0.0, 0.5):
                tasks += [(load, s, "profile", lam), (load, s, "flat", lam)]
    with ProcessPoolExecutor() as pool:
        res = {t: v for t, *v in pool.map(run, tasks)}
    T = 2.262
    for load in ("low", "medium"):
        for lam in (0.0, 0.5):
            red = {v: [] for v in ("profile", "flat")}; viol = {v: [] for v in red}; susp = {v: [] for v in red}; diff = []
            for s in range(1, 11):
                pe = res[(load, s, "easy", -1)][0]
                for v in red:
                    p, q, h = res[(load, s, v, lam)]
                    red[v].append(100 * (1 - p / pe)); viol[v].append(q); susp[v].append(h)
                diff.append(red["profile"][-1] - red["flat"][-1])
            ci = T * st.stdev(diff) / 10 ** 0.5
            print(f"{load:6} lambda={lam}: price reduction vs EASY  profile {st.mean(red['profile']):5.1f}%  flat {st.mean(red['flat']):5.1f}%  "
                  f"(profile - flat = {st.mean(diff):.1f} +- {ci:.1f} pts) | violations {st.mean(viol['profile']):.1f}% vs {st.mean(viol['flat']):.1f}% | "
                  f"suspended job-h {st.mean(susp['profile']):.0f} vs {st.mean(susp['flat']):.0f}")
