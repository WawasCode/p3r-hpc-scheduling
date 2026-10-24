from bachelor26 import Job, JobProfile, generate_workload, simulate


def test_job_profile_defaults_to_flat_requested_node_usage():
    job = Job(0, 0, 3, 4, 6)
    assert job.active_nodes_at(0) == 4
    assert job.active_nodes_at(1) == 4
    assert job.active_nodes_at(2) == 4
    assert job.profile.active_nodes_by_hour == (4, 4, 4)


def test_job_profile_validates_active_nodes_against_requested_nodes():
    try:
        Job(0, 0, 2, 4, 6, profile=JobProfile("invalid", (4, 5)))
    except ValueError as exc:
        assert "active nodes" in str(exc)
    else:
        raise AssertionError("expected invalid active-node profile to fail")


def test_profile_aware_cost_uses_active_nodes_not_reserved_nodes():
    prices = [100.0, 100.0, 100.0]
    flat = [Job(0, 0, 3, 4, 3)]
    profiled = [Job(0, 0, 3, 4, 3, profile=JobProfile("shrinking", (4, 2, 1)))]

    flat_result = simulate(flat, prices, "fcfs", capacity_nodes=4)
    profiled_result = simulate(profiled, prices, "fcfs", capacity_nodes=4)

    assert round(flat_result.total_cost_eur, 4) == 1.2
    assert round(profiled_result.total_cost_eur, 4) == 0.7
    assert profiled_result.utilization == flat_result.utilization


def test_easy_backfill_schedules_at_least_fcfs_on_fragmented_queue():
    prices = [100.0] * 12
    jobs = [Job(0, 0, 4, 4, 8), Job(1, 1, 2, 4, 8), Job(2, 1, 1, 1, 8)]
    fcfs = simulate(jobs, prices, "fcfs", capacity_nodes=4)
    easy = simulate(jobs, prices, "easy_backfill", capacity_nodes=4)
    assert easy.scheduled_jobs >= fcfs.scheduled_jobs


def test_legacy_non_preemptive_price_aware_policy_is_removed():
    prices = [200.0, 20.0, 20.0]
    jobs = [Job(0, 0, 1, 1, 2)]
    try:
        simulate(jobs, prices, "price_aware", capacity_nodes=1, delay_penalty_lambda=0.5)
    except ValueError as exc:
        assert "unknown policy" in str(exc)
    else:
        raise AssertionError("legacy price_aware policy should not be exposed")


def test_preemptive_price_aware_suspends_expensive_hour_and_preserves_progress():
    prices = [10.0, 1000.0, 10.0, 10.0]
    jobs = [Job(0, 0, 3, 1, 1, preemptible=True)]

    result = simulate(jobs, prices, "price_aware_preemptive", capacity_nodes=1)

    assert result.scheduled_jobs == 1
    assert result.qos_violations == 0
    assert result.avg_wait_h == 0
    assert result.avg_response_h == 4
    assert round(result.total_cost_eur, 4) == 0.03
    assert result.active_node_hours == 3
    assert result.reserved_node_hours == 4
    assert result.suspended_reserved_node_hours == 1
    assert round(result.mean_paid_price_eur_per_mwh, 4) == 10.0


def test_preemptive_price_aware_runs_urgent_job_to_meet_deadline_even_when_price_is_high():
    prices = [10.0, 1000.0, 10.0]
    jobs = [Job(0, 0, 3, 1, 0, preemptible=True)]

    result = simulate(jobs, prices, "price_aware_preemptive", capacity_nodes=1)

    assert result.scheduled_jobs == 1
    assert result.qos_violations == 0
    assert result.avg_response_h == 3
    assert round(result.total_cost_eur, 4) == 1.02


def test_preemptive_price_aware_does_not_suspend_non_preemptible_jobs():
    prices = [10.0, 1000.0, 10.0, 1.0]
    jobs = [Job(0, 0, 3, 1, 1, preemptible=False)]

    result = simulate(jobs, prices, "price_aware_preemptive", capacity_nodes=1)

    assert result.scheduled_jobs == 1
    assert result.qos_violations == 0
    assert result.avg_response_h == 4
    assert result.total_cost_eur > 1.0


def test_paused_preemptible_jobs_keep_their_reserved_nodes():
    prices = [10.0, 1000.0, 10.0, 10.0]
    jobs = [
        Job(0, 0, 3, 2, 1, preemptible=True),
        Job(1, 1, 1, 2, 0, preemptible=True),
    ]

    result = simulate(jobs, prices, "price_aware_preemptive", capacity_nodes=2)

    assert result.scheduled_jobs == 1
    assert result.qos_violations == 1
    assert result.suspended_job_hours == 1
    assert result.suspended_reserved_node_hours == 2
    assert result.reserved_node_hours == 8


def test_profile_lookahead_runs_low_active_step_to_save_cheap_hour_for_high_active_step():
    prices = [100.0, 1.0, 50.0]
    jobs = [Job(0, 0, 2, 10, 1, profile=JobProfile("low_then_high", (1, 10)), preemptible=True)]

    result = simulate(jobs, prices, "price_aware_preemptive", capacity_nodes=10)

    assert result.scheduled_jobs == 1
    assert result.qos_violations == 0
    assert result.avg_wait_h == 0
    assert round(result.total_cost_eur, 4) == 0.11
    assert round(result.mean_paid_price_eur_per_mwh, 4) == 10.0


def test_generate_workload_levels_are_ordered():
    low = len(generate_workload("low", 168, seed=1))
    medium = len(generate_workload("medium", 168, seed=1))
    high = len(generate_workload("high", 168, seed=1))
    assert low < medium < high


def test_generate_workload_assigns_valid_job_profiles():
    jobs = generate_workload("medium", 168, seed=3)
    assert jobs
    assert all(len(job.profile.active_nodes_by_hour) == job.duration for job in jobs)
    assert all(max(job.profile.active_nodes_by_hour) <= job.nodes for job in jobs)
    assert any(job.profile.active_nodes_by_hour != tuple([job.nodes] * job.duration) for job in jobs if job.duration > 1)


def test_generate_workload_runtime_classes_are_realistic_and_capped_at_14_days():
    jobs = generate_workload("mixed", 24 * 90, seed=11)
    assert jobs
    assert {"short_debug", "medium", "long"}.issubset({job.job_class for job in jobs})
    assert max(job.duration for job in jobs) == 336
    assert all(1 <= job.duration <= 336 for job in jobs)


def test_generate_mixed_workload_contains_random_job_mix():
    jobs = generate_workload("mixed", 168, seed=7)
    assert jobs
    assert any(job.duration <= 6 and job.nodes <= 4 for job in jobs)
    assert any(job.duration >= 48 or job.nodes >= 8 for job in jobs)
