"""Cross-check the hourly run-or-skip rule against exhaustive enumeration.

The exact BestCost dynamic program inside ``_profile_lookahead_should_run``
is compared with a brute-force placement search on random small instances,
so that the decision the simulator takes matches the decision implied by the
definition in the thesis (run iff run_now <= skip_now + penalty).
"""
from __future__ import annotations

import itertools
import math
import random

from bachelor26.simulator import Job, JobProfile, PreemptiveJobState, _profile_lookahead_should_run


def _best_cost_bruteforce(active: list[int], prices: list[float]) -> float:
    if len(prices) < len(active):
        return math.inf
    return min(
        sum(a * prices[h] for a, h in zip(active, hours))
        for hours in itertools.combinations(range(len(prices)), len(active))
    )


def _reference_decision(active: list[int], window: list[float], lam: float) -> bool:
    if len(active) >= len(window):
        return True
    run_now = active[0] * window[0] + _best_cost_bruteforce(active[1:], window[1:])
    skip_now = _best_cost_bruteforce(active, window[1:])
    span = max(window) - min(window)
    penalty = lam * span * max(1.0, sum(active) / len(active))
    return run_now <= skip_now + penalty


def _running_example_state() -> tuple[PreemptiveJobState, list[float]]:
    # Remaining profile (4, 2, 4) with window prices (100, 40, 120, 30, 90):
    # the job is submitted at hour 0 and its deadline is the end of hour 5.
    job = Job(1, 0, 3, 4, 2, profile=JobProfile("example", [4, 2, 4]))
    return PreemptiveJobState(job), [100.0, 40.0, 120.0, 30.0, 90.0]


def test_thesis_running_example_switches_at_lambda_0_27() -> None:
    # run_now = 600, skip_now = 520, penalty = 300 * lambda: switch at 80/300.
    active = [4, 2, 4]
    window = [100.0, 40.0, 120.0, 30.0, 90.0]
    assert _best_cost_bruteforce(active, window) == 520
    state, prices = _running_example_state()
    for lam, runs in ((0.0, False), (0.1, False), (0.26, False), (0.27, True), (0.5, True)):
        assert _profile_lookahead_should_run(state, 0, prices, lam) is runs
        assert _reference_decision(active, window, lam) is runs


def test_lookahead_rule_matches_bruteforce_on_random_instances() -> None:
    rng = random.Random(7)
    checked = 0
    while checked < 300:
        duration = rng.randint(2, 6)
        nodes = rng.randint(1, 8)
        profile = JobProfile("rnd", [rng.randint(0, nodes) for _ in range(duration)])
        if max(profile.active_nodes_by_hour) == 0:
            continue
        progress = rng.randint(0, duration - 1)
        remaining = duration - progress
        window_len = rng.randint(remaining + 1, remaining + 5)
        now = rng.randint(0, 20)
        # deadline = submit + max_wait + duration must equal now + window_len
        submit = 0
        max_wait = now + window_len - duration
        if max_wait < 0:
            continue
        job = Job(1, submit, duration, nodes, max_wait, profile=profile)
        state = PreemptiveJobState(job, progress=progress, first_start=0 if progress else None)
        prices = [float(rng.randint(-150, 200)) for _ in range(now + window_len + 3)]
        lam = rng.choice([0.0, 0.05, 0.25, 1.0])
        window = prices[now : now + window_len]
        active = list(profile.active_nodes_by_hour[progress:])
        assert _profile_lookahead_should_run(state, now, prices, lam) == _reference_decision(active, window, lam)
        checked += 1
