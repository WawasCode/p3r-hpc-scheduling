# P3R: price-aware HPC scheduling with pause and resume

Code, input data, and simulation results for the Bachelor's thesis
*Electricity Price-Aware HPC Scheduling* (Freie Universität Berlin, 2026).

The thesis compares three batch scheduling policies on a simulated
64-node cluster:

- **FCFS**: first-come, first-served,
- **EASY**: EASY backfilling,
- **P3R**: a profile- and price-aware pause/resume policy that pauses
  checkpointable jobs in expensive hours and resumes them in cheaper ones,
  within each job's deadline, with one urgency parameter λ.

All policies run on identical synthetic workloads and on the 2024 hourly
day-ahead price trace for Germany/Luxembourg, and every comparison is
paired per seed.

## Contents

| Path | What it is |
|---|---|
| `src/bachelor26/simulator.py` | The hourly simulator: workload generator, FCFS, EASY, and P3R |
| `tests/` | Unit tests (32), including a brute-force check of P3R's run-or-skip decision |
| `data/prices/` | SMARD day-ahead prices DE/LU 2024, hourly, EUR/MWh |
| `scripts/` | Experiment runners, robustness checks, table and figure scripts |
| `experiments/results/` | Results of every run reported in the thesis |

### Results and where the thesis uses them

| Folder | Thesis |
|---|---|
| `main-full-2024-v4` | Main experiment, full year 2024 (Sections 5.4–5.6, Table 5.3, Figures 5.2–5.3, Section 6.2) |
| `main-60d-winter-v4` | 60-day winter window, January–February (Section 5.7, Table B.1) |
| `main-60d-summer-v4` | 60-day summer window, July–August (Section 5.7, Table B.2) |
| `dev-seeds-60d-winter-v4` | Winter window with a second set of seeds, 42–51 (Section 5.7) |
| `priority-order-check` | Admission order: tie-breaking and arrival order (Sections 5.5, 5.7) |
| `profile-ablation` | P3R with a profile-blind planner (Section 5.7) |
| `wide-job-waits` | Waiting times by requested node count (Section 6.3) |

Each `main-*` and `dev-seeds-*` folder contains `runs.csv` (one row per
simulation run), `summary.csv`, `workloads.csv`, a `REPORT.md`, and the
run log.

## Reproducing the results

The simulator needs only the Python standard library (Python 3.10 or
newer). The figure scripts need matplotlib, the tests need pytest.

```bash
python3 -m pytest -q

# main experiments (10 seeds x 4 loads x 9 policy settings = 360 runs each)
python3 scripts/run_parallel_policy_report.py --horizon 8784 --seeds 1,2,3,4,5,6,7,8,9,10 --out-dir experiments/results/main-full-2024-v4
python3 scripts/run_parallel_policy_report.py --horizon 1440 --seeds 1,2,3,4,5,6,7,8,9,10 --out-dir experiments/results/main-60d-winter-v4
python3 scripts/run_parallel_policy_report.py --horizon 1440 --price-offset 4368 --seeds 1,2,3,4,5,6,7,8,9,10 --out-dir experiments/results/main-60d-summer-v4
python3 scripts/run_parallel_policy_report.py --horizon 1440 --seeds 42,43,44,45,46,47,48,49,50,51 --out-dir experiments/results/dev-seeds-60d-winter-v4

# robustness checks
python3 scripts/check_priority_order.py --out-dir experiments/results/priority-order-check
python3 scripts/check_profile_ablation.py > experiments/results/profile-ablation/summary.txt
python3 scripts/check_wide_job_waits.py > experiments/results/wide-job-waits/summary.txt

# thesis tables and figures
python3 scripts/make_results_table.py experiments/results/main-full-2024-v4/runs.csv results_full.tex
python3 scripts/make_whatif_table.py experiments/results/main-full-2024-v4/runs.csv whatif.tex
python3 scripts/plot_thesis_figures.py experiments/results/main-full-2024-v4/runs.csv figures full
python3 scripts/plot_seasonal.py experiments/results/main-60d-winter-v4/runs.csv experiments/results/main-60d-summer-v4/runs.csv experiments/results/main-full-2024-v4/runs.csv figures
```

The simulation is deterministic: the same seeds give the same numbers.
A full-year run of one load level and policy setting takes about twenty
seconds on a laptop; the runners use all available cores.

## Price data

`data/prices/smard_de_lu_2024_hourly.csv` is the hourly day-ahead price
for the Germany/Luxembourg bidding zone in 2024, retrieved from
[SMARD](https://www.smard.de), the electricity market data platform of the
Bundesnetzagentur, which publishes its data under the CC BY 4.0 licence.
Source: Bundesnetzagentur | SMARD.de. `scripts/download_smard_prices.py`
downloads it again.
