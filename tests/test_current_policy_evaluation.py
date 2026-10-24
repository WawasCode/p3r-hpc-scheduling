from pathlib import Path

from scripts.run_parallel_policy_report import (
    CURRENT_POLICY,
    best_lambda_rows,
    parse_lambdas,
    policy_variant,
    summarize,
    write_report,
)


def test_parse_lambdas_sorts_deduplicates_and_rejects_negative_values():
    assert parse_lambdas("0.1,0,0.05,0.1") == [0.0, 0.05, 0.1]
    try:
        parse_lambdas("0,-1")
    except ValueError as exc:
        assert "non-negative" in str(exc)
    else:
        raise AssertionError("negative lambdas should fail")


def test_policy_variant_names_baselines_and_current_lambda_sweep():
    assert policy_variant("fcfs", None) == "fcfs"
    assert policy_variant("easy_backfill", None) == "easy_backfill"
    assert policy_variant(CURRENT_POLICY, 0.25) == "preemptive_profile_price_aware_lambda_0.25"


def test_summarize_keeps_baselines_and_lambda_variants_separate():
    runs = [
        {
            "load_level": "low",
            "policy": "fcfs",
            "policy_variant": "fcfs",
            "policy_label": "FCFS",
            "delay_penalty_lambda": "baseline",
            "scheduled_jobs": 8,
            "total_jobs": 10,
            "qos_violations": 2,
            "qos_violation_rate_percent": 20.0,
            "total_cost_eur": 12.0,
            "cost_per_completed_job_eur": 1.5,
            "mean_paid_price_eur_per_mwh": 100.0,
            "avg_wait_h": 0.0,
            "p95_wait_h": 0.0,
            "avg_response_h": 4.0,
            "avg_bounded_slowdown": 1.0,
            "utilization": 0.2,
            "active_node_hours": 100,
            "reserved_node_hours": 120,
            "preempted_jobs": 0,
            "suspended_job_hours": 0,
            "suspended_reserved_node_hours": 0,
        },
        {
            "load_level": "low",
            "policy": CURRENT_POLICY,
            "policy_variant": "preemptive_profile_price_aware_lambda_0",
            "policy_label": "Profile+price-aware",
            "delay_penalty_lambda": 0.0,
            "scheduled_jobs": 9,
            "total_jobs": 10,
            "qos_violations": 1,
            "qos_violation_rate_percent": 10.0,
            "total_cost_eur": 10.0,
            "cost_per_completed_job_eur": 1.1111,
            "mean_paid_price_eur_per_mwh": 80.0,
            "avg_wait_h": 6.0,
            "p95_wait_h": 8.0,
            "avg_response_h": 10.0,
            "avg_bounded_slowdown": 1.5,
            "utilization": 0.3,
            "active_node_hours": 100,
            "reserved_node_hours": 140,
            "preempted_jobs": 1,
            "suspended_job_hours": 5,
            "suspended_reserved_node_hours": 20,
        },
        {
            "load_level": "low",
            "policy": CURRENT_POLICY,
            "policy_variant": "preemptive_profile_price_aware_lambda_0.5",
            "policy_label": "Profile+price-aware",
            "delay_penalty_lambda": 0.5,
            "scheduled_jobs": 9,
            "total_jobs": 10,
            "qos_violations": 3,
            "qos_violation_rate_percent": 30.0,
            "total_cost_eur": 9.0,
            "cost_per_completed_job_eur": 1.0,
            "mean_paid_price_eur_per_mwh": 75.0,
            "avg_wait_h": 3.0,
            "p95_wait_h": 6.0,
            "avg_response_h": 8.0,
            "avg_bounded_slowdown": 1.2,
            "utilization": 0.3,
            "active_node_hours": 100,
            "reserved_node_hours": 140,
            "preempted_jobs": 1,
            "suspended_job_hours": 2,
            "suspended_reserved_node_hours": 8,
        },
    ]

    summary = summarize(runs, qos_violation_penalty_eur=1000.0)

    assert [row["policy_variant"] for row in summary] == [
        "fcfs",
        "preemptive_profile_price_aware_lambda_0",
        "preemptive_profile_price_aware_lambda_0.5",
    ]
    assert summary[0]["delay_penalty_lambda"] == "baseline"
    assert summary[1]["qos_penalized_objective_eur_mean"] == 1010.0


def test_best_lambda_rows_uses_qos_penalized_objective():
    rows = [
        {"load_level": "low", "policy": CURRENT_POLICY, "delay_penalty_lambda": 0.0, "qos_penalized_objective_eur_mean": 1100.0, "qos_violations_mean": 1.0, "total_cost_eur_mean": 100.0},
        {"load_level": "low", "policy": CURRENT_POLICY, "delay_penalty_lambda": 1.0, "qos_penalized_objective_eur_mean": 900.0, "qos_violations_mean": 0.0, "total_cost_eur_mean": 900.0},
    ]
    assert best_lambda_rows(rows)[0]["delay_penalty_lambda"] == 1.0


def test_write_report_documents_current_policy_and_normalized_price_plot(tmp_path: Path):
    report = tmp_path / "REPORT.md"
    summary_rows = [
        {
            "load_level": "low",
            "policy": CURRENT_POLICY,
            "policy_variant": "preemptive_profile_price_aware_lambda_0",
            "delay_penalty_lambda": 0.0,
            "runs": 1,
            "scheduled_jobs_mean": 1.0,
            "qos_violations_mean": 0.0,
            "qos_violation_rate_percent_mean": 0.0,
            "total_cost_eur_mean": 1.0,
            "cost_per_completed_job_eur_mean": 1.0,
            "mean_paid_price_eur_per_mwh_mean": 100.0,
            "avg_wait_h_mean": 2.0,
            "reserved_utilization_mean": 0.5,
            "suspended_job_hours_mean": 0.0,
            "qos_penalized_objective_eur_mean": 1.0,
        }
    ]
    workload_rows: list[dict[str, object]] = [
        {"load_level": load, "jobs": 1, "max_duration_h": 336} for load in ["low", "medium", "high", "mixed"]
    ]
    plot_paths = [
        tmp_path / name
        for name in [
            "total_cost_by_load.png",
            "cost_per_job_by_load.png",
            "normalized_price_by_load.png",
            "qos_violations_by_load.png",
            "qos_violation_rate_percent_by_load.png",
            "wait_by_load.png",
            "suspension_by_load.png",
            "synthetic_profile_examples.png",
        ]
    ]
    write_report(
        report,
        summary_rows=summary_rows,
        workload_rows=workload_rows,
        seeds=[42],
        lambdas=[0.0],
        arrival_horizon_h=720,
        price_horizon_h=720,
        price_source="data/prices/example.csv",
        price_offset_h=0,
        capacity_nodes=64,
        power_kw_per_node=1.0,
        qos_violation_penalty_eur=1000.0,
        max_workers=1,
        plot_paths=plot_paths,
    )

    text = report.read_text()
    assert "Current Policy Evaluation" in text
    assert "price_aware_preemptive" in text
    assert "older non-preemptive delayed-start `price_aware`" in text
    assert "![Normalized paid price by load](normalized_price_by_load.png)" in text
