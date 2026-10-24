"""Baselines keep the same QoS semantics as the preemptive policy: a job whose
latest start time passes still runs, later, and counts as one violation.
Nothing is dropped from the queue."""
from bachelor26.simulator import Job, simulate


def _blocking_workload():
    # Job 0 fills the whole 4-node cluster for 6 hours. Job 1 arrives at hour
    # 1 with max_wait 2, so its latest start (3) passes while job 0 runs.
    return [Job(0, 0, 6, 4, 10), Job(1, 1, 2, 4, 2)]


def test_fcfs_runs_late_job_and_counts_one_violation() -> None:
    result = simulate(_blocking_workload(), [50.0] * 24, "fcfs", capacity_nodes=4)
    assert result.scheduled_jobs == 2
    assert result.qos_violations == 1


def test_easy_runs_late_job_and_counts_one_violation() -> None:
    result = simulate(_blocking_workload(), [50.0] * 24, "easy_backfill", capacity_nodes=4)
    assert result.scheduled_jobs == 2
    assert result.qos_violations == 1


def test_baselines_and_preemptive_policy_complete_the_same_jobs() -> None:
    jobs = _blocking_workload()
    prices = [50.0] * 24
    completed = {p: simulate(jobs, prices, p, capacity_nodes=4).scheduled_jobs for p in ("fcfs", "easy_backfill", "price_aware_preemptive")}
    assert len(set(completed.values())) == 1, completed
