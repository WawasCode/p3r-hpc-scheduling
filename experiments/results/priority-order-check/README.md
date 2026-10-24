# priority-order-check

Answers the supervisor's question (17 Oct 2026) whether the tie-breaking
rules of Section 4.4.4 matter, and separates the two sources of P3R's
deadline advantage over EASY (admission without reservation, deadline order).

Same workloads and prices as run #15 (full year 2024, seeds 1-10, 64 nodes,
1 kW per node). Command:

    python3 scripts/check_priority_order.py --out-dir experiments/results/priority-order-check --workers 10

Variants of the admission order (`_preemptive_priority`, patched at runtime,
no change to the simulator itself):

- `deadline`: the thesis order. Reproduces run #15 exactly (120 of 120 runs
  compared, including EASY).
- `alt_ties`: same urgency class and deadline, ties broken by higher
  current-step cost, then higher job id, slack ignored.
- `arrival`: plain arrival order (submit time, job id), no urgency class.

Findings used in Sections 5.5, 5.7, 6.1 and 6.3:

- Tie-breaking: at most 0.35 % change in paid price and 2.1 points in
  violation rate at any load and lambda in {0, 1}; no difference
  distinguishable from zero.
- At lambda = 1, medium load, P3R misses 17.8 +- 3.9 points fewer deadlines
  than EASY; 11.9 +- 3.1 come from the admission rule (arrival vs EASY) and
  5.8 +- 1.6 from the deadline order (deadline vs arrival).
- The price saving does not depend on the order (low 26.2 vs 26.1 %,
  medium 11.8 vs 11.4 %), but with arrival order lambda = 0 misses
  3.6 +- 1.7 points more deadlines than EASY at medium load (deadline
  order: 4.6 +- 2.3 fewer).

`summary.md` has the full table; `runs.csv` the per-seed values.
