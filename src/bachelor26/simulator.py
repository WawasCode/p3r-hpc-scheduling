from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import math
import random
import statistics
from typing import Iterable, Sequence


@dataclass(frozen=True)
class JobProfile:
    """Time-varying active-node usage for a job.

    `active_nodes_by_hour[k]` describes how many of the job's requested nodes
    are actively used during profile hour `k`. The scheduler still reserves the
    job's full requested node count; this profile changes cost/energy accounting
    and price-aware scoring.
    """

    name: str
    active_nodes_by_hour: Sequence[int]

    def __post_init__(self) -> None:
        active_nodes = tuple(int(value) for value in self.active_nodes_by_hour)
        if not active_nodes:
            raise ValueError("job profile must contain at least one active-node step")
        if any(value < 0 for value in active_nodes):
            raise ValueError("job profile active nodes must be non-negative")
        object.__setattr__(self, "active_nodes_by_hour", active_nodes)

    def validate_for(self, requested_nodes: int, duration: int) -> None:
        if len(self.active_nodes_by_hour) != duration:
            raise ValueError(
                f"job profile length {len(self.active_nodes_by_hour)} must match duration {duration}"
            )
        if any(value > requested_nodes for value in self.active_nodes_by_hour):
            raise ValueError("job profile active nodes cannot exceed requested nodes")

    def active_nodes_at(self, offset: int) -> int:
        return int(self.active_nodes_by_hour[offset])


@dataclass(frozen=True)
class Job:
    job_id: int
    submit_time: int
    duration: int
    nodes: int
    max_wait: int
    profile: JobProfile | None = None
    job_class: str = "unknown"
    preemptible: bool = True

    def __post_init__(self) -> None:
        if self.duration <= 0:
            raise ValueError("job duration must be positive")
        if self.nodes <= 0:
            raise ValueError("job requested nodes must be positive")
        if self.max_wait < 0:
            raise ValueError("job max_wait must be non-negative")
        profile = self.profile or JobProfile("flat", tuple([self.nodes] * self.duration))
        profile.validate_for(self.nodes, self.duration)
        object.__setattr__(self, "profile", profile)

    @property
    def latest_start(self) -> int:
        return self.submit_time + self.max_wait

    def active_nodes_at(self, offset: int) -> int:
        if self.profile is None:  # defensive only; __post_init__ always sets it
            return self.nodes
        return self.profile.active_nodes_at(offset)


@dataclass
class ScheduledJob:
    job: Job
    start_time: int

    @property
    def end_time(self) -> int:
        return self.start_time + self.job.duration


@dataclass
class PreemptiveJobState:
    """Hourly execution state for checkpointable/suspendable jobs."""

    job: Job
    progress: int = 0
    first_start: int | None = None
    completion_time: int | None = None
    suspended_hours: int = 0
    preemptions: int = 0
    ran_previous_hour: bool = False

    @property
    def remaining(self) -> int:
        return self.job.duration - self.progress

    @property
    def deadline(self) -> int:
        return self.job.submit_time + self.job.max_wait + self.job.duration

    @property
    def completed(self) -> bool:
        return self.completion_time is not None

    @property
    def started(self) -> bool:
        return self.first_start is not None


@dataclass
class PolicyResult:
    policy: str
    load_level: str
    scheduled_jobs: int
    qos_violations: int
    total_jobs: int
    total_cost_eur: float
    avg_wait_h: float
    p95_wait_h: float
    avg_response_h: float
    avg_bounded_slowdown: float
    utilization: float
    active_node_hours: int = 0
    reserved_node_hours: int = 0
    mean_paid_price_eur_per_mwh: float = 0.0
    preempted_jobs: int = 0
    suspended_job_hours: int = 0
    suspended_reserved_node_hours: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "policy": self.policy,
            "load_level": self.load_level,
            "scheduled_jobs": self.scheduled_jobs,
            "qos_violations": self.qos_violations,
            "total_jobs": self.total_jobs,
            "total_cost_eur": round(self.total_cost_eur, 4),
            "avg_wait_h": round(self.avg_wait_h, 4),
            "p95_wait_h": round(self.p95_wait_h, 4),
            "avg_response_h": round(self.avg_response_h, 4),
            "avg_bounded_slowdown": round(self.avg_bounded_slowdown, 4),
            "utilization": round(self.utilization, 4),
            "active_node_hours": self.active_node_hours,
            "reserved_node_hours": self.reserved_node_hours,
            "mean_paid_price_eur_per_mwh": round(self.mean_paid_price_eur_per_mwh, 4),
            "preempted_jobs": self.preempted_jobs,
            "suspended_job_hours": self.suspended_job_hours,
            "suspended_reserved_node_hours": self.suspended_reserved_node_hours,
        }


def load_prices(path: str | Path, limit: int | None = None, offset: int = 0) -> list[float]:
    prices: list[float] = []
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            prices.append(float(row["price_eur_per_mwh"]))
    if offset:
        prices = prices[offset:]
    if limit is not None:
        prices = prices[:limit]
    if not prices:
        raise ValueError(f"no prices loaded from {path}")
    return prices


def _poisson(lam: float, rng: random.Random) -> int:
    threshold = math.exp(-lam)
    k = 0
    product = 1.0
    while product > threshold:
        k += 1
        product *= rng.random()
    return k - 1


RUNTIME_CLASSES = ("short_debug", "medium", "long")


def _make_job_profile(job_class: str, duration: int, nodes: int, rng: random.Random) -> JobProfile:
    """Create a lightweight active-node profile for synthetic jobs.

    The profile is intentionally simple: requested nodes still reserve capacity,
    while active nodes vary by phase to give the price-aware scheduler a shape to
    optimize against. Shapes include flat, front-loaded, back-loaded, valley,
    peak, ramp-up, and ramp-down behavior so long realistic jobs are not all
    constant-node runs.
    """
    if duration == 1:
        return JobProfile(f"{job_class}_flat", (nodes,))

    low_nodes = max(0, nodes // 2)
    high_nodes = nodes
    shape = rng.choices(
        ["flat", "front_loaded", "back_loaded", "valley", "peak", "ramp_up", "ramp_down"],
        weights=[25, 22, 22, 11, 8, 6, 6],
        k=1,
    )[0]

    def interpolate(start: int, end: int, steps: int) -> list[int]:
        if steps <= 1:
            return [end]
        return [int(round(start + (end - start) * idx / (steps - 1))) for idx in range(steps)]

    if shape == "flat":
        active = [high_nodes] * duration
    elif shape == "front_loaded":
        split = max(1, math.ceil(duration * 0.4))
        active = [high_nodes] * split + [low_nodes] * (duration - split)
    elif shape == "back_loaded":
        split = max(1, math.floor(duration * 0.6))
        active = [low_nodes] * split + [high_nodes] * (duration - split)
    elif shape == "valley":
        active = [high_nodes] * duration
        middle_start = duration // 3
        middle_end = max(middle_start + 1, math.ceil(duration * 2 / 3))
        for idx in range(middle_start, min(duration, middle_end)):
            active[idx] = low_nodes
    elif shape == "peak":
        active = [low_nodes] * duration
        middle_start = duration // 3
        middle_end = max(middle_start + 1, math.ceil(duration * 2 / 3))
        for idx in range(middle_start, min(duration, middle_end)):
            active[idx] = high_nodes
    elif shape == "ramp_up":
        active = interpolate(low_nodes, high_nodes, duration)
    else:
        active = interpolate(high_nodes, low_nodes, duration)
    if max(active) == 0:
        active[-1] = 1
    return JobProfile(f"{job_class}_{shape}", tuple(active))


def _sample_job_shape(load_level: str, rng: random.Random) -> tuple[str, int, int, float]:
    """Sample class, duration, requested nodes, and runtime-scaled wait factor.

    Runtime classes are intentionally capped at 14 days (336 h). This makes the
    default synthetic workload more realistic for long HPC jobs without adding
    rare >14-day hero runs to the Bachelor-scope comparison.
    """
    if load_level == "mixed":
        job_class = rng.choices(RUNTIME_CLASSES, weights=[45, 38, 17], k=1)[0]
    else:
        job_class = rng.choices(RUNTIME_CLASSES, weights=[50, 37, 13], k=1)[0]

    if job_class == "short_debug":
        nodes = rng.choices([1, 2, 4], weights=[55, 35, 10], k=1)[0]
        duration = rng.randint(1, 6)
        qos_factor = rng.choices([1.0, 2.0, 3.0], weights=[35, 50, 15], k=1)[0]
    elif job_class == "medium":
        nodes = rng.choices([1, 2, 4, 8], weights=[35, 30, 20, 15], k=1)[0]
        duration = max(6, min(48, int(round(rng.lognormvariate(2.75, 0.55)))))
        qos_factor = rng.choices([0.75, 1.0, 1.5, 2.0], weights=[20, 35, 35, 10], k=1)[0]
    else:
        # Job width is capped at 10 of 64 nodes, about a sixth of the cluster,
        # like the job size limit of the cluster that motivates the thesis.
        nodes = rng.choices([4, 8, 10], weights=[40, 35, 25], k=1)[0]
        duration = max(48, min(336, int(round(rng.lognormvariate(4.55, 0.55)))))
        # Add an explicit chance of a 14-day realistic longest job so experiment
        # documentation and generated runs include the upper bound.
        if rng.random() < 0.08:
            duration = 336
        qos_factor = rng.choices([0.25, 0.5, 0.75, 1.0], weights=[20, 45, 25, 10], k=1)[0]
    return job_class, duration, nodes, qos_factor


def generate_workload(load_level: str, horizon_hours: int, seed: int = 42) -> list[Job]:
    # Base arrival rates in jobs per hour, chosen so that the four levels offer
    # about 0.34, 0.77, 1.23, and 1.23 of the cluster's node-hours.
    rates = {"low": 0.16, "medium": 0.355, "high": 0.58, "mixed": 0.46}
    if load_level not in rates:
        raise ValueError(f"unknown load level {load_level!r}; expected one of {sorted(rates)}")
    rng = random.Random(seed)
    jobs: list[Job] = []
    next_id = 0
    for hour in range(horizon_hours):
        hour_of_day = hour % 24
        day_of_week = (hour // 24) % 7
        daytime_factor = 1.25 if 8 <= hour_of_day <= 18 else 0.70
        weekday_factor = 1.15 if day_of_week < 5 else 0.75
        arrivals = _poisson(rates[load_level] * daytime_factor * weekday_factor, rng)
        for _ in range(arrivals):
            job_class, duration, nodes, qos_factor = _sample_job_shape(load_level, rng)
            max_wait = max(1, int(math.ceil(duration * qos_factor)))
            profile = _make_job_profile(job_class, duration, nodes, rng)
            jobs.append(Job(next_id, hour, duration, nodes, max_wait, profile=profile, job_class=job_class))
            next_id += 1
    return jobs


def _used_nodes_at(running: Sequence[ScheduledJob], hour: int) -> int:
    return sum(item.job.nodes for item in running if item.start_time <= hour < item.end_time)


def _can_start(job: Job, start: int, running: Sequence[ScheduledJob], capacity_nodes: int, horizon: int) -> bool:
    # A job may start even if it cannot finish before the horizon, like in the
    # preemptive policy: it runs until the horizon, is charged for those hours,
    # and counts as a violation. Capacity is only checked inside the horizon.
    if start < job.submit_time or start >= horizon:
        return False
    for hour in range(start, min(start + job.duration, horizon)):
        if _used_nodes_at(running, hour) + job.nodes > capacity_nodes:
            return False
    return True


def _earliest_start(job: Job, now: int, running: Sequence[ScheduledJob], capacity_nodes: int, horizon: int) -> int | None:
    for start in range(max(now, job.submit_time), horizon):
        if _can_start(job, start, running, capacity_nodes, horizon):
            return start
    return None


def _job_cost(job: Job, start: int, prices: Sequence[float], power_kw_per_node: float) -> float:
    # Only hours inside the price trace are charged; a job still running at the
    # horizon pays for the hours it ran, as in the preemptive policy.
    return sum(
        job.active_nodes_at(h - start) * power_kw_per_node * (prices[h] / 1000.0)
        for h in range(start, min(start + job.duration, len(prices)))
    )


def _job_active_node_hours(job: Job, start: int, horizon: int) -> int:
    return sum(job.active_nodes_at(h - start) for h in range(start, min(start + job.duration, horizon)))


def _mean_paid_price(total_cost_eur: float, active_node_hours: int, power_kw_per_node: float) -> float:
    energy_mwh = active_node_hours * power_kw_per_node / 1000.0
    return total_cost_eur / energy_mwh if energy_mwh > 0 else 0.0


def _start(job: Job, start: int, running: list[ScheduledJob], scheduled: list[ScheduledJob]) -> None:
    item = ScheduledJob(job, start)
    running.append(item)
    scheduled.append(item)


def _schedule_fcfs(now: int, pending: list[Job], running: list[ScheduledJob], scheduled: list[ScheduledJob], capacity_nodes: int, horizon: int) -> None:
    while pending and _can_start(pending[0], now, running, capacity_nodes, horizon):
        _start(pending.pop(0), now, running, scheduled)


def _schedule_easy_backfill(now: int, pending: list[Job], running: list[ScheduledJob], scheduled: list[ScheduledJob], capacity_nodes: int, horizon: int) -> list[Job]:
    violations: list[Job] = []
    while pending and _can_start(pending[0], now, running, capacity_nodes, horizon):
        _start(pending.pop(0), now, running, scheduled)
    if not pending:
        return violations
    head = pending[0]
    # A head that cannot start before the horizon has its reservation at the
    # horizon: no backfilled job can delay it, so every job that fits may start.
    reservation_start = _earliest_start(head, now, running, capacity_nodes, horizon)
    if reservation_start is None:
        reservation_start = horizon
    keep: list[Job] = [head]
    for job in pending[1:]:
        if not _can_start(job, now, running, capacity_nodes, horizon):
            keep.append(job)
            continue
        trial_running = [*running, ScheduledJob(job, now)]
        new_reservation = _earliest_start(head, now, trial_running, capacity_nodes, horizon)
        if (horizon if new_reservation is None else new_reservation) <= reservation_start:
            _start(job, now, running, scheduled)
        else:
            keep.append(job)
    pending[:] = keep
    return violations


def _delayed_start_objective(
    job: Job,
    start: int,
    prices: Sequence[float],
    power_kw_per_node: float,
    delay_penalty_lambda: float,
) -> float:
    """Profile-aware delayed-start score for non-preemptible jobs inside the current policy.

    The repository no longer exposes the old non-preemptive `price_aware` policy.
    This helper remains only so `price_aware_preemptive` can choose sensible
    start times for jobs marked `preemptible=False`.
    """
    cost = _job_cost(job, start, prices, power_kw_per_node)
    normalized_wait = (start - job.submit_time) / max(1, job.max_wait)
    return cost + delay_penalty_lambda * normalized_wait


def _must_run_now(state: PreemptiveJobState, now: int, horizon: int) -> bool:
    remaining_window = max(0, min(state.deadline, horizon) - now)
    return state.remaining >= remaining_window


def _run_and_skip_costs(active: Sequence[int], window: Sequence[float]) -> tuple[float, float]:
    """Exact run_now and skip_now costs from one BestCost table.

    B(s, i) is the cheapest placement of profile steps s..m-1 into window hours
    i..n-1, in order. Then run_now = active[0] * window[0] + B(1, 1) and
    skip_now = B(0, 1). Only cells with enough hours left for the remaining
    steps are feasible, so each row is filled over a band of n - m + 1 hours,
    and the table costs m * (n - m + 1) operations. Requires n > m.
    """
    steps = len(active)
    hours = len(window)
    inf = math.inf
    next_row = [0.0] * (hours + 1)  # row s = m: nothing left to place
    b_1_1 = 0.0 if steps == 1 else inf
    for step in range(steps - 1, -1, -1):
        row = [inf] * (hours + 1)
        nodes = float(active[step])
        best = inf  # B(step, i + 1); infinite past the last feasible hour
        for i in range(hours - (steps - step), step - 1, -1):
            run = nodes * window[i] + next_row[i + 1]
            if run < best:
                best = run
            row[i] = best
        if step == 1:
            b_1_1 = row[1]
        next_row = row
    return active[0] * window[0] + b_1_1, next_row[1]


def _profile_lookahead_should_run(state: PreemptiveJobState, now: int, prices: Sequence[float], delay_penalty_lambda: float) -> bool:
    """Return True if the current profile step should execute now.

    The rule compares two profile-weighted lookahead choices over the remaining
    deadline window: execute the current profile step now, or keep the job paused
    for this hour.  It estimates the remaining opportunity cost by matching high
    active-node profile steps to the cheapest available future price hours.  This
    is stronger than looking only at the current spot price: it can decide to run
    a low-active profile step during a moderately expensive hour if that preserves
    a later cheap hour for a high-active step.

    `delay_penalty_lambda` adds a transparent urgency term. A higher value makes
    the scheduler less willing to skip the current hour when the pure
    profile-price optimum is nearly indifferent.
    """
    job = state.job
    window_end = min(state.deadline, len(prices))
    if now >= window_end:
        return True
    if state.remaining >= window_end - now:
        return True

    window_prices = [float(prices[hour]) for hour in range(now, window_end)]
    remaining_active = [job.active_nodes_at(offset) for offset in range(state.progress, job.duration)]
    if len(remaining_active) >= len(window_prices):
        return True
    run_now_cost, skip_now_cost = _run_and_skip_costs(remaining_active, window_prices)

    price_span = max(window_prices) - min(window_prices) if window_prices else 0.0
    average_active_nodes = sum(remaining_active) / max(1, len(remaining_active))
    delay_penalty = delay_penalty_lambda * price_span * max(1.0, average_active_nodes)
    return run_now_cost <= skip_now_cost + delay_penalty


def _non_preemptible_should_start(
    state: PreemptiveJobState,
    now: int,
    prices: Sequence[float],
    capacity_nodes: int,
    power_kw_per_node: float,
    delay_penalty_lambda: float,
) -> bool:
    job = state.job
    latest_start = job.latest_start
    if now >= latest_start:
        return True
    feasible_starts = range(now, min(latest_start, len(prices) - job.duration) + 1)
    best_start: int | None = None
    best_score: float | None = None
    for start in feasible_starts:
        score = _delayed_start_objective(job, start, prices, power_kw_per_node, delay_penalty_lambda)
        if best_score is None or (score, start) < (best_score, best_start if best_start is not None else start):
            best_score = score
            best_start = start
    return best_start == now


def _preemptive_priority(state: PreemptiveJobState, now: int, prices: Sequence[float], mandatory: bool) -> tuple[object, ...]:
    slack = state.deadline - now - state.remaining
    active_nodes = state.job.active_nodes_at(state.progress)
    current_cost = active_nodes * float(prices[now])
    return (0 if mandatory else 1, state.deadline, slack, current_cost, state.job.job_id)


def _simulate_price_aware_preemptive(
    all_jobs: list[Job],
    prices: Sequence[float],
    *,
    load_level: str,
    capacity_nodes: int,
    power_kw_per_node: float,
    delay_penalty_lambda: float,
) -> PolicyResult:
    jobs_by_submit: dict[int, list[Job]] = {}
    for job in all_jobs:
        jobs_by_submit.setdefault(job.submit_time, []).append(job)

    horizon = len(prices)
    states: dict[int, PreemptiveJobState] = {}
    total_cost = 0.0
    active_node_hours = 0
    reserved_node_hours = 0
    suspended_reserved_node_hours = 0

    for now in range(horizon):
        for job in jobs_by_submit.get(now, []):
            states[job.job_id] = PreemptiveJobState(job)

        active_states = [state for state in states.values() if not state.completed and state.job.submit_time <= now]
        already_reserved = [state for state in active_states if state.started and state.remaining > 0]
        reserved_ids = {state.job.job_id for state in already_reserved}
        capacity_left_for_new = capacity_nodes - sum(state.job.nodes for state in already_reserved)
        mandatory: list[PreemptiveJobState] = []
        opportunistic: list[PreemptiveJobState] = []

        for state in active_states:
            job = state.job
            if state.remaining <= 0:
                continue
            if not job.preemptible:
                if state.started or _non_preemptible_should_start(
                    state,
                    now,
                    prices,
                    capacity_nodes,
                    power_kw_per_node,
                    delay_penalty_lambda,
                ):
                    mandatory.append(state)
                continue
            must_run = _must_run_now(state, now, horizon)
            if must_run:
                mandatory.append(state)
            elif _profile_lookahead_should_run(state, now, prices, delay_penalty_lambda):
                opportunistic.append(state)

        selected: list[PreemptiveJobState] = []

        def select_if_capacity_allows(state: PreemptiveJobState) -> bool:
            nonlocal capacity_left_for_new
            if state in selected:
                return True
            if state.job.job_id in reserved_ids:
                selected.append(state)
                return True
            if state.job.nodes <= capacity_left_for_new:
                selected.append(state)
                capacity_left_for_new -= state.job.nodes
                reserved_ids.add(state.job.job_id)
                return True
            return False

        for state in sorted(mandatory, key=lambda item: _preemptive_priority(item, now, prices, True)):
            select_if_capacity_allows(state)
        for state in sorted(opportunistic, key=lambda item: _preemptive_priority(item, now, prices, False)):
            select_if_capacity_allows(state)

        selected_ids = {state.job.job_id for state in selected}
        hour_reserved_ids = set(reserved_ids)
        for state in active_states:
            if state.completed:
                continue
            if state.job.job_id not in selected_ids:
                if state.started and state.job.preemptible:
                    state.suspended_hours += 1
                    suspended_reserved_node_hours += state.job.nodes
                    if state.ran_previous_hour:
                        state.preemptions += 1
                state.ran_previous_hour = False

        for state in selected:
            if state.first_start is None:
                state.first_start = now
                hour_reserved_ids.add(state.job.job_id)
            active_nodes = state.job.active_nodes_at(state.progress)
            total_cost += active_nodes * power_kw_per_node * (float(prices[now]) / 1000.0)
            active_node_hours += active_nodes
            state.progress += 1
            state.ran_previous_hour = True
            if state.progress >= state.job.duration:
                state.completion_time = now + 1
                state.ran_previous_hour = False
        reserved_node_hours += sum(states[job_id].job.nodes for job_id in hour_reserved_ids)

    completed_states = [state for state in states.values() if state.completed]
    violation_ids = {
        state.job.job_id
        for state in states.values()
        if state.completion_time is None or state.completion_time > state.deadline
    }
    # Jobs submitted after the simulated horizon are outside this replay window;
    # all generated jobs are normally submitted within the horizon.
    known_ids = set(states)
    violation_ids.update(job.job_id for job in all_jobs if job.job_id not in known_ids and job.submit_time < horizon)

    waits = [(state.first_start or state.job.submit_time) - state.job.submit_time for state in completed_states]
    responses = [(state.completion_time or horizon) - state.job.submit_time for state in completed_states]
    slowdowns = [resp / max(1, state.job.duration) for resp, state in zip(responses, completed_states)]
    p95 = statistics.quantiles(waits, n=20, method="inclusive")[18] if len(waits) > 1 else (waits[0] if waits else 0.0)
    return PolicyResult(
        policy="price_aware_preemptive",
        load_level=load_level,
        scheduled_jobs=len(completed_states),
        qos_violations=len(violation_ids),
        total_jobs=len(all_jobs),
        total_cost_eur=total_cost,
        avg_wait_h=statistics.mean(waits) if waits else 0.0,
        p95_wait_h=float(p95),
        avg_response_h=statistics.mean(responses) if responses else 0.0,
        avg_bounded_slowdown=statistics.mean(slowdowns) if slowdowns else 0.0,
        utilization=reserved_node_hours / (capacity_nodes * horizon) if horizon else 0.0,
        active_node_hours=active_node_hours,
        reserved_node_hours=reserved_node_hours,
        mean_paid_price_eur_per_mwh=_mean_paid_price(total_cost, active_node_hours, power_kw_per_node),
        preempted_jobs=sum(1 for state in states.values() if state.preemptions > 0),
        suspended_job_hours=sum(state.suspended_hours for state in states.values()),
        suspended_reserved_node_hours=suspended_reserved_node_hours,
    )


def simulate(
    jobs: Iterable[Job],
    prices: Sequence[float],
    policy: str,
    load_level: str = "unknown",
    capacity_nodes: int = 64,
    power_kw_per_node: float = 1.0,
    delay_penalty_lambda: float = 0.0,
) -> PolicyResult:
    if delay_penalty_lambda < 0:
        raise ValueError("delay_penalty_lambda must be non-negative")
    jobs_by_submit: dict[int, list[Job]] = {}
    all_jobs = sorted(list(jobs), key=lambda j: (j.submit_time, j.job_id))
    if policy == "price_aware_preemptive":
        return _simulate_price_aware_preemptive(
            all_jobs,
            prices,
            load_level=load_level,
            capacity_nodes=capacity_nodes,
            power_kw_per_node=power_kw_per_node,
            delay_penalty_lambda=delay_penalty_lambda,
        )
    for job in all_jobs:
        jobs_by_submit.setdefault(job.submit_time, []).append(job)
    horizon = len(prices)
    pending: list[Job] = []
    running: list[ScheduledJob] = []
    scheduled: list[ScheduledJob] = []
    violations: list[Job] = []
    for now in range(horizon):
        running[:] = [item for item in running if item.end_time > now]
        pending.extend(jobs_by_submit.get(now, []))
        pending.sort(key=lambda j: (j.submit_time, j.job_id))
        if policy == "fcfs":
            _schedule_fcfs(now, pending, running, scheduled, capacity_nodes, horizon)
        elif policy == "easy_backfill":
            violations.extend(_schedule_easy_backfill(now, pending, running, scheduled, capacity_nodes, horizon))
        else:
            raise ValueError(f"unknown policy {policy!r}")
    # Same semantics as the preemptive policy: a job that starts after its
    # latest start time completes late and counts as one violation; a job
    # that does not complete before the horizon, started or not, counts as
    # well. Wait and response statistics cover completed jobs only.
    completed = [item for item in scheduled if item.end_time <= horizon]
    violations.extend(item.job for item in scheduled if item.start_time > item.job.latest_start or item.end_time > horizon)
    violations.extend(pending)
    waits = [item.start_time - item.job.submit_time for item in completed]
    responses = [item.end_time - item.job.submit_time for item in completed]
    slowdowns = [resp / max(1, item.job.duration) for resp, item in zip(responses, completed)]
    node_hours = sum(item.job.nodes * (min(item.end_time, horizon) - item.start_time) for item in scheduled)
    active_node_hours = sum(_job_active_node_hours(item.job, item.start_time, horizon) for item in scheduled)
    total_cost = sum(_job_cost(item.job, item.start_time, prices, power_kw_per_node) for item in scheduled)
    p95 = statistics.quantiles(waits, n=20, method="inclusive")[18] if len(waits) > 1 else (waits[0] if waits else 0.0)
    return PolicyResult(
        policy=policy,
        load_level=load_level,
        scheduled_jobs=len(completed),
        qos_violations=len({job.job_id for job in violations}),
        total_jobs=len(all_jobs),
        total_cost_eur=total_cost,
        avg_wait_h=statistics.mean(waits) if waits else 0.0,
        p95_wait_h=float(p95),
        avg_response_h=statistics.mean(responses) if responses else 0.0,
        avg_bounded_slowdown=statistics.mean(slowdowns) if slowdowns else 0.0,
        utilization=node_hours / (capacity_nodes * horizon) if horizon else 0.0,
        active_node_hours=active_node_hours,
        reserved_node_hours=node_hours,
        mean_paid_price_eur_per_mwh=_mean_paid_price(total_cost, active_node_hours, power_kw_per_node),
    )
