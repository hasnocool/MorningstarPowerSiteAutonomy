# src/powersite_autonomy/planning.py
from __future__ import annotations

import math
from datetime import UTC, datetime

from .forecast import ForecastInputs, build_forecast
from .models import (
    ActionPlan,
    ActionPlanAction,
    AdditionalLoad,
    AdditionalSource,
    AuxiliaryPlanRequest,
    AuxiliaryPlanResult,
    FlexibleLoadRequest,
    FlexibleLoadScheduleResult,
    LoadPriority,
    OptimizationCandidate,
    OptimizationRequest,
    OptimizationResult,
    PVArrayConfig,
    ScheduledLoadSegment,
)


def _with_loads(inputs: ForecastInputs, loads: tuple[AdditionalLoad, ...]) -> ForecastInputs:
    return ForecastInputs(
        site_uid=inputs.site_uid,
        config=inputs.config,
        state=inputs.state,
        weather=inputs.weather,
        calibration=inputs.calibration,
        sentinel_feedback=inputs.sentinel_feedback,
        additional_loads=(*inputs.additional_loads, *loads),
        additional_sources=inputs.additional_sources,
    )


def _with_sources(inputs: ForecastInputs, sources: tuple[AdditionalSource, ...]) -> ForecastInputs:
    return ForecastInputs(
        site_uid=inputs.site_uid,
        config=inputs.config,
        state=inputs.state,
        weather=inputs.weather,
        calibration=inputs.calibration,
        sentinel_feedback=inputs.sentinel_feedback,
        additional_loads=inputs.additional_loads,
        additional_sources=(*inputs.additional_sources, *sources),
    )


def schedule_flexible_load(
    inputs: ForecastInputs,
    request: FlexibleLoadRequest,
    *,
    samples: int,
) -> FlexibleLoadScheduleResult:
    baseline = build_forecast(inputs, samples=samples, seed=101)
    eligible_hours = list(range(request.earliest_start_hour, request.deadline_hour))

    if request.interruptible:
        ranked = sorted(
            eligible_hours,
            key=lambda index: (
                baseline.points[index].surplus_p10_w,
                baseline.points[index].soc_p10_percent,
            ),
            reverse=True,
        )
        remaining = request.energy_required_wh
        segments: list[ScheduledLoadSegment] = []
        for index in ranked:
            if remaining <= 1e-6:
                break
            power_w = min(request.max_power_w, remaining)
            segments.append(
                ScheduledLoadSegment(
                    start_hour=index,
                    duration_hours=1,
                    power_w=power_w,
                    energy_wh=power_w,
                )
            )
            remaining -= power_w
        segments.sort(key=lambda segment: segment.start_hour)
        loads = tuple(
            AdditionalLoad(
                power_w=segment.power_w,
                start_hour=segment.start_hour,
                duration_hours=1,
            )
            for segment in segments
        )
        scheduled = build_forecast(_with_loads(inputs, loads), samples=samples, seed=101)
        candidate_count = len(eligible_hours)
    else:
        duration = math.ceil(request.energy_required_wh / request.max_power_w)
        power_w = request.energy_required_wh / duration
        latest_start = request.deadline_hour - duration
        candidates: list[tuple[float, float, int, object]] = []
        for start in range(request.earliest_start_hour, latest_start + 1):
            load = AdditionalLoad(power_w=power_w, start_hour=start, duration_hours=duration)
            result = build_forecast(
                _with_loads(inputs, (load,)),
                samples=samples,
                seed=101,
            )
            candidates.append(
                (
                    result.reserve_breach_probability,
                    -result.minimum_soc_p50_percent,
                    start,
                    result,
                )
            )
        candidates.sort(key=lambda item: (item[0], item[1], item[2]))
        _, _, best_start, scheduled_obj = candidates[0]
        scheduled = scheduled_obj  # type: ignore[assignment]
        segments = [
            ScheduledLoadSegment(
                start_hour=best_start,
                duration_hours=duration,
                power_w=power_w,
                energy_wh=request.energy_required_wh,
            )
        ]
        candidate_count = len(candidates)

    risk = scheduled.reserve_breach_probability
    if request.priority == LoadPriority.SURPLUS_ONLY:
        recommendation = (
            "surplus_only"
            if risk <= baseline.reserve_breach_probability + 0.02
            else "defer"
        )
    elif request.priority in {LoadPriority.CRITICAL, LoadPriority.ESSENTIAL}:
        recommendation = "schedule"
    elif risk >= 0.60 or risk - baseline.reserve_breach_probability >= 0.25:
        recommendation = "defer"
    else:
        recommendation = "schedule"

    return FlexibleLoadScheduleResult(
        site_uid=inputs.site_uid,
        generated_at=datetime.now(UTC),
        priority=request.priority,
        interruptible=request.interruptible,
        segments=segments,
        scheduled_energy_wh=sum(segment.energy_wh for segment in segments),
        baseline_risk=baseline.reserve_breach_probability,
        scheduled_risk=scheduled.reserve_breach_probability,
        minimum_soc_p50_percent=scheduled.minimum_soc_p50_percent,
        candidate_count=candidate_count,
        recommendation=recommendation,  # type: ignore[arg-type]
    )


def scaled_site_config(config, array_watts: float, battery_wh: float):
    if config.pv_arrays:
        current_total = sum(array.rated_watts for array in config.pv_arrays)
        factor = array_watts / max(1.0, current_total)
        arrays = [
            PVArrayConfig.model_validate(
                {
                    **array.model_dump(),
                    "rated_watts": max(1.0, array.rated_watts * factor),
                }
            )
            for array in config.pv_arrays
        ]
    else:
        arrays = []
    return config.model_copy(
        update={
            "array_watts": array_watts,
            "battery_capacity_wh": battery_wh,
            "pv_arrays": arrays,
        }
    )


def _grid_values(start: float, end: float, step: float) -> list[float]:
    values: list[float] = []
    current = start
    while current <= end + step * 0.001:
        values.append(round(current, 6))
        current += step
    if not values or values[-1] < end - step * 0.001:
        values.append(end)
    return values


def optimize_site(
    inputs: ForecastInputs,
    request: OptimizationRequest,
    *,
    samples: int,
) -> OptimizationResult:
    baseline_forecast = build_forecast(inputs, samples=samples, seed=202)
    current_array = sum(array.rated_watts for array in inputs.config.resolved_pv_arrays())
    current_battery = inputs.config.battery_capacity_wh
    array_min = request.array_watts_min or max(request.array_watts_step, current_array * 0.5)
    array_max = request.array_watts_max or current_array * 2.0
    battery_min = request.battery_capacity_wh_min or max(
        request.battery_capacity_wh_step,
        current_battery * 0.5,
    )
    battery_max = request.battery_capacity_wh_max or current_battery * 2.0

    baseline = OptimizationCandidate(
        array_watts=current_array,
        battery_capacity_wh=current_battery,
        reserve_breach_probability=baseline_forecast.reserve_breach_probability,
        minimum_soc_p50_percent=baseline_forecast.minimum_soc_p50_percent,
        safe_discretionary_energy_wh=baseline_forecast.safe_discretionary_energy_wh,
        incremental_cost=(
            0.0
            if request.pv_cost_per_w is not None
            or request.battery_cost_per_wh is not None
            else None
        ),
        meets_target=(
            baseline_forecast.reserve_breach_probability
            <= request.target_reserve_breach_probability
        ),
    )

    array_values = _grid_values(array_min, array_max, request.array_watts_step)
    battery_values = _grid_values(battery_min, battery_max, request.battery_capacity_wh_step)
    evaluated = 0
    candidates: list[OptimizationCandidate] = []
    sim_samples = max(40, min(samples, 160))
    for array_watts in array_values:
        for battery_wh in battery_values:
            if evaluated >= request.max_candidates:
                break
            evaluated += 1
            config = scaled_site_config(inputs.config, array_watts, battery_wh)
            candidate_inputs = ForecastInputs(
                site_uid=inputs.site_uid,
                config=config,
                state=inputs.state,
                weather=inputs.weather,
                calibration=inputs.calibration,
                sentinel_feedback=inputs.sentinel_feedback,
            )
            forecast = build_forecast(candidate_inputs, samples=sim_samples, seed=202)
            incremental_cost = None
            if request.pv_cost_per_w is not None or request.battery_cost_per_wh is not None:
                incremental_cost = (
                    max(0.0, array_watts - current_array) * (request.pv_cost_per_w or 0.0)
                    + max(0.0, battery_wh - current_battery)
                    * (request.battery_cost_per_wh or 0.0)
                )
            candidates.append(
                OptimizationCandidate(
                    array_watts=array_watts,
                    battery_capacity_wh=battery_wh,
                    reserve_breach_probability=forecast.reserve_breach_probability,
                    minimum_soc_p50_percent=forecast.minimum_soc_p50_percent,
                    safe_discretionary_energy_wh=forecast.safe_discretionary_energy_wh,
                    incremental_cost=incremental_cost,
                    meets_target=(
                        forecast.reserve_breach_probability
                        <= request.target_reserve_breach_probability
                    ),
                )
            )
        if evaluated >= request.max_candidates:
            break

    def hardware_delta(candidate: OptimizationCandidate) -> float:
        return max(0.0, candidate.array_watts - current_array) / max(1.0, current_array) + max(
            0.0,
            candidate.battery_capacity_wh - current_battery,
        ) / max(1.0, current_battery)

    candidates.sort(
        key=lambda candidate: (
            not candidate.meets_target,
            candidate.incremental_cost
            if candidate.incremental_cost is not None
            else hardware_delta(candidate),
            candidate.reserve_breach_probability,
            -candidate.minimum_soc_p50_percent,
        )
    )

    # Keep a compact Pareto-like frontier: progressively lower risk for
    # progressively more hardware or cost.
    frontier: list[OptimizationCandidate] = []
    best_risk = 2.0
    for candidate in candidates:
        if candidate.reserve_breach_probability <= best_risk + 1e-9:
            frontier.append(candidate)
            best_risk = candidate.reserve_breach_probability
        if len(frontier) >= 12:
            break
    if not frontier:
        frontier = candidates[:12]

    return OptimizationResult(
        site_uid=inputs.site_uid,
        generated_at=datetime.now(UTC),
        baseline=baseline,
        target_reserve_breach_probability=request.target_reserve_breach_probability,
        evaluated_candidates=evaluated,
        candidates=frontier,
    )


def _auxiliary_source_for_energy(
    baseline,
    request: AuxiliaryPlanRequest,
    energy_wh: float,
) -> AdditionalSource | None:
    if energy_wh <= 0:
        return None
    duration = max(1, math.ceil(energy_wh / request.source_power_w))
    if duration > request.latest_end_hour - request.earliest_start_hour:
        return None
    power_w = energy_wh / duration

    breach_index = request.latest_end_hour
    if baseline.first_reserve_breach_at is not None:
        for index, point in enumerate(baseline.points):
            if point.timestamp >= baseline.first_reserve_breach_at:
                breach_index = index
                break
    latest_start = request.latest_end_hour - duration
    start = max(request.earliest_start_hour, min(latest_start, breach_index - duration))
    return AdditionalSource(power_w=power_w, start_hour=start, duration_hours=duration)


def plan_auxiliary_energy(
    inputs: ForecastInputs,
    request: AuxiliaryPlanRequest,
    *,
    samples: int,
) -> AuxiliaryPlanResult:
    baseline = build_forecast(inputs, samples=samples, seed=303)
    if baseline.reserve_breach_probability <= request.target_reserve_breach_probability:
        return AuxiliaryPlanResult(
            site_uid=inputs.site_uid,
            generated_at=datetime.now(UTC),
            required_energy_wh=0.0,
            source_power_w=request.source_power_w,
            start_hour=None,
            duration_hours=0,
            baseline_risk=baseline.reserve_breach_probability,
            planned_risk=baseline.reserve_breach_probability,
            target_risk=request.target_reserve_breach_probability,
            feasible=True,
        )

    max_source = _auxiliary_source_for_energy(baseline, request, request.max_energy_wh)
    if max_source is None:
        return AuxiliaryPlanResult(
            site_uid=inputs.site_uid,
            generated_at=datetime.now(UTC),
            required_energy_wh=request.max_energy_wh,
            source_power_w=request.source_power_w,
            start_hour=None,
            duration_hours=0,
            baseline_risk=baseline.reserve_breach_probability,
            planned_risk=baseline.reserve_breach_probability,
            target_risk=request.target_reserve_breach_probability,
            feasible=False,
        )
    max_result = build_forecast(
        _with_sources(inputs, (max_source,)),
        samples=samples,
        seed=303,
    )
    if max_result.reserve_breach_probability > request.target_reserve_breach_probability:
        return AuxiliaryPlanResult(
            site_uid=inputs.site_uid,
            generated_at=datetime.now(UTC),
            required_energy_wh=request.max_energy_wh,
            source_power_w=max_source.power_w,
            start_hour=max_source.start_hour,
            duration_hours=max_source.duration_hours,
            baseline_risk=baseline.reserve_breach_probability,
            planned_risk=max_result.reserve_breach_probability,
            target_risk=request.target_reserve_breach_probability,
            feasible=False,
        )

    low = 0.0
    high = request.max_energy_wh
    best_source = max_source
    best_result = max_result
    for _ in range(12):
        mid = (low + high) / 2
        source = _auxiliary_source_for_energy(baseline, request, mid)
        if source is None:
            low = mid
            continue
        result = build_forecast(_with_sources(inputs, (source,)), samples=samples, seed=303)
        if result.reserve_breach_probability <= request.target_reserve_breach_probability:
            high = mid
            best_source = source
            best_result = result
        else:
            low = mid

    required_energy = best_source.power_w * best_source.duration_hours
    return AuxiliaryPlanResult(
        site_uid=inputs.site_uid,
        generated_at=datetime.now(UTC),
        required_energy_wh=required_energy,
        source_power_w=best_source.power_w,
        start_hour=best_source.start_hour,
        duration_hours=best_source.duration_hours,
        baseline_risk=baseline.reserve_breach_probability,
        planned_risk=best_result.reserve_breach_probability,
        target_risk=request.target_reserve_breach_probability,
        feasible=True,
    )


def build_action_plan(forecast) -> ActionPlan:
    actions: list[ActionPlanAction] = []
    risk = forecast.reserve_breach_probability
    if forecast.confidence == "low":
        actions.append(
            ActionPlanAction(
                kind="improve_observability",
                priority="high",
                reason=(
                    "Forecast confidence is low; improve or restore measurement evidence "
                    "before relying on optimization outputs."
                ),
            )
        )
    if risk >= 0.60:
        actions.extend(
            [
                ActionPlanAction(
                    kind="preserve_reserve",
                    priority="high",
                    reason=(
                        f"Reserve-breach probability is {risk:.0%}; preserve stored energy "
                        "for essential loads."
                    ),
                ),
                ActionPlanAction(
                    kind="defer_flexible_loads",
                    priority="high",
                    reason=(
                        "High reserve risk makes discretionary load deferral the safest "
                        "planning recommendation."
                    ),
                ),
                ActionPlanAction(
                    kind="plan_auxiliary_source",
                    priority="medium",
                    reason=(
                        "Evaluate the read-only auxiliary-energy planner to quantify how much "
                        "external energy would reduce reserve risk."
                    ),
                ),
            ]
        )
    elif risk >= 0.20:
        actions.append(
            ActionPlanAction(
                kind="defer_flexible_loads",
                priority="medium",
                reason=(
                    f"Reserve-breach probability is elevated at {risk:.0%}; schedule flexible "
                    "loads into conservative surplus windows."
                ),
            )
        )
    elif forecast.safe_discretionary_energy_wh > 0:
        actions.append(
            ActionPlanAction(
                kind="use_surplus",
                priority="low",
                reason=(
                    "The conservative forecast leaves about "
                    f"{forecast.safe_discretionary_energy_wh:.0f} Wh above reserve for "
                    "discretionary work."
                ),
            )
        )

    return ActionPlan(
        site_uid=forecast.site_uid,
        generated_at=datetime.now(UTC),
        forecast_model_version=forecast.model_version,
        reserve_breach_probability=risk,
        actions=actions,
    )
