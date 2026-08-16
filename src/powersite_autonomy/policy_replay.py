# src/powersite_autonomy/policy_replay.py
from __future__ import annotations

import math
import statistics
from collections import defaultdict

from .policy_candidates import classify_regime, recommend_dynamic_reserve
from .policy_models import PolicyCandidate, PolicyEvaluation, PolicyReplayRecord
from .shadow_models import (
    CounterfactualEvaluation,
    EnergyPolicy,
    PlanAlternative,
    ShadowAutopilotPlan,
)


def _alternative_score(
    alternative: PlanAlternative,
    policy: EnergyPolicy,
    effective_reserve: float,
) -> float:
    weights = policy.weights
    score = alternative.reserve_breach_probability * weights.reserve_risk * 100.0
    score += alternative.deferred_load_wh / 1000.0 * weights.deferred_load
    score += alternative.auxiliary_energy_wh / 1000.0 * weights.auxiliary_energy
    if policy.maximize_solar_self_consumption:
        score += alternative.expected_surplus_wh / 1000.0 * weights.curtailed_solar
    if policy.minimize_battery_degradation:
        score += (
            alternative.scheduled_load_wh / 1000.0
            * max(0.0, weights.battery_degradation)
            * 0.15
        )
    reserve_gap = max(0.0, effective_reserve - alternative.minimum_soc_p10_percent)
    score += reserve_gap * max(20.0, weights.reserve_risk * 0.35)
    morning_gap = max(0.0, policy.target_morning_soc_percent - alternative.minimum_soc_p50_percent)
    score += morning_gap * max(1.0, weights.reserve_risk * 0.03)
    emergency_gap = max(
        0.0,
        policy.emergency_reserve_percent - alternative.minimum_soc_p10_percent,
    )
    return max(0.0, score + emergency_gap * 10000.0)


def _choose_alternative(
    plan: ShadowAutopilotPlan,
    policy: EnergyPolicy,
    effective_reserve: float,
) -> tuple[PlanAlternative, float]:
    scored = [
        (item, _alternative_score(item, policy, effective_reserve))
        for item in plan.alternatives
    ]
    return min(scored, key=lambda item: (item[1], item[0].name))


def replay_policy(
    candidate: PolicyCandidate,
    plan: ShadowAutopilotPlan,
    evaluation: CounterfactualEvaluation,
    *,
    fallback_policy: EnergyPolicy,
) -> PolicyReplayRecord:
    regime = classify_regime(plan)
    policy = candidate.policy
    if candidate.regime is not None and candidate.regime is not regime:
        policy = fallback_policy
    reserve = recommend_dynamic_reserve(plan.site_uid, plan, policy)
    alternative, point_score = _choose_alternative(
        plan,
        policy,
        reserve.effective_reserve_percent,
    )
    actual = evaluation.actual
    observed_penalty = actual.total_penalty * 0.05
    if actual.reserve_breached:
        observed_penalty += 5000.0 * (
            1.25 if alternative.name == "maximum_utilization" else 1.0
        )
    observed_penalty += (
        actual.unserved_energy_wh / 1000.0 * policy.weights.unserved_critical_load
    )
    recoverable_surplus = min(actual.surplus_energy_wh, alternative.deferred_load_wh)
    observed_penalty += recoverable_surplus / 1000.0 * policy.weights.deferred_load
    predicted_emergency = (
        alternative.minimum_soc_p10_percent < policy.emergency_reserve_percent
    )
    safety_incident = actual.reserve_breached and (
        alternative.name == "maximum_utilization"
        or alternative.minimum_soc_p10_percent < reserve.effective_reserve_percent
    )
    return PolicyReplayRecord(
        plan_id=plan.plan_id,
        generated_at=plan.generated_at,
        regime=regime,
        selected_mode=alternative.name,
        point_in_time_score=point_score,
        observed_penalty=max(0.0, observed_penalty),
        total_score=max(0.0, point_score + observed_penalty),
        predicted_emergency_breach=predicted_emergency,
        actual_reserve_breached=actual.reserve_breached,
        actual_safety_incident=safety_incident,
        actual_unserved_energy_wh=actual.unserved_energy_wh,
        auxiliary_energy_wh=alternative.auxiliary_energy_wh,
        deferred_load_wh=alternative.deferred_load_wh,
        scheduled_load_wh=alternative.scheduled_load_wh,
        battery_throughput_wh=(
            actual.battery_throughput_wh + alternative.scheduled_load_wh * 0.5
        ),
        surplus_energy_wh=actual.surplus_energy_wh,
    )


def _fold_scores(records: list[PolicyReplayRecord]) -> list[float]:
    if not records:
        return []
    ordered = sorted(records, key=lambda item: item.generated_at)
    fold_count = min(5, max(1, len(ordered) // 12))
    if fold_count == 1:
        return [statistics.fmean(item.total_score for item in ordered)]
    size = max(1, math.ceil(len(ordered) / fold_count))
    folds = [ordered[index : index + size] for index in range(0, len(ordered), size)]
    return [statistics.fmean(item.total_score for item in fold) for fold in folds if fold]


def evaluate_policy_candidate(
    candidate: PolicyCandidate,
    plans: list[ShadowAutopilotPlan],
    evaluations: list[CounterfactualEvaluation],
    *,
    fallback_policy: EnergyPolicy,
) -> PolicyEvaluation:
    by_plan = {item.plan_id: item for item in evaluations}
    records = [
        replay_policy(candidate, plan, by_plan[plan.plan_id], fallback_policy=fallback_policy)
        for plan in sorted(plans, key=lambda item: item.generated_at)
        if plan.plan_id in by_plan
    ]
    if not records:
        return PolicyEvaluation(
            site_uid=candidate.site_uid,
            policy_id=candidate.policy_id,
            evaluation_count=0,
        )

    scores = [item.total_score for item in records]
    by_regime: dict[str, list[float]] = defaultdict(list)
    for record in records:
        by_regime[record.regime.value].append(record.total_score)
    return PolicyEvaluation(
        site_uid=candidate.site_uid,
        policy_id=candidate.policy_id,
        evaluation_count=len(records),
        mean_score=statistics.fmean(scores),
        median_score=statistics.median(scores),
        rolling_origin_fold_scores=_fold_scores(records),
        predicted_emergency_breaches=sum(item.predicted_emergency_breach for item in records),
        actual_safety_incidents=sum(item.actual_safety_incident for item in records),
        actual_unserved_energy_wh=sum(item.actual_unserved_energy_wh for item in records),
        auxiliary_energy_wh=sum(item.auxiliary_energy_wh for item in records),
        deferred_load_wh=sum(item.deferred_load_wh for item in records),
        battery_throughput_wh=sum(item.battery_throughput_wh for item in records),
        unused_surplus_wh=sum(
            min(item.surplus_energy_wh, item.deferred_load_wh) for item in records
        ),
        score_by_regime={
            regime: statistics.fmean(values) for regime, values in by_regime.items()
        },
        sample_scores={item.plan_id: item.total_score for item in records},
    )
