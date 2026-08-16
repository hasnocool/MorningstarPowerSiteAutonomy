# src/powersite_autonomy/policy_candidates.py
from __future__ import annotations

import hashlib
import json
from datetime import UTC

from .adaptive_models import BatteryDegradationSnapshot
from .policy_models import (
    DynamicReserveRecommendation,
    PolicyCandidate,
    PolicyObjective,
    PolicyRegime,
    PolicySearchBounds,
    ReserveHorizonTarget,
)
from .shadow_models import EnergyPolicy, PolicyWeights, ShadowAutopilotPlan


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _policy_id(
    policy: EnergyPolicy,
    objective: PolicyObjective,
    regime: PolicyRegime | None,
) -> str:
    payload = {
        "objective": objective.value,
        "regime": regime.value if regime else None,
        "policy": policy.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    return f"policy-{digest}"


def classify_regime(plan: ShadowAutopilotPlan) -> PolicyRegime:
    forecast = plan.baseline
    if forecast.confidence == "low":
        return PolicyRegime.WEATHER_UNCERTAIN
    if forecast.reserve_breach_probability >= 0.55:
        return PolicyRegime.EXTENDED_SCARCITY
    if forecast.minimum_soc_p10_percent < plan.policy.minimum_reserve_percent:
        return PolicyRegime.LOW_SOLAR
    capacity = max(1.0, forecast.effective_battery_capacity_wh)
    if forecast.expected_load_wh / capacity >= 1.25:
        return PolicyRegime.HIGH_LOAD
    if (
        forecast.expected_surplus_wh >= max(250.0, forecast.expected_load_wh * 0.20)
        and forecast.reserve_breach_probability <= 0.08
    ):
        return PolicyRegime.SUNNY_SURPLUS
    month = plan.generated_at.astimezone(UTC).month
    if month in {11, 12, 1, 2} and forecast.reserve_breach_probability >= 0.20:
        return PolicyRegime.EXTENDED_SCARCITY
    return PolicyRegime.NORMAL


def _horizon_targets(
    plan: ShadowAutopilotPlan,
    effective_reserve: float,
) -> list[ReserveHorizonTarget]:
    targets: list[ReserveHorizonTarget] = []
    points = plan.baseline.points
    for horizon in (6, 24, 72, 168):
        actual_horizon = min(horizon, len(points))
        if targets and targets[-1].horizon_hours == actual_horizon:
            break
        subset = points[:actual_horizon]
        if not subset:
            continue
        minimum = min(point.soc_p10_percent for point in subset)
        pressure = clamp((effective_reserve - minimum) / 25.0, 0.0, 1.0)
        target = clamp(effective_reserve + pressure * 8.0, 0.0, 95.0)
        targets.append(
            ReserveHorizonTarget(
                horizon_hours=actual_horizon,
                target_reserve_percent=target,
                minimum_soc_p10_percent=minimum,
                pressure=pressure,
            )
        )
        if len(points) < horizon:
            break
    return targets


def recommend_dynamic_reserve(
    site_uid: str,
    plan: ShadowAutopilotPlan,
    policy: EnergyPolicy,
    *,
    battery: BatteryDegradationSnapshot | None = None,
    recent_change_probability: float = 0.0,
    upper_bound: float = 60.0,
) -> DynamicReserveRecommendation:
    regime = classify_regime(plan)
    forecast = plan.baseline
    adjustments: dict[str, float] = {}
    if forecast.confidence == "low":
        adjustments["weather_uncertainty"] = 6.0
    elif forecast.confidence == "medium":
        adjustments["weather_uncertainty"] = 2.0
    adjustments["reserve_risk"] = min(10.0, forecast.reserve_breach_probability * 14.0)
    regime_adjustments = {
        PolicyRegime.EXTENDED_SCARCITY: ("extended_scarcity", 8.0),
        PolicyRegime.LOW_SOLAR: ("low_solar", 5.0),
        PolicyRegime.HIGH_LOAD: ("high_load", 4.0),
        PolicyRegime.SUNNY_SURPLUS: ("sunny_surplus", -4.0),
    }
    if regime in regime_adjustments:
        name, value = regime_adjustments[regime]
        adjustments[name] = value
    if battery is not None and battery.estimated_health_percent is not None:
        health_gap = max(0.0, 90.0 - battery.estimated_health_percent)
        if health_gap > 0:
            adjustments["battery_health"] = min(6.0, health_gap * 0.20)
    if recent_change_probability >= 0.80:
        adjustments["recent_change"] = min(6.0, recent_change_probability * 6.0)

    lower_bound = max(policy.emergency_reserve_percent + 2.0, 0.0)
    bounded_upper = max(lower_bound, min(95.0, upper_bound))
    effective = clamp(
        policy.minimum_reserve_percent + sum(adjustments.values()),
        lower_bound,
        bounded_upper,
    )
    return DynamicReserveRecommendation(
        site_uid=site_uid,
        regime=regime,
        base_reserve_percent=policy.minimum_reserve_percent,
        effective_reserve_percent=effective,
        lower_bound_percent=lower_bound,
        upper_bound_percent=bounded_upper,
        adjustments=adjustments,
        horizon_targets=_horizon_targets(plan, effective),
    )


def _bounded_policy(
    base: EnergyPolicy,
    bounds: PolicySearchBounds,
    *,
    reserve_delta: float = 0.0,
    morning_delta: float = 0.0,
    reserve_weight_factor: float = 1.0,
    degradation_weight_factor: float = 1.0,
    curtailed_weight_factor: float = 1.0,
    auxiliary_weight_factor: float = 1.0,
    deferred_weight_factor: float = 1.0,
    suffix: str,
) -> EnergyPolicy:
    reserve = clamp(
        base.minimum_reserve_percent + reserve_delta,
        max(bounds.minimum_reserve_min_percent, base.emergency_reserve_percent + 2.0),
        bounds.minimum_reserve_max_percent,
    )
    morning = clamp(
        base.target_morning_soc_percent + morning_delta,
        max(bounds.morning_soc_min_percent, reserve),
        bounds.morning_soc_max_percent,
    )
    weights = base.weights
    updated_weights = PolicyWeights(
        reserve_risk=clamp(
            weights.reserve_risk * reserve_weight_factor,
            bounds.reserve_risk_weight_min,
            bounds.reserve_risk_weight_max,
        ),
        unserved_critical_load=weights.unserved_critical_load,
        battery_degradation=clamp(
            weights.battery_degradation * degradation_weight_factor,
            bounds.battery_degradation_weight_min,
            bounds.battery_degradation_weight_max,
        ),
        curtailed_solar=clamp(
            weights.curtailed_solar * curtailed_weight_factor,
            bounds.curtailed_solar_weight_min,
            bounds.curtailed_solar_weight_max,
        ),
        auxiliary_energy=clamp(
            weights.auxiliary_energy * auxiliary_weight_factor,
            bounds.auxiliary_energy_weight_min,
            bounds.auxiliary_energy_weight_max,
        ),
        deferred_load=clamp(
            weights.deferred_load * deferred_weight_factor,
            bounds.deferred_load_weight_min,
            bounds.deferred_load_weight_max,
        ),
        load_interruptions=weights.load_interruptions,
    )
    return base.model_copy(
        update={
            "policy_version": f"{base.policy_version}+{suffix}",
            "minimum_reserve_percent": reserve,
            "target_morning_soc_percent": morning,
            "weights": updated_weights,
        }
    )


def initial_candidate(site_uid: str, policy: EnergyPolicy) -> PolicyCandidate:
    return PolicyCandidate(
        policy_id=_policy_id(policy, PolicyObjective.BALANCED, None),
        site_uid=site_uid,
        objective=PolicyObjective.BALANCED,
        policy=policy,
        status="champion",
        origin="operator",
    )


def generate_policy_candidates(
    champion: PolicyCandidate,
    bounds: PolicySearchBounds,
    *,
    max_candidates: int = 12,
) -> list[PolicyCandidate]:
    base = champion.policy
    variants = [
        (PolicyObjective.RESILIENCE, None, dict(
            reserve_delta=6.0, morning_delta=6.0, reserve_weight_factor=1.35,
            auxiliary_weight_factor=0.85, suffix="resilience")),
        (PolicyObjective.SOLAR_UTILIZATION, None, dict(
            reserve_delta=-4.0, morning_delta=-2.0, reserve_weight_factor=0.90,
            curtailed_weight_factor=1.80, deferred_weight_factor=1.25, suffix="solar")),
        (PolicyObjective.BATTERY_PRESERVATION, None, dict(
            reserve_delta=3.0, morning_delta=4.0, degradation_weight_factor=1.70,
            suffix="battery")),
        (PolicyObjective.MINIMUM_AUXILIARY, None, dict(
            reserve_delta=2.0, reserve_weight_factor=1.10, auxiliary_weight_factor=1.75,
            deferred_weight_factor=0.85, suffix="min-aux")),
        (PolicyObjective.BALANCED, None, dict(
            reserve_delta=2.0, morning_delta=2.0, reserve_weight_factor=1.15,
            degradation_weight_factor=1.15, suffix="balanced-auto")),
        (PolicyObjective.RESILIENCE, PolicyRegime.WEATHER_UNCERTAIN, dict(
            reserve_delta=8.0, morning_delta=6.0, reserve_weight_factor=1.45,
            suffix="weather-uncertain")),
        (PolicyObjective.RESILIENCE, PolicyRegime.EXTENDED_SCARCITY, dict(
            reserve_delta=10.0, morning_delta=10.0, reserve_weight_factor=1.55,
            auxiliary_weight_factor=0.80, suffix="scarcity")),
        (PolicyObjective.SOLAR_UTILIZATION, PolicyRegime.SUNNY_SURPLUS, dict(
            reserve_delta=-5.0, curtailed_weight_factor=2.20,
            deferred_weight_factor=1.35, suffix="sunny")),
    ]
    candidates = [champion.model_copy(update={"status": "champion"})]
    for objective, regime, changes in variants:
        policy = _bounded_policy(base, bounds, **changes)
        candidate = PolicyCandidate(
            policy_id=_policy_id(policy, objective, regime),
            site_uid=champion.site_uid,
            parent_policy_id=champion.policy_id,
            objective=objective,
            regime=regime,
            policy=policy,
        )
        if candidate.policy_id not in {item.policy_id for item in candidates}:
            candidates.append(candidate)
        if len(candidates) >= max(2, max_candidates):
            break
    return candidates
