# src/powersite_autonomy/shadow_counterfactual.py
from __future__ import annotations

import math
from datetime import UTC, datetime
from statistics import mean

from .models import HistoryPoint, SiteConfig
from .shadow_models import (
    CounterfactualEvaluation,
    DecisionScore,
    EnergyPolicy,
    ManagedLoad,
    ModelFeedback,
    ShadowAutopilotPlan,
)

_SOLAR_METRICS = ("solar_input_power_w", "charge_output_power_w")
_LOAD_METRICS = ("system_load_power_w", "dc_load_power_w", "load_power_w")
_SOC_METRICS = ("battery_soc_percent",)


def _hour_key(timestamp: datetime) -> datetime:
    value = timestamp.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


def _first_series(
    history: dict[str, list[HistoryPoint]],
    names: tuple[str, ...],
) -> list[HistoryPoint]:
    for name in names:
        if history.get(name):
            return history[name]
    return []


def _bucket(points: list[HistoryPoint]) -> dict[datetime, float]:
    grouped: dict[datetime, list[float]] = {}
    for point in points:
        grouped.setdefault(_hour_key(point.timestamp), []).append(float(point.value))
    return {key: mean(values) for key, values in grouped.items()}


def _aligned(
    points: list[HistoryPoint],
    timeline: list[datetime],
) -> list[float | None]:
    values = _bucket(points)
    return [values.get(_hour_key(timestamp)) for timestamp in timeline]


def _mean_or_none(values: list[float]) -> float | None:
    return mean(values) if values else None


def _mae_bias(predicted: list[float], actual: list[float]) -> tuple[float | None, float | None]:
    if not predicted or not actual or len(predicted) != len(actual):
        return None, None
    errors = [
        prediction - observation
        for prediction, observation in zip(predicted, actual, strict=True)
    ]
    return mean(abs(error) for error in errors), mean(errors)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _action_hourly_power(
    plan: ShadowAutopilotPlan,
    kind: str,
    observed_hours: int,
) -> list[float]:
    result = [0.0] * observed_hours
    for action in plan.actions:
        if action.kind != kind or action.start_hour is None or action.duration_hours is None:
            continue
        power = action.planned_power_w or 0.0
        for index in range(action.start_hour, action.start_hour + action.duration_hours):
            if 0 <= index < observed_hours:
                result[index] += power
    return result


def _score(
    *,
    solar_w: list[float],
    load_w: list[float],
    extra_load_w: list[float],
    source_w: list[float],
    initial_soc_percent: float,
    config: SiteConfig,
    policy: EnergyPolicy,
    effective_capacity_wh: float,
    deferred_load_wh: float,
    load_interruptions: int,
    actual_soc: list[float | None] | None = None,
) -> DecisionScore:
    capacity = max(1.0, effective_capacity_wh)
    reserve_wh = capacity * policy.minimum_reserve_percent / 100
    energy_wh = capacity * _clamp(initial_soc_percent, 0.0, 100.0) / 100
    minimum_soc = 100 * energy_wh / capacity
    reserve_violation_wh = 0.0
    unserved_wh = 0.0
    surplus_wh = 0.0
    auxiliary_wh = sum(source_w)
    throughput_wh = 0.0

    for index, solar in enumerate(solar_w):
        load = max(0.0, load_w[index] + extra_load_w[index])
        production = max(0.0, solar + source_w[index])
        net = production - load
        surplus_wh += max(0.0, solar - load)
        if net >= 0:
            accepted = net
            if config.max_charge_power_w is not None:
                accepted = min(accepted, config.max_charge_power_w)
            stored = accepted * config.charge_efficiency
            before = energy_wh
            energy_wh = min(capacity, energy_wh + stored)
            throughput_wh += max(0.0, energy_wh - before)
        else:
            deficit = -net
            deliverable = deficit
            if config.max_discharge_power_w is not None:
                deliverable = min(deliverable, config.max_discharge_power_w)
            deliverable = min(deliverable, energy_wh * config.discharge_efficiency)
            before = energy_wh
            energy_wh -= deliverable / config.discharge_efficiency
            throughput_wh += max(0.0, before - energy_wh)
            unserved_wh += max(0.0, deficit - deliverable)
        reserve_violation_wh += max(0.0, reserve_wh - energy_wh)
        minimum_soc = min(minimum_soc, 100 * energy_wh / capacity)

    if actual_soc:
        observed = [value for value in actual_soc if value is not None]
        if observed:
            minimum_soc = min(observed)

    reserve_breached = minimum_soc <= policy.minimum_reserve_percent
    weights = policy.weights
    penalty = 0.0
    penalty += (100.0 if reserve_breached else 0.0) * weights.reserve_risk
    penalty += reserve_violation_wh / 1000 * weights.reserve_risk
    penalty += unserved_wh / 1000 * weights.unserved_critical_load
    penalty += surplus_wh / 1000 * weights.curtailed_solar
    penalty += auxiliary_wh / 1000 * weights.auxiliary_energy
    penalty += deferred_load_wh / 1000 * weights.deferred_load
    penalty += load_interruptions * weights.load_interruptions
    if policy.minimize_battery_degradation:
        penalty += throughput_wh / capacity * weights.battery_degradation

    emergency_gap = max(0.0, policy.emergency_reserve_percent - minimum_soc)
    penalty += emergency_gap * 10000
    return DecisionScore(
        total_penalty=max(0.0, penalty),
        minimum_soc_percent=minimum_soc,
        reserve_breached=reserve_breached,
        reserve_violation_wh=reserve_violation_wh,
        unserved_energy_wh=unserved_wh,
        surplus_energy_wh=surplus_wh,
        auxiliary_energy_wh=auxiliary_wh,
        deferred_load_wh=deferred_load_wh,
        battery_throughput_wh=throughput_wh,
        load_interruptions=load_interruptions,
    )


def _best_contiguous_start(
    load: ManagedLoad,
    solar_w: list[float],
    load_w: list[float],
    observed_hours: int,
) -> tuple[int, int, float] | None:
    earliest = min(load.earliest_start_hour, observed_hours)
    deadline = min(load.deadline_hour, observed_hours)
    duration = math.ceil(load.energy_required_wh / load.power_w)
    latest = deadline - duration
    if earliest > latest:
        return None
    best: tuple[float, int] | None = None
    for start in range(earliest, latest + 1):
        surplus = sum(
            max(0.0, solar_w[index] - load_w[index])
            for index in range(start, start + duration)
        )
        candidate = (surplus, -start)
        if best is None or candidate > best:
            best = candidate
    if best is None:
        return None
    start = -best[1]
    power = load.energy_required_wh / duration
    return start, duration, power


def _hindsight_loads(
    managed_loads: list[ManagedLoad],
    solar_w: list[float],
    load_w: list[float],
    observed_hours: int,
) -> tuple[list[float], float, int]:
    additions = [0.0] * observed_hours
    deferred = 0.0
    interruptions = 0
    for load in managed_loads:
        if not load.enabled:
            continue
        earliest = min(load.earliest_start_hour, observed_hours)
        deadline = min(load.deadline_hour, observed_hours)
        if earliest >= deadline:
            deferred += load.energy_required_wh
            continue
        if not load.interruptible:
            choice = _best_contiguous_start(load, solar_w, load_w, observed_hours)
            if choice is None:
                deferred += load.energy_required_wh
                continue
            start, duration, power = choice
            for index in range(start, start + duration):
                additions[index] += power
            continue

        ranked = sorted(
            range(earliest, deadline),
            key=lambda index: (solar_w[index] - load_w[index], -index),
            reverse=True,
        )
        remaining = load.energy_required_wh
        used = 0
        for index in ranked:
            if remaining <= 1e-6:
                break
            power = min(load.power_w, remaining)
            additions[index] += power
            remaining -= power
            used += 1
        if remaining > 1e-6:
            deferred += remaining
        interruptions += max(0, used - 1)
    return additions, deferred, interruptions


def _model_feedback(
    plan: ShadowAutopilotPlan,
    solar_actual: list[float | None],
    load_actual: list[float | None],
    soc_actual: list[float | None],
) -> ModelFeedback:
    solar_predicted: list[float] = []
    solar_observed: list[float] = []
    load_predicted: list[float] = []
    load_observed: list[float] = []
    soc_predicted: list[float] = []
    soc_observed: list[float] = []
    for index, point in enumerate(plan.baseline.points[: len(solar_actual)]):
        if solar_actual[index] is not None:
            solar_predicted.append(point.solar_p50_w)
            solar_observed.append(float(solar_actual[index]))
        if load_actual[index] is not None:
            load_predicted.append(point.load_p50_w)
            load_observed.append(float(load_actual[index]))
        if soc_actual[index] is not None:
            soc_predicted.append(point.soc_p50_percent)
            soc_observed.append(float(soc_actual[index]))

    solar_mae, solar_bias = _mae_bias(solar_predicted, solar_observed)
    load_mae, load_bias = _mae_bias(load_predicted, load_observed)
    soc_mae, soc_bias = _mae_bias(soc_predicted, soc_observed)
    sample_count = max(len(solar_observed), len(load_observed), len(soc_observed))

    pv_multiplier = 1.0
    if solar_predicted and sum(solar_predicted) > 50:
        pv_multiplier = _clamp(sum(solar_observed) / sum(solar_predicted), 0.5, 1.5)
    load_multiplier = 1.0
    if load_predicted and sum(load_predicted) > 50:
        load_multiplier = _clamp(sum(load_observed) / sum(load_predicted), 0.5, 1.5)

    solar_norm = (solar_mae or 0.0) / max(25.0, _mean_or_none(solar_observed) or 25.0)
    load_norm = (load_mae or 0.0) / max(25.0, _mean_or_none(load_observed) or 25.0)
    soc_norm = (soc_mae or 0.0) / 10.0
    ranked = sorted(
        [
            (solar_norm, "weather_or_pv_model"),
            (load_norm, "load_model"),
            (soc_norm, "battery_model"),
        ],
        reverse=True,
    )
    if sample_count < 4:
        attribution = "insufficient_data"
    elif ranked[0][0] < 0.15:
        attribution = "optimizer_or_policy"
    elif ranked[0][0] > ranked[1][0] * 1.5:
        attribution = ranked[0][1]
    else:
        attribution = "mixed"
    completeness = min(1.0, sample_count / 24)
    confidence = completeness * min(1.0, 0.5 + ranked[0][0])
    return ModelFeedback(
        site_uid=plan.site_uid,
        plan_id=plan.plan_id,
        sample_count=sample_count,
        solar_mae_w=solar_mae,
        solar_bias_w=solar_bias,
        load_mae_w=load_mae,
        load_bias_w=load_bias,
        soc_mae_percent=soc_mae,
        soc_bias_percent=soc_bias,
        recommended_pv_scale_multiplier=pv_multiplier,
        recommended_load_scale_multiplier=load_multiplier,
        primary_attribution=attribution,  # type: ignore[arg-type]
        confidence=confidence,
        notes=["Bias is forecast P50 minus observed telemetry."],
    )


def evaluate_shadow_plan(
    plan: ShadowAutopilotPlan,
    history: dict[str, list[HistoryPoint]],
    config: SiteConfig,
) -> CounterfactualEvaluation:
    now = datetime.now(UTC)
    timeline = [point.timestamp for point in plan.baseline.points if point.timestamp <= now]
    timeline = timeline[: plan.horizon_hours]
    observed_hours = len(timeline)
    if observed_hours == 0:
        timeline = [point.timestamp for point in plan.baseline.points[:1]]
        observed_hours = len(timeline)

    solar_actual = _aligned(_first_series(history, _SOLAR_METRICS), timeline)
    load_actual = _aligned(_first_series(history, _LOAD_METRICS), timeline)
    soc_actual = _aligned(_first_series(history, _SOC_METRICS), timeline)
    solar_w = [
        float(value) if value is not None else plan.baseline.points[index].solar_p50_w
        for index, value in enumerate(solar_actual)
    ]
    load_w = [
        float(value) if value is not None else plan.baseline.points[index].load_p50_w
        for index, value in enumerate(load_actual)
    ]
    observed_soc_values = [value for value in soc_actual if value is not None]
    initial_soc = (
        float(observed_soc_values[0])
        if observed_soc_values
        else plan.baseline.points[0].soc_p50_percent
    )
    policy = plan.policy
    capacity = plan.baseline.effective_battery_capacity_wh
    zeros = [0.0] * observed_hours

    actual = _score(
        solar_w=solar_w,
        load_w=load_w,
        extra_load_w=zeros,
        source_w=zeros,
        initial_soc_percent=initial_soc,
        config=config,
        policy=policy,
        effective_capacity_wh=capacity,
        deferred_load_wh=0.0,
        load_interruptions=0,
        actual_soc=soc_actual,
    )
    shadow_loads = _action_hourly_power(plan, "schedule_load", observed_hours)
    shadow_sources = _action_hourly_power(plan, "plan_auxiliary_source", observed_hours)
    interruptions = sum(
        1 for action in plan.actions if action.kind == "schedule_load"
    ) - len(
        {
            action.target for action in plan.actions if action.kind == "schedule_load"
        }
    )
    shadow = _score(
        solar_w=solar_w,
        load_w=load_w,
        extra_load_w=shadow_loads,
        source_w=shadow_sources,
        initial_soc_percent=initial_soc,
        config=config,
        policy=policy,
        effective_capacity_wh=capacity,
        deferred_load_wh=plan.deferred_load_wh,
        load_interruptions=max(0, interruptions),
    )
    hindsight_loads, hindsight_deferred, hindsight_interruptions = _hindsight_loads(
        plan.managed_loads,
        solar_w,
        load_w,
        observed_hours,
    )
    hindsight = _score(
        solar_w=solar_w,
        load_w=load_w,
        extra_load_w=hindsight_loads,
        source_w=zeros,
        initial_soc_percent=initial_soc,
        config=config,
        policy=policy,
        effective_capacity_wh=capacity,
        deferred_load_wh=hindsight_deferred,
        load_interruptions=hindsight_interruptions,
    )

    regret = max(0.0, shadow.total_penalty - hindsight.total_penalty)
    regret_percent = regret / max(1.0, hindsight.total_penalty) * 100
    improvement = (
        (actual.total_penalty - shadow.total_penalty)
        / max(1.0, actual.total_penalty)
        * 100
    )
    feedback = _model_feedback(plan, solar_actual, load_actual, soc_actual)
    observed_pairs = sum(
        1
        for solar, load in zip(solar_actual, load_actual, strict=True)
        if solar is not None and load is not None
    )
    if observed_pairs >= max(12, observed_hours * 0.8) and len(observed_soc_values) >= 4:
        quality = "high"
    elif observed_pairs >= 4:
        quality = "medium"
    else:
        quality = "low"
    notes: list[str] = []
    if any(value is None for value in solar_actual):
        notes.append("Missing solar observations were filled from the original P50 forecast.")
    if any(value is None for value in load_actual):
        notes.append("Missing load observations were filled from the original P50 forecast.")
    notes.append(
        "Observed operation does not reveal whether a manually operated managed load matched "
        "a shadow proposal; counterfactual managed loads are therefore modeled explicitly."
    )
    return CounterfactualEvaluation(
        plan_id=plan.plan_id,
        site_uid=plan.site_uid,
        observed_hours=observed_hours,
        actual=actual,
        shadow=shadow,
        hindsight=hindsight,
        decision_regret=regret,
        regret_percent=regret_percent,
        shadow_improvement_vs_actual_percent=improvement,
        feedback=feedback,
        evidence_quality=quality,
        notes=notes,
    )
