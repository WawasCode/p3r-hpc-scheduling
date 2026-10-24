"""Near the end of the simulation, the baselines follow the preemptive policy's
semantics: a job that cannot finish before the horizon still starts, runs until
the horizon, is charged for those hours, and counts as one violation. It does
not block the queue behind it."""
import pytest

from bachelor26.simulator import Job, simulate

HORIZON = 10
PRICES = [50.0] * HORIZON


def _long_head_workload():
    # Job 0 arrives at hour 5 and needs 20 hours, so it cannot finish before
    # the horizon. Job 1 arrives behind it and fits on the remaining nodes.
    return [Job(0, 5, 20, 2, 24), Job(1, 6, 2, 2, 24)]


@pytest.mark.parametrize("policy", ["fcfs", "easy_backfill"])
def test_job_that_cannot_finish_does_not_block_the_queue(policy: str) -> None:
    result = simulate(_long_head_workload(), PRICES, policy, capacity_nodes=4)
    assert result.scheduled_jobs == 1  # job 1 completes
    assert result.qos_violations == 1  # job 0 does not complete


@pytest.mark.parametrize("policy", ["fcfs", "easy_backfill"])
def test_job_running_at_horizon_is_charged_only_inside_it(policy: str) -> None:
    result = simulate(_long_head_workload(), PRICES, policy, capacity_nodes=4)
    # Job 0 runs hours 5..9 on 2 nodes, job 1 runs hours 6..7 on 2 nodes.
    assert result.active_node_hours == 5 * 2 + 2 * 2
    assert result.total_cost_eur == pytest.approx(result.active_node_hours * 50.0 / 1000.0)
    assert result.utilization == pytest.approx((5 * 2 + 2 * 2) / (4 * HORIZON))


def test_easy_backfills_behind_a_head_without_reservation() -> None:
    # Job 0 holds 3 of 4 nodes past the horizon. Job 1 needs all 4 nodes, so it
    # has no feasible start before the horizon. Job 2 fits on the free node and
    # cannot delay job 1, so EASY must backfill it.
    jobs = [Job(0, 0, 20, 3, 24), Job(1, 1, 5, 4, 24), Job(2, 2, 2, 1, 24)]
    result = simulate(jobs, PRICES, "easy_backfill", capacity_nodes=4)
    assert result.scheduled_jobs == 1  # job 2 completes
    assert result.qos_violations == 2  # job 0 unfinished, job 1 never started


def test_all_policies_complete_the_same_jobs_at_the_horizon() -> None:
    completed = {
        policy: simulate(_long_head_workload(), PRICES, policy, capacity_nodes=4).scheduled_jobs
        for policy in ("fcfs", "easy_backfill", "price_aware_preemptive")
    }
    assert len(set(completed.values())) == 1, completed
