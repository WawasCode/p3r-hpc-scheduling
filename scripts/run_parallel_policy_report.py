#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import importlib
import math
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, stdev
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from bachelor26 import Job, generate_workload, load_prices, simulate  # noqa: E402

LOAD_LEVELS = ["low", "medium", "high", "mixed"]
BASELINE_POLICIES = ["fcfs", "easy_backfill"]
CURRENT_POLICY = "price_aware_preemptive"
DEFAULT_LAMBDAS = [0.0, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0]
DEFAULT_SEEDS = [42, 43, 44, 45, 46, 47, 48, 49, 50, 51]
PROFILE_SHAPES = ["flat", "front_loaded", "back_loaded", "valley", "peak", "ramp_up", "ramp_down"]
DEFAULT_QOS_VIOLATION_PENALTY_EUR = 1000.0
POLICY_LABELS = {
    "fcfs": "FCFS",
    "easy_backfill": "EASY backfill",
    CURRENT_POLICY: "Profile+price-aware",
}


def parse_lambdas(text: str) -> list[float]:
    values = sorted({float(part.strip()) for part in text.split(",") if part.strip()})
    if not values:
        raise ValueError("at least one lambda value is required")
    if any(value < 0 for value in values):
        raise ValueError("lambda values must be non-negative")
    return values


def parse_ints(text: str) -> list[int]:
    values = sorted({int(part.strip()) for part in text.split(",") if part.strip()})
    if not values:
        raise ValueError("at least one seed is required")
    return values


def _round(value: float, ndigits: int = 4) -> float:
    return round(float(value), ndigits)


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"cannot write empty CSV: {path}")
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def profile_shape(profile_name: str) -> str:
    for shape in PROFILE_SHAPES:
        if profile_name.endswith(shape):
            return shape
    return profile_name.rsplit("_", 1)[-1]


def workload_seed(seed: int, load: str) -> int:
    return seed + LOAD_LEVELS.index(load) * 1000


def workload_summary(load_level: str, seed: int, jobs: list[Job], arrival_horizon_h: int) -> dict[str, object]:
    class_counts = Counter(getattr(job, "job_class", "unknown") for job in jobs)
    profile_counts = Counter(profile_shape(job.profile.name if job.profile else "flat") for job in jobs)
    durations = [int(job.duration) for job in jobs]
    requested_node_hours = sum(int(job.nodes) * int(job.duration) for job in jobs)
    active_node_hours = sum(sum(job.profile.active_nodes_by_hour if job.profile else [job.nodes] * job.duration) for job in jobs)
    return {
        "load_level": load_level,
        "seed": seed,
        "arrival_horizon_h": arrival_horizon_h,
        "jobs": len(jobs),
        "short_debug_jobs": class_counts.get("short_debug", 0),
        "medium_jobs": class_counts.get("medium", 0),
        "long_jobs": class_counts.get("long", 0),
        "max_duration_h": max(durations) if durations else 0,
        "mean_duration_h": _round(mean(durations) if durations else 0.0),
        "requested_node_hours": requested_node_hours,
        "active_node_hours": active_node_hours,
        "flat_profiles": profile_counts.get("flat", 0),
        "front_loaded_profiles": profile_counts.get("front_loaded", 0),
        "back_loaded_profiles": profile_counts.get("back_loaded", 0),
        "valley_profiles": profile_counts.get("valley", 0),
        "peak_profiles": profile_counts.get("peak", 0),
        "ramp_up_profiles": profile_counts.get("ramp_up", 0),
        "ramp_down_profiles": profile_counts.get("ramp_down", 0),
    }


@dataclass(frozen=True)
class RunTask:
    load_level: str
    seed: int
    policy: str
    lambda_value: float | None
    prices: tuple[float, ...]
    capacity_nodes: int
    power_kw_per_node: float
    arrival_horizon_h: int


def policy_variant(policy: str, lambda_value: float | None) -> str:
    if policy in BASELINE_POLICIES:
        return policy
    return f"preemptive_profile_price_aware_lambda_{lambda_value:g}"


def run_task(task: RunTask) -> dict[str, object]:
    jobs = generate_workload(task.load_level, horizon_hours=task.arrival_horizon_h, seed=workload_seed(task.seed, task.load_level))
    result = simulate(
        jobs,
        list(task.prices),
        task.policy,
        load_level=task.load_level,
        capacity_nodes=task.capacity_nodes,
        power_kw_per_node=task.power_kw_per_node,
        delay_penalty_lambda=float(task.lambda_value or 0.0),
    )
    row = result.as_dict()
    row.update(
        {
            "seed": task.seed,
            "workload_seed": workload_seed(task.seed, task.load_level),
            "arrival_horizon_h": task.arrival_horizon_h,
            "simulation_horizon_h": len(task.prices),
            "capacity_nodes": task.capacity_nodes,
            "power_kw_per_node": task.power_kw_per_node,
            "delay_penalty_lambda": task.lambda_value if task.policy == CURRENT_POLICY else "baseline",
            "policy_variant": policy_variant(task.policy, task.lambda_value),
            "policy_label": POLICY_LABELS[task.policy],
            "cost_per_completed_job_eur": _round(row["total_cost_eur"] / row["scheduled_jobs"] if row["scheduled_jobs"] else 0.0),
            "qos_violation_rate_percent": _round(100.0 * row["qos_violations"] / row["total_jobs"] if row["total_jobs"] else 0.0),
        }
    )
    return row


def summarize(runs: list[dict[str, object]], qos_violation_penalty_eur: float = DEFAULT_QOS_VIOLATION_PENALTY_EUR) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in runs:
        groups[(str(row["load_level"]), str(row["policy_variant"]))].append(row)

    def mean_metric(rows: list[dict[str, object]], key: str) -> float:
        return mean(float(row[key]) for row in rows)

    def sd_metric(rows: list[dict[str, object]], key: str) -> float:
        return stdev(float(row[key]) for row in rows) if len(rows) > 1 else 0.0

    def sort_key(key: tuple[str, str]) -> tuple[int, int, float]:
        load, variant = key
        load_order = LOAD_LEVELS.index(load) if load in LOAD_LEVELS else len(LOAD_LEVELS)
        if variant == "fcfs":
            return load_order, 0, -1.0
        if variant == "easy_backfill":
            return load_order, 1, -1.0
        lambdas = [float(row["delay_penalty_lambda"]) for row in groups[key]]
        return load_order, 2, lambdas[0]

    rows_out: list[dict[str, object]] = []
    for key in sorted(groups, key=sort_key):
        load, variant = key
        rows = groups[key]
        policy = str(rows[0]["policy"])
        lambda_values = {row["delay_penalty_lambda"] for row in rows}
        qos = mean_metric(rows, "qos_violations")
        cost = mean_metric(rows, "total_cost_eur")
        scheduled = mean_metric(rows, "scheduled_jobs")
        total_jobs = mean_metric(rows, "total_jobs")
        rows_out.append(
            {
                "load_level": load,
                "policy": policy,
                "policy_variant": variant,
                "policy_label": rows[0]["policy_label"],
                "delay_penalty_lambda": next(iter(lambda_values)) if len(lambda_values) == 1 else "mixed",
                "runs": len(rows),
                "total_jobs_mean": _round(total_jobs),
                "scheduled_jobs_mean": _round(scheduled),
                "scheduled_jobs_sum": int(sum(int(row["scheduled_jobs"]) for row in rows)),
                "qos_violations_mean": _round(qos),
                "qos_violations_sum": int(sum(int(row["qos_violations"]) for row in rows)),
                "qos_violation_rate_percent_mean": _round(mean_metric(rows, "qos_violation_rate_percent")),
                "total_cost_eur_mean": _round(cost),
                "total_cost_eur_sd": _round(sd_metric(rows, "total_cost_eur")),
                "cost_per_completed_job_eur_mean": _round(mean_metric(rows, "cost_per_completed_job_eur")),
                "mean_paid_price_eur_per_mwh_mean": _round(mean_metric(rows, "mean_paid_price_eur_per_mwh")),
                "avg_wait_h_mean": _round(mean_metric(rows, "avg_wait_h")),
                "p95_wait_h_mean": _round(mean_metric(rows, "p95_wait_h")),
                "avg_response_h_mean": _round(mean_metric(rows, "avg_response_h")),
                "avg_bounded_slowdown_mean": _round(mean_metric(rows, "avg_bounded_slowdown")),
                "reserved_utilization_mean": _round(mean_metric(rows, "utilization")),
                "active_node_hours_mean": _round(mean_metric(rows, "active_node_hours")),
                "reserved_node_hours_mean": _round(mean_metric(rows, "reserved_node_hours")),
                "preempted_jobs_mean": _round(mean_metric(rows, "preempted_jobs")),
                "suspended_job_hours_mean": _round(mean_metric(rows, "suspended_job_hours")),
                "suspended_reserved_node_hours_mean": _round(mean_metric(rows, "suspended_reserved_node_hours")),
                "qos_penalized_objective_eur_mean": _round(cost + qos_violation_penalty_eur * qos),
            }
        )
    return rows_out


def best_lambda_rows(summary_rows: list[dict[str, object]]) -> list[dict[str, object]]:
    best: list[dict[str, object]] = []
    for load in LOAD_LEVELS:
        candidates = [row for row in summary_rows if row["load_level"] == load and row["policy"] == CURRENT_POLICY]
        if candidates:
            best.append(min(candidates, key=lambda row: (float(row["qos_penalized_objective_eur_mean"]), float(row["qos_violations_mean"]), float(row["total_cost_eur_mean"]))))
    return best


def _pil_fonts() -> tuple[object, object, object]:
    from PIL import ImageFont
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)
        small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 13)
        bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 24)
    except Exception:
        font = small = bold = None
    return font, small, bold


def _plot_lambda_metric_pil(summary_rows: list[dict[str, object]], output: Path, metric: str, ylabel: str, title: str) -> None:
    from PIL import Image, ImageDraw
    font, small, bold = _pil_fonts()
    image = Image.new("RGB", (1600, 1000), "white")
    draw = ImageDraw.Draw(image)
    draw.text((40, 25), title, fill="#111", font=bold)
    draw.text((40, 58), f"Y-axis: {ylabel}; X-axis: λ. Dashed lines show FCFS and EASY baselines.", fill="#444", font=small)
    for idx, load in enumerate(LOAD_LEVELS):
        rows = [row for row in summary_rows if row["load_level"] == load]
        preemptive = sorted([row for row in rows if row["policy"] == CURRENT_POLICY], key=lambda row: float(row["delay_penalty_lambda"]))
        left = 90 + (idx % 2) * 760
        top = 135 + (idx // 2) * 410
        width = 620
        height = 260
        values = [float(row.get(metric, 0.0)) for row in rows]
        maxv = max([1.0, *values])
        draw.text((left, top - 35), f"{load} workload", fill="#111", font=font)
        draw.line((left, top, left, top + height), fill="#333", width=2)
        draw.line((left, top + height, left + width, top + height), fill="#333", width=2)
        for tick in range(5):
            y = top + height - int((tick / 4) * height)
            value = maxv * tick / 4
            draw.line((left - 5, y, left + width, y), fill="#dddddd", width=1)
            draw.text((left - 78, y - 8), f"{value:.1f}", fill="#555", font=small)
        for policy, color in [("fcfs", "#d95f02"), ("easy_backfill", "#1b9e77")]:
            row = next((item for item in rows if item["policy"] == policy), None)
            if row is None:
                continue
            y = top + height - int((float(row.get(metric, 0.0)) / maxv) * height)
            for x in range(left, left + width, 18):
                draw.line((x, y, min(x + 10, left + width), y), fill=color, width=3)
            draw.text((left + width + 12, y - 9), policy, fill=color, font=small)
        if preemptive:
            points: list[tuple[int, int, float, float]] = []
            for i, row in enumerate(preemptive):
                value = float(row.get(metric, 0.0))
                x = left + int((i / max(1, len(preemptive) - 1)) * width)
                y = top + height - int((value / maxv) * height)
                points.append((x, y, float(row["delay_penalty_lambda"]), value))
            for (x1, y1, _, _), (x2, y2, _, _) in zip(points, points[1:]):
                draw.line((x1, y1, x2, y2), fill="#7570b3", width=3)
            for x, y, lambda_value, value in points:
                draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#7570b3", outline="#111")
                draw.text((x - 18, top + height + 12), f"{lambda_value:g}", fill="#333", font=small)
                draw.text((x - 18, y - 23), f"{value:.1f}", fill="#333", font=small)
        draw.text((left + width // 2 - 35, top + height + 40), "λ", fill="#333", font=small)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def plot_lambda_metric(summary_rows: list[dict[str, object]], output: Path, metric: str, ylabel: str, title: str) -> None:
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
    except Exception:
        _plot_lambda_metric_pil(summary_rows, output, metric, ylabel, title)
        return
    fig, axes_grid = plt.subplots(2, 2, figsize=(15, 9), sharex=True)
    axes = list(axes_grid.ravel())
    baseline_styles = {
        "fcfs": {"color": "#d95f02", "linestyle": "--", "label": "FCFS baseline"},
        "easy_backfill": {"color": "#1b9e77", "linestyle": "-.", "label": "EASY backfill baseline"},
    }
    for ax, load in zip(axes, LOAD_LEVELS):
        rows = [row for row in summary_rows if row["load_level"] == load]
        preemptive = sorted([row for row in rows if row["policy"] == CURRENT_POLICY], key=lambda row: float(row["delay_penalty_lambda"]))
        if preemptive:
            xs = [float(row["delay_penalty_lambda"]) for row in preemptive]
            ys = [float(row.get(metric, 0.0)) for row in preemptive]
            ax.plot(xs, ys, marker="o", linewidth=2.2, color="#7570b3", label="profile+price-aware λ sweep")
            for x, y in zip(xs, ys):
                ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points", xytext=(0, 6), ha="center", fontsize=7)
        for policy, style in baseline_styles.items():
            row = next((item for item in rows if item["policy"] == policy), None)
            if row is not None:
                ax.axhline(float(row.get(metric, 0.0)), color=style["color"], linestyle=style["linestyle"], linewidth=1.8, label=style["label"])
        ax.set_title(f"{load} workload")
        ax.set_xlabel("delay penalty λ")
        ax.set_ylabel(ylabel)
        ax.grid(axis="both", alpha=0.25)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=3)
    fig.suptitle(title, fontweight="bold")
    fig.tight_layout(rect=[0, 0.06, 1, 0.95])
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, bbox_inches="tight")
    plt.close(fig)


def make_profile(shape: str, duration: int = 48, nodes: int = 16) -> list[int]:
    low_nodes = max(0, nodes // 2)
    high_nodes = nodes
    def interpolate(start: int, end: int, steps: int) -> list[int]:
        if steps <= 1:
            return [end]
        return [int(round(start + (end - start) * idx / (steps - 1))) for idx in range(steps)]
    if shape == "flat":
        return [high_nodes] * duration
    if shape == "front_loaded":
        split = max(1, math.ceil(duration * 0.4))
        return [high_nodes] * split + [low_nodes] * (duration - split)
    if shape == "back_loaded":
        split = max(1, math.floor(duration * 0.6))
        return [low_nodes] * split + [high_nodes] * (duration - split)
    if shape == "valley":
        active = [high_nodes] * duration
        for idx in range(duration // 3, max(duration // 3 + 1, math.ceil(duration * 2 / 3))):
            active[idx] = low_nodes
        return active
    if shape == "peak":
        active = [low_nodes] * duration
        for idx in range(duration // 3, max(duration // 3 + 1, math.ceil(duration * 2 / 3))):
            active[idx] = high_nodes
        return active
    if shape == "ramp_up":
        return interpolate(low_nodes, high_nodes, duration)
    if shape == "ramp_down":
        return interpolate(high_nodes, low_nodes, duration)
    raise ValueError(shape)


def plot_profile_examples(output: Path) -> None:
    try:
        matplotlib = importlib.import_module("matplotlib")
        matplotlib.use("Agg")
        plt = importlib.import_module("matplotlib.pyplot")
        fig, axes = plt.subplots(2, 4, figsize=(15, 7), sharex=True, sharey=True)
        axes_flat = list(axes.ravel())
        for ax, shape in zip(axes_flat, PROFILE_SHAPES):
            active = make_profile(shape)
            ax.step(range(len(active)), active, where="post", linewidth=2.3, color="#7570b3")
            ax.fill_between(range(len(active)), active, step="post", alpha=0.18, color="#7570b3")
            ax.set_title(shape.replace("_", " "))
            ax.set_xlabel("profile hour")
            ax.set_ylabel("active nodes")
            ax.grid(alpha=0.25)
        axes_flat[-1].axis("off")
        fig.suptitle("Example synthetic job profiles: reserved nodes stay fixed, active nodes vary over time", fontweight="bold")
        fig.tight_layout(rect=[0, 0, 1, 0.94])
        output.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(output, dpi=180, bbox_inches="tight")
        plt.close(fig)
        return
    except Exception:
        pass
    from PIL import Image, ImageDraw
    font, small, bold = _pil_fonts()
    image = Image.new("RGB", (1600, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.text((45, 25), "Example synthetic job profiles", fill="#111", font=bold)
    draw.text((45, 58), "Reserved nodes are fixed; active nodes vary over profile time and drive electricity cost.", fill="#555", font=font)
    panel_w, panel_h = 340, 250
    for idx, shape in enumerate(PROFILE_SHAPES):
        col, row = idx % 4, idx // 4
        left = 70 + col * 380
        top = 130 + row * 330
        active = make_profile(shape)
        maxv = max(active) or 1
        draw.text((left, top - 30), shape.replace("_", " "), fill="#111", font=font)
        draw.rectangle((left, top, left + panel_w, top + panel_h), outline="#333", width=2)
        points = []
        for i, value in enumerate(active):
            x = left + int(i / max(1, len(active) - 1) * panel_w)
            y = top + panel_h - int(value / maxv * (panel_h - 20)) - 10
            points.append((x, y))
        for (x1, y1), (x2, y2) in zip(points, points[1:]):
            draw.line((x1, y1, x2, y2), fill="#7570b3", width=3)
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)


def plot_all(summary_rows: list[dict[str, object]], out_dir: Path) -> list[Path]:
    specs = [
        ("total_cost_by_load.png", "total_cost_eur_mean", "Mean total electricity cost (€)", "Total electricity cost by workload and λ"),
        ("cost_per_job_by_load.png", "cost_per_completed_job_eur_mean", "Mean cost per completed job (€ / job)", "Electricity cost per completed job by λ"),
        ("normalized_price_by_load.png", "mean_paid_price_eur_per_mwh_mean", "Mean paid price (€/MWh active work)", "Normalized paid electricity price by workload and λ"),
        ("qos_violations_by_load.png", "qos_violations_mean", "Mean QoS violations", "QoS violations by workload and λ"),
        ("qos_violation_rate_percent_by_load.png", "qos_violation_rate_percent_mean", "Mean QoS violation rate (%)", "QoS violation rate by workload and λ"),
        ("wait_by_load.png", "avg_wait_h_mean", "Mean wait time (h)", "Average wait by workload and λ"),
        ("suspension_by_load.png", "suspended_job_hours_mean", "Mean suspended job-hours", "Suspend/resume activity by workload and λ"),
    ]
    paths: list[Path] = []
    for filename, metric, ylabel, title in specs:
        path = out_dir / filename
        plot_lambda_metric(summary_rows, path, metric, ylabel, title)
        paths.append(path)
    profile_path = out_dir / "synthetic_profile_examples.png"
    plot_profile_examples(profile_path)
    paths.append(profile_path)
    return paths


def compact_table(summary_rows: list[dict[str, object]]) -> list[str]:
    lines = [
        "| Load | Variant | λ | Runs | Completed mean | Cost mean € | Cost/job € | QoS mean | QoS rate % | Paid €/MWh | Avg wait h | Reserved util | Suspended h | Penalized € |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary_rows:
        lines.append(
            "| {load_level} | {policy_variant} | {delay_penalty_lambda} | {runs} | {scheduled_jobs_mean} | {total_cost_eur_mean} | {cost_per_completed_job_eur_mean} | {qos_violations_mean} | {qos_violation_rate_percent_mean} | {mean_paid_price_eur_per_mwh_mean} | {avg_wait_h_mean} | {reserved_utilization_mean} | {suspended_job_hours_mean} | {qos_penalized_objective_eur_mean} |".format(**row)
        )
    return lines


def write_report(
    path: Path,
    *,
    summary_rows: list[dict[str, object]],
    workload_rows: list[dict[str, object]],
    seeds: list[int],
    lambdas: list[float],
    arrival_horizon_h: int,
    price_horizon_h: int,
    price_source: str,
    price_offset_h: int,
    capacity_nodes: int,
    power_kw_per_node: float,
    qos_violation_penalty_eur: float,
    max_workers: int,
    plot_paths: list[Path],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    max_duration = max(int(row["max_duration_h"]) for row in workload_rows)
    mean_jobs_by_load = {load: _round(mean(float(row["jobs"]) for row in workload_rows if row["load_level"] == load)) for load in LOAD_LEVELS}
    plot_names = {p.name: p.name for p in plot_paths}
    best_rows = best_lambda_rows(summary_rows)
    lines = [
        "# Current Policy Evaluation — FCFS, EASY Backfilling, and Profile+Price-Aware λ Sweep",
        "",
        "This is the current cleaned Bachelor-thesis simulator result artifact. It keeps only the focused scheduler comparison:",
        "",
        "1. `fcfs` baseline.",
        "2. `easy_backfill` baseline.",
        "3. `price_aware_preemptive`, the current profile+price-aware pause/resume policy, evaluated over several λ values.",
        "",
        "The older non-preemptive delayed-start `price_aware` scheduler model is intentionally not part of this report.",
        "",
        "## Run configuration",
        "",
        f"- price_source: `{price_source}`",
        f"- price_offset_h: `{price_offset_h}`",
        f"- arrival/simulation horizon: `{arrival_horizon_h}` h (`{arrival_horizon_h / 24:.1f}` days)",
        f"- loaded price horizon: `{price_horizon_h}` h",
        f"- capacity_nodes: `{capacity_nodes}`",
        f"- power_kw_per_node: `{power_kw_per_node:g}`",
        f"- seeds: `{', '.join(str(seed) for seed in seeds)}`",
        f"- lambda_values: `{', '.join(f'{value:g}' for value in lambdas)}`",
        f"- parallel_workers: `{max_workers}`",
        f"- qos_violation_penalty_eur for λ ranking: `{qos_violation_penalty_eur:g}`",
        f"- maximum generated job duration observed: `{max_duration}` h",
        "",
        "## Workload scale",
        "",
        f"- Mean jobs per low workload: `{mean_jobs_by_load['low']}`.",
        f"- Mean jobs per medium workload: `{mean_jobs_by_load['medium']}`.",
        f"- Mean jobs per high workload: `{mean_jobs_by_load['high']}`.",
        f"- Mean jobs per mixed workload: `{mean_jobs_by_load['mixed']}`.",
        "- Runtime classes: `short_debug` = 1–6 h, `medium` = 6–48 h, `long` = 48–336 h.",
        "",
        "## Current policy model",
        "",
        "Jobs reserve their requested node count until completion. The hourly `JobProfile` controls how many of those reserved nodes are active and therefore how much electricity cost is incurred. In the current preemptive policy, checkpointable jobs can be paused/resumed at hourly boundaries, but paused jobs keep their reserved nodes.",
        "",
        "The λ parameter is an urgency term in the hourly run/skip decision. Lower λ lets the policy wait more aggressively for cheap hours; higher λ makes it less willing to delay when the expected saving is small.",
        "",
        "## Best λ by QoS-penalized objective",
        "",
    ]
    for row in best_rows:
        lines.append(
            f"- {row['load_level']}: λ=`{row['delay_penalty_lambda']}`; cost={row['total_cost_eur_mean']} €, cost/job={row['cost_per_completed_job_eur_mean']} €, paid_price={row['mean_paid_price_eur_per_mwh_mean']} €/MWh, QoS={row['qos_violations_mean']}, avg_wait={row['avg_wait_h_mean']} h, penalized={row['qos_penalized_objective_eur_mean']} €."
        )
    lines.extend([
        "",
        "## Plots",
        "",
        f"![Total cost by load]({plot_names['total_cost_by_load.png']})",
        "",
        f"![Cost per completed job by load]({plot_names['cost_per_job_by_load.png']})",
        "",
        f"![Normalized paid price by load]({plot_names['normalized_price_by_load.png']})",
        "",
        f"![QoS violations by load]({plot_names['qos_violations_by_load.png']})",
        "",
        f"![QoS violation rate by load]({plot_names['qos_violation_rate_percent_by_load.png']})",
        "",
        f"![Average wait by load]({plot_names['wait_by_load.png']})",
        "",
        f"![Suspension activity by load]({plot_names['suspension_by_load.png']})",
        "",
        f"![Synthetic profile examples]({plot_names['synthetic_profile_examples.png']})",
        "",
        "## Summary table",
        "",
        *compact_table(summary_rows),
        "",
        "## Generated files",
        "",
        "- `REPORT.md` — this report.",
        "- `RUNS.md` — raw run log in Markdown.",
        "- `runs.csv` — raw per-policy, per-seed, per-load, per-λ results.",
        "- `summary.csv` — mean metrics by workload and policy variant.",
        "- `workloads.csv` — generated workload composition by seed/load.",
        "- `total_cost_by_load.png`, `cost_per_job_by_load.png`, `normalized_price_by_load.png`, `qos_violations_by_load.png`, `qos_violation_rate_percent_by_load.png`, `wait_by_load.png`, `suspension_by_load.png`, `synthetic_profile_examples.png`.",
        "",
    ])
    path.write_text("\n".join(lines))


def write_runs_markdown(path: Path, runs: list[dict[str, object]], workload_rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Run Log — Current Policy Evaluation",
        "",
        "## Workload composition by seed/load",
        "",
        "| load | seed | jobs | short | medium | long | max h | mean h | requested node-h | active node-h | flat | front | back | valley | peak | ramp up | ramp down |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in workload_rows:
        lines.append(
            "| {load_level} | {seed} | {jobs} | {short_debug_jobs} | {medium_jobs} | {long_jobs} | {max_duration_h} | {mean_duration_h} | {requested_node_hours} | {active_node_hours} | {flat_profiles} | {front_loaded_profiles} | {back_loaded_profiles} | {valley_profiles} | {peak_profiles} | {ramp_up_profiles} | {ramp_down_profiles} |".format(**row)
        )
    lines.extend([
        "",
        "## Raw scheduler runs",
        "",
        "| load | seed | policy variant | λ | completed/total | QoS | cost € | cost/job € | paid €/MWh | avg wait h | p95 wait h | response h | slowdown | reserved util | active node-h | reserved node-h | preempted | suspended h | suspended reserved node-h |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for row in runs:
        lines.append(
            "| {load_level} | {seed} | {policy_variant} | {delay_penalty_lambda} | {scheduled_jobs}/{total_jobs} | {qos_violations} | {total_cost_eur} | {cost_per_completed_job_eur} | {mean_paid_price_eur_per_mwh} | {avg_wait_h} | {p95_wait_h} | {avg_response_h} | {avg_bounded_slowdown} | {utilization} | {active_node_hours} | {reserved_node_hours} | {preempted_jobs} | {suspended_job_hours} | {suspended_reserved_node_hours} |".format(**row)
        )
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser(description="Parallel current policy evaluation with multi-lambda sweep, report, and plots.")
    parser.add_argument("--prices", default="data/prices/smard_de_lu_2024_hourly.csv")
    parser.add_argument("--horizon", type=int, default=24 * 60)
    parser.add_argument("--price-offset", type=int, default=0)
    parser.add_argument("--capacity", type=int, default=64)
    parser.add_argument("--power-kw-per-node", type=float, default=1.0)
    parser.add_argument("--qos-violation-penalty-eur", type=float, default=DEFAULT_QOS_VIOLATION_PENALTY_EUR)
    parser.add_argument("--lambdas", default=",".join(str(value) for value in DEFAULT_LAMBDAS))
    parser.add_argument("--seeds", default=",".join(str(value) for value in DEFAULT_SEEDS))
    parser.add_argument("--workers", type=int, default=max(1, min(os.cpu_count() or 1, 12)))
    parser.add_argument("--out-dir", default="docs/ten-seed-policy-evaluation")
    args = parser.parse_args()

    if args.qos_violation_penalty_eur < 0:
        raise ValueError("qos violation penalty must be non-negative")
    lambdas = parse_lambdas(args.lambdas)
    seeds = parse_ints(args.seeds)
    prices = tuple(load_prices(ROOT / args.prices, limit=args.horizon, offset=args.price_offset))
    out_dir = ROOT / args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    workload_rows: list[dict[str, object]] = []
    for seed in seeds:
        for load in LOAD_LEVELS:
            jobs = generate_workload(load, horizon_hours=args.horizon, seed=workload_seed(seed, load))
            workload_rows.append(workload_summary(load, workload_seed(seed, load), jobs, args.horizon))

    tasks: list[RunTask] = []
    for seed in seeds:
        for load in LOAD_LEVELS:
            for policy in BASELINE_POLICIES:
                tasks.append(RunTask(load, seed, policy, None, prices, args.capacity, args.power_kw_per_node, args.horizon))
            for lambda_value in lambdas:
                tasks.append(RunTask(load, seed, CURRENT_POLICY, lambda_value, prices, args.capacity, args.power_kw_per_node, args.horizon))

    print(f"Running {len(tasks)} simulations: {len(seeds)} seeds × {len(LOAD_LEVELS)} loads × (2 baselines + {len(lambdas)} λ values) with {args.workers} workers...")
    run_rows: list[dict[str, object]] = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        future_map = {executor.submit(run_task, task): task for task in tasks}
        for completed, future in enumerate(as_completed(future_map), start=1):
            task = future_map[future]
            row = future.result()
            run_rows.append(row)
            print(f"[{completed:03d}/{len(tasks)}] {task.load_level} seed={task.seed} {policy_variant(task.policy, task.lambda_value)} done")

    policy_order = {"fcfs": 0, "easy_backfill": 1, CURRENT_POLICY: 2}
    run_rows.sort(key=lambda row: (LOAD_LEVELS.index(str(row["load_level"])), int(row["seed"]), policy_order[str(row["policy"])], float(row["delay_penalty_lambda"]) if row["delay_penalty_lambda"] != "baseline" else -1.0))
    summary_rows = summarize(run_rows, qos_violation_penalty_eur=args.qos_violation_penalty_eur)
    write_csv(out_dir / "runs.csv", run_rows)
    write_csv(out_dir / "summary.csv", summary_rows)
    write_csv(out_dir / "workloads.csv", workload_rows)
    plot_paths = plot_all(summary_rows, out_dir)
    write_report(
        out_dir / "REPORT.md",
        summary_rows=summary_rows,
        workload_rows=workload_rows,
        seeds=seeds,
        lambdas=lambdas,
        arrival_horizon_h=args.horizon,
        price_horizon_h=len(prices),
        price_source=args.prices,
        price_offset_h=args.price_offset,
        capacity_nodes=args.capacity,
        power_kw_per_node=args.power_kw_per_node,
        qos_violation_penalty_eur=args.qos_violation_penalty_eur,
        max_workers=args.workers,
        plot_paths=plot_paths,
    )
    write_runs_markdown(out_dir / "RUNS.md", run_rows, workload_rows)
    print(f"Wrote {out_dir / 'REPORT.md'}")
    for path in plot_paths:
        print(f"Wrote {path}")
    print("Best λ by load:")
    for row in best_lambda_rows(summary_rows):
        print(f"{row['load_level']}: lambda={row['delay_penalty_lambda']}, cost={row['total_cost_eur_mean']}, paid_price={row['mean_paid_price_eur_per_mwh_mean']}, qos={row['qos_violations_mean']}, penalized={row['qos_penalized_objective_eur_mean']}")


if __name__ == "__main__":
    main()
