# src/powersite_autonomy/shadow_planning.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .forecast import ForecastInputs, build_forecast
from .models import AdditionalLoad, AdditionalSource, AuxiliaryPlanRequest, FlexibleLoadRequest
from .planning import plan_auxiliary_energy, schedule_flexible_load
from .shadow_models import (
    EnergyPolicy,
    ManagedLoad,
    PlanAlternative,
    ShadowAction,
    ShadowAutopilotPlan,
)

_MODE_ORDER = ("conservative", "balanced", "maximum_utilization")
_PRIORITY_ORDER = {
    "critical": 0,
    "essential": 1,
    "normal": 2,
    "flexible": 3,
    "deferrable": 4,
    "surplus_only": 5,
}


@dataclass(slots=True)
class _CandidatePlan:
    mode: str
    planned: object
    actions: list[ShadowAction]
    scheduled_load_wh: float
    deferred_load_wh: float
    auxiliary_energy_wh: float
    objective_score: float
    interruptions: int


def _with_policy_reserve(inputs: ForecastInputs, policy: EnergyPolicy) -> ForecastInputs:
    return ForecastInputs(
        site_uid=inputs.site_uid,
        config=inputs.config.model_copy(
            update={"reserve_percent": policy.minimum_reserve_percent}
        ),
        state=inputs.state,
        weather=inputs.weather,
        calibration=inputs.calibration,
        sentinel_feedback=inputs.sentinel_feedback,
        additional_loads=inputs.additional_loads,
        additional_sources=inputs.additional_sources,
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


def _confidence_value(value: str) -> float:
    return {"high": 0.92, "medium": 0.72, "low": 0.45}.get(value, 0.45)


def _mode_risk_limit(mode: str, policy: EnergyPolicy) -> float:
    target = policy.target_reserve_breach_probability
    if mode == "conservative":
        return min(0.02, target)
    if mode == "maximum_utilization":
        return min(0.30, max(0.15, target * 4))
    return target


def _mode_soc_floor(mode: str, policy: EnergyPolicy) -> float:
    if mode == "conservative":
        return policy.minimum_reserve_percent
    if mode == "maximum_utilization":
        return policy.emergency_reserve_percent
    return (policy.minimum_reserve_percent + policy.emergency_reserve_percent) / 2


def _base_constraints(policy: EnergyPolicy) -> list[str]:
    return [
        "Shadow-only action; PowerSiteAutonomy must not emit a hardware command.",
        "Discard the proposal if telemetry, policy, or forecast evidence becomes stale.",
        (
            "Replan before any operator decision if the predicted SOC falls below the "
            f"{policy.emergency_reserve_percent:.1f}% emergency reserve."
        ),
    ]


def _action_expiry(now: datetime) -> datetime:
    return now + timedelta(minutes=30)


def _schedule_request(load: ManagedLoad, horizon: int) -> FlexibleLoadRequest | None:
    deadline = min(load.deadline_hour, horizon)
    if load.earliest_start_hour >= deadline:
        return None
    available_wh = load.power_w * (deadline - load.earliest_start_hour)
    energy_wh = min(load.energy_required_wh, available_wh)
    if energy_wh <= 0:
        return None
    return FlexibleLoadRequest(
        horizon_hours=horizon,
        energy_required_wh=energy_wh,
        max_power_w=load.power_w,
        earliest_start_hour=load.earliest_start_hour,
        deadline_hour=deadline,
        priority=load.priority,
        interruptible=load.interruptible,
    )


def _accept_schedule(mode: str, load: ManagedLoad, result, policy: EnergyPolicy) -> bool:
    if load.priority.value in {"critical", "essential"}:
        return True
    if result.minimum_soc_p50_percent < policy.emergency_reserve_percent:
        return False
    if result.scheduled_risk > _mode_risk_limit(mode, policy):
        return False
    if mode == "conservative" and result.minimum_soc_p50_percent < policy.minimum_reserve_percent:
        return False
    if mode == "balanced" and result.minimum_soc_p50_percent < _mode_soc_floor(mode, policy):
        return False
    if load.priority.value == "surplus_only" and result.recommendation == "defer":
        return False
    return True


def _build_load_actions(
    *,
    now: datetime,
    load: ManagedLoad,
    result,
    policy: EnergyPolicy,
    forecast_model_version: str,
    calibration_version: str | None,
    model_epoch_id: str | None,
) -> list[ShadowAction]:
    actions: list[ShadowAction] = []
    confidence = 0.78 if result.recommendation == "schedule" else 0.62
    for segment in result.segments:
        actions.append(
            ShadowAction(
                created_at=now,
                expires_at=_action_expiry(now),
                kind="schedule_load",
                target=load.load_id,
                operation="shadow_schedule",
                planned_power_w=segment.power_w,
                planned_energy_wh=segment.energy_wh,
                start_hour=segment.start_hour,
                duration_hours=segment.duration_hours,
                window_start_hour=load.earliest_start_hour,
                window_end_hour=load.deadline_hour,
                expected_risk_delta=result.scheduled_risk - result.baseline_risk,
                expected_min_soc_delta_percent=0.0,
                confidence=confidence,
                reason=(
                    "This interval ranked as a lower-risk window for the managed load under "
                    "the current shadow policy."
                ),
                evidence_codes=["forecast_surplus", "reserve_risk", "managed_load_window"],
                preconditions=["Fresh forecast inputs remain available before the interval."],
                safety_constraints=_base_constraints(policy),
                policy_version=policy.policy_version,
                forecast_model_version=forecast_model_version,
                calibration_version=calibration_version,
                model_epoch_id=model_epoch_id,
            )
        )
    return actions


def _defer_action(
    *,
    now: datetime,
    load: ManagedLoad,
    policy: EnergyPolicy,
    baseline,
    model_epoch_id: str | None,
) -> ShadowAction:
    return ShadowAction(
        created_at=now,
        expires_at=_action_expiry(now),
        kind="defer_load",
        target=load.load_id,
        operation="shadow_defer",
        planned_energy_wh=load.energy_required_wh,
        window_start_hour=load.earliest_start_hour,
        window_end_hour=load.deadline_hour,
        confidence=_confidence_value(baseline.confidence),
        reason=(
            "No candidate schedule satisfied the selected policy's reserve-risk and SOC "
            "constraints."
        ),
        evidence_codes=["reserve_risk", "managed_load_window"],
        preconditions=["Reconsider automatically when the next receding-horizon plan runs."],
        safety_constraints=_base_constraints(policy),
        policy_version=policy.policy_version,
        forecast_model_version=baseline.model_version,
        calibration_version=baseline.calibration_version,
        model_epoch_id=model_epoch_id,
    )


def _site_level_actions(
    *,
    now: datetime,
    baseline,
    planned,
    policy: EnergyPolicy,
    model_epoch_id: str | None,
) -> list[ShadowAction]:
    actions: list[ShadowAction] = []
    confidence = _confidence_value(planned.confidence)
    common = {
        "created_at": now,
        "expires_at": _action_expiry(now),
        "policy_version": policy.policy_version,
        "forecast_model_version": planned.model_version,
        "calibration_version": planned.calibration_version,
        "model_epoch_id": model_epoch_id,
        "safety_constraints": _base_constraints(policy),
    }
    if planned.confidence == "low":
        actions.append(
            ShadowAction(
                **common,
                kind="improve_observability",
                target="site",
                operation="shadow_observability_warning",
                confidence=confidence,
                reason="Forecast evidence is weak enough to reduce confidence in policy decisions.",
                evidence_codes=["low_forecast_confidence"],
            )
        )
    if planned.reserve_breach_probability > policy.target_reserve_breach_probability:
        actions.append(
            ShadowAction(
                **common,
                kind="preserve_reserve",
                target="site",
                operation="shadow_preserve_reserve",
                expected_risk_delta=(
                    planned.reserve_breach_probability - baseline.reserve_breach_probability
                ),
                confidence=confidence,
                reason=(
                    "Planned reserve-breach probability remains above the policy target; "
                    "discretionary demand should remain deferred in shadow policy."
                ),
                evidence_codes=["reserve_risk_above_target"],
            )
        )
    best_index = None
    best_surplus = 0.0
    for index, point in enumerate(planned.points):
        if point.surplus_p10_w > best_surplus:
            best_surplus = point.surplus_p10_w
            best_index = index
    if policy.maximize_solar_self_consumption and best_index is not None and best_surplus >= 25:
        actions.append(
            ShadowAction(
                **common,
                kind="use_surplus",
                target="flexible_load_pool",
                operation="shadow_surplus_window",
                planned_power_w=best_surplus,
                planned_energy_wh=best_surplus,
                start_hour=best_index,
                duration_hours=1,
                confidence=confidence,
                reason="The P10 forecast still shows conservative surplus in this interval.",
                evidence_codes=["p10_surplus"],
            )
        )
    return actions


def _objective_score(
    forecast,
    *,
    policy: EnergyPolicy,
    deferred_load_wh: float,
    auxiliary_energy_wh: float,
    interruptions: int,
) -> float:
    weights = policy.weights
    reserve_penalty = forecast.reserve_breach_probability * weights.reserve_risk * 100
    unserved_penalty = forecast.unmet_load_probability * weights.unserved_critical_load * 100
    deferred_penalty = deferred_load_wh / 1000 * weights.deferred_load
    auxiliary_penalty = auxiliary_energy_wh / 1000 * weights.auxiliary_energy
    interruption_penalty = interruptions * weights.load_interruptions
    curtailed_penalty = 0.0
    if policy.maximize_solar_self_consumption:
        curtailed_penalty = forecast.expected_surplus_wh / 1000 * weights.curtailed_solar
    degradation_penalty = 0.0
    if policy.minimize_battery_degradation:
        cycle_proxy = forecast.expected_load_wh / max(1.0, forecast.effective_battery_capacity_wh)
        degradation_penalty = cycle_proxy * weights.battery_degradation

    emergency_gap = max(0.0, policy.emergency_reserve_percent - forecast.minimum_soc_p10_percent)
    hard_penalty = emergency_gap * 10000
    return (
        reserve_penalty
        + unserved_penalty
        + deferred_penalty
        + auxiliary_penalty
        + interruption_penalty
        + curtailed_penalty
        + degradation_penalty
        + hard_penalty
    )


def _build_candidate(
    inputs: ForecastInputs,
    managed_loads: list[ManagedLoad],
    policy: EnergyPolicy,
    *,
    mode: str,
    samples: int,
    model_epoch_id: str | None,
) -> _CandidatePlan:
    now = datetime.now(UTC)
    current = inputs
    baseline = build_forecast(current, samples=samples, seed=404)
    actions: list[ShadowAction] = []
    scheduled_load_wh = 0.0
    deferred_load_wh = 0.0
    interruptions = 0
    horizon = len(inputs.weather)

    loads = sorted(
        (item for item in managed_loads if item.enabled),
        key=lambda item: (_PRIORITY_ORDER[item.priority.value], item.deadline_hour, item.load_id),
    )
    for load in loads:
        request = _schedule_request(load, horizon)
        if request is None:
            deferred_load_wh += load.energy_required_wh
            actions.append(
                _defer_action(
                    now=now,
                    load=load,
                    policy=policy,
                    baseline=baseline,
                    model_epoch_id=model_epoch_id,
                )
            )
            continue
        result = schedule_flexible_load(current, request, samples=samples)
        if not _accept_schedule(mode, load, result, policy):
            deferred_load_wh += request.energy_required_wh
            actions.append(
                _defer_action(
                    now=now,
                    load=load,
                    policy=policy,
                    baseline=baseline,
                    model_epoch_id=model_epoch_id,
                )
            )
            continue
        additional = tuple(
            AdditionalLoad(
                power_w=segment.power_w,
                start_hour=segment.start_hour,
                duration_hours=segment.duration_hours,
            )
            for segment in result.segments
        )
        current = _with_loads(current, additional)
        scheduled_load_wh += result.scheduled_energy_wh
        interruptions += max(0, len(result.segments) - 1)
        actions.extend(
            _build_load_actions(
                now=now,
                load=load,
                result=result,
                policy=policy,
                forecast_model_version=baseline.model_version,
                calibration_version=baseline.calibration_version,
                model_epoch_id=model_epoch_id,
            )
        )

    pre_aux = build_forecast(current, samples=samples, seed=404)
    auxiliary_energy_wh = 0.0
    if (
        pre_aux.reserve_breach_probability > policy.target_reserve_breach_probability
        and policy.auxiliary_source_power_w is not None
        and policy.auxiliary_max_energy_wh > 0
    ):
        auxiliary_request = AuxiliaryPlanRequest(
            horizon_hours=horizon,
            target_reserve_breach_probability=policy.target_reserve_breach_probability,
            source_power_w=policy.auxiliary_source_power_w,
            max_energy_wh=policy.auxiliary_max_energy_wh,
            earliest_start_hour=0,
            latest_end_hour=horizon,
        )
        auxiliary = plan_auxiliary_energy(current, auxiliary_request, samples=samples)
        if auxiliary.feasible and auxiliary.start_hour is not None and auxiliary.duration_hours > 0:
            source = AdditionalSource(
                power_w=auxiliary.source_power_w,
                start_hour=auxiliary.start_hour,
                duration_hours=auxiliary.duration_hours,
            )
            current = _with_sources(current, (source,))
            auxiliary_energy_wh = auxiliary.required_energy_wh
            actions.append(
                ShadowAction(
                    created_at=now,
                    expires_at=_action_expiry(now),
                    kind="plan_auxiliary_source",
                    target="auxiliary_source",
                    operation="shadow_auxiliary_energy",
                    planned_power_w=auxiliary.source_power_w,
                    planned_energy_wh=auxiliary.required_energy_wh,
                    start_hour=auxiliary.start_hour,
                    duration_hours=auxiliary.duration_hours,
                    expected_risk_delta=auxiliary.planned_risk - auxiliary.baseline_risk,
                    confidence=_confidence_value(pre_aux.confidence),
                    reason=(
                        "The read-only auxiliary planner found an energy window that reduces "
                        "reserve risk toward the policy target."
                    ),
                    evidence_codes=["reserve_risk", "auxiliary_energy_simulation"],
                    safety_constraints=_base_constraints(policy),
                    policy_version=policy.policy_version,
                    forecast_model_version=pre_aux.model_version,
                    calibration_version=pre_aux.calibration_version,
                    model_epoch_id=model_epoch_id,
                )
            )

    planned = build_forecast(current, samples=samples, seed=404)
    actions.extend(
        _site_level_actions(
            now=now,
            baseline=baseline,
            planned=planned,
            policy=policy,
            model_epoch_id=model_epoch_id,
        )
    )
    objective = _objective_score(
        planned,
        policy=policy,
        deferred_load_wh=deferred_load_wh,
        auxiliary_energy_wh=auxiliary_energy_wh,
        interruptions=interruptions,
    )
    return _CandidatePlan(
        mode=mode,
        planned=planned,
        actions=actions,
        scheduled_load_wh=scheduled_load_wh,
        deferred_load_wh=deferred_load_wh,
        auxiliary_energy_wh=auxiliary_energy_wh,
        objective_score=objective,
        interruptions=interruptions,
    )


def build_shadow_plan(
    inputs: ForecastInputs,
    policy: EnergyPolicy,
    managed_loads: list[ManagedLoad],
    *,
    samples: int,
    model_epoch_id: str | None = None,
) -> ShadowAutopilotPlan:
    policy_inputs = _with_policy_reserve(inputs, policy)
    baseline = build_forecast(policy_inputs, samples=samples, seed=404)
    candidates = [
        _build_candidate(
            policy_inputs,
            managed_loads,
            policy,
            mode=mode,
            samples=samples,
            model_epoch_id=model_epoch_id,
        )
        for mode in _MODE_ORDER
    ]
    candidates.sort(key=lambda item: (item.objective_score, _MODE_ORDER.index(item.mode)))
    selected = candidates[0]
    alternatives = [
        PlanAlternative(
            name=candidate.mode,
            objective_score=candidate.objective_score,
            reserve_breach_probability=candidate.planned.reserve_breach_probability,
            minimum_soc_p10_percent=candidate.planned.minimum_soc_p10_percent,
            minimum_soc_p50_percent=candidate.planned.minimum_soc_p50_percent,
            expected_surplus_wh=candidate.planned.expected_surplus_wh,
            scheduled_load_wh=candidate.scheduled_load_wh,
            deferred_load_wh=candidate.deferred_load_wh,
            auxiliary_energy_wh=candidate.auxiliary_energy_wh,
            action_count=len(candidate.actions),
        )
        for candidate in sorted(candidates, key=lambda item: _MODE_ORDER.index(item.mode))
    ]
    return ShadowAutopilotPlan(
        site_uid=inputs.site_uid,
        horizon_hours=len(inputs.weather),
        policy=policy,
        baseline=baseline,
        planned=selected.planned,
        objective_score=selected.objective_score,
        selected_mode=selected.mode,
        alternatives=alternatives,
        managed_loads=[item for item in managed_loads if item.enabled],
        actions=selected.actions,
        scheduled_load_wh=selected.scheduled_load_wh,
        deferred_load_wh=selected.deferred_load_wh,
        auxiliary_energy_wh=selected.auxiliary_energy_wh,
        model_epoch_id=model_epoch_id,
    )
