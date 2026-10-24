"""The run-or-skip rule uses the exact BestCost dynamic program for every job,
however long. Large instances are checked against a plain full-table DP."""
import math
import random

from bachelor26.simulator import _run_and_skip_costs


def _best_cost_full_table(active: list[int], prices: list[float]) -> float:
    steps, hours = len(active), len(prices)
    if hours < steps:
        return math.inf
    table = [[math.inf] * (hours + 1) for _ in range(steps + 1)]
    table[steps] = [0.0] * (hours + 1)
    for step in range(steps - 1, -1, -1):
        for hour in range(hours - 1, -1, -1):
            if hours - hour < steps - step:
                continue
            run = active[step] * prices[hour] + table[step + 1][hour + 1]
            table[step][hour] = min(run, table[step][hour + 1])
    return table[0][0]


def test_running_example() -> None:
    assert _run_and_skip_costs([4, 2, 4], [100.0, 40.0, 120.0, 30.0, 90.0]) == (600.0, 520.0)


def test_long_jobs_beyond_the_former_cap_use_the_exact_program() -> None:
    # 150 steps x 300 hours = 45,000 cells, above the former 20,000-cell cap
    # where the policy used an unordered relaxation.
    rng = random.Random(11)
    for _ in range(3):
        active = [rng.randint(0, 32) for _ in range(150)]
        prices = [rng.uniform(-100.0, 400.0) for _ in range(300)]
        run_now, skip_now = _run_and_skip_costs(active, prices)
        assert math.isclose(run_now, active[0] * prices[0] + _best_cost_full_table(active[1:], prices[1:]))
        assert math.isclose(skip_now, _best_cost_full_table(active, prices[1:]))
