# src/powersite_autonomy/policy_analysis.py
from __future__ import annotations

import math
import random
import statistics
from collections import defaultdict

from .adaptive_models import AdaptiveWorldSnapshot
from .policy_candidates import clamp
from .policy_models import (
    AutonomyIntelligenceScore,
    DecisionSensitivitySignal,
    DecisionSensitivitySummary,
    PolicyCandidate,
    PolicyEvaluation,
    PolicyFrontier,
    PolicyLabScorecard,
    PolicyParetoPoint,
    PolicyRegime,
    PolicyTournamentDecision,
    RegretDecomposition,
)
from .shadow_models import CounterfactualEvaluation


def _paired_confidence(
    champion: PolicyEvaluation,
    challenger: PolicyEvaluation,
    *,
    samples: int,
) -> float:
    shared = sorted(champion.sample_scores.keys() & challenger.sample_scores.keys())
    if len(shared) < 2:
        return 0.0
    differences = [
        challenger.sample_scores[plan_id] - champion.sample_scores[plan_id]
        for plan_id in shared
    ]
    rng = random.Random(42)
    draws = max(100, samples)
    better = 0
    for _ in range(draws):
        draw = [differences[rng.randrange(len(differences))] for _ in differences]
        if statistics.fmean(draw) < 0:
            better += 1
    return better / draws


def choose_policy_tournament(
    site_uid: str,
    champion: PolicyCandidate,
    candidates: list[PolicyCandidate],
    evaluations: list[PolicyEvaluation],
    *,
    minimum_replays: int,
    promotion_margin: float,
    bootstrap_samples: int,
) -> PolicyTournamentDecision:
    by_id = {item.policy_id: item for item in evaluations}
    champion_eval = by_id.get(champion.policy_id)
    if champion_eval is None or champion_eval.mean_score is None:
        return PolicyTournamentDecision(
            site_uid=site_uid,
            champion_before=champion.policy_id,
            champion_after=champion.policy_id,
            reason="champion has no mature replay evidence yet",
        )
    ranked = sorted(
        (
            (item, by_id.get(item.policy_id))
            for item in candidates
            if item.policy_id != champion.policy_id
            and item.regime is None
            and by_id.get(item.policy_id) is not None
        ),
        key=lambda pair: (
            pair[1].mean_score if pair[1] and pair[1].mean_score is not None else math.inf
        ),
    )
    if not ranked:
        return PolicyTournamentDecision(
            site_uid=site_uid,
            champion_before=champion.policy_id,
            champion_after=champion.policy_id,
            reason="no global challenger has replay evidence",
        )
    challenger, challenger_eval = ranked[0]
    assert challenger_eval is not None
    if challenger_eval.mean_score is None:
        return PolicyTournamentDecision(
            site_uid=site_uid,
            champion_before=champion.policy_id,
            challenger_id=challenger.policy_id,
            champion_after=champion.policy_id,
            reason="best challenger has no scored replay samples",
        )
    denominator = max(1.0, champion_eval.mean_score)
    improvement = (champion_eval.mean_score - challenger_eval.mean_score) / denominator
    confidence = _paired_confidence(
        champion_eval,
        challenger_eval,
        samples=bootstrap_samples,
    )
    safety_gate = (
        challenger_eval.predicted_emergency_breaches
        <= champion_eval.predicted_emergency_breaches
        and challenger_eval.actual_safety_incidents <= champion_eval.actual_safety_incidents
    )
    enough_history = challenger_eval.evaluation_count >= minimum_replays
    promoted = (
        enough_history
        and safety_gate
        and improvement >= promotion_margin
        and confidence >= 0.95
    )
    if not enough_history:
        reason = "challenger has insufficient mature point-in-time replay history"
    elif not safety_gate:
        reason = "challenger failed the emergency-reserve safety regression gate"
    elif improvement < promotion_margin:
        reason = "challenger improvement is below the configured promotion margin"
    elif confidence < 0.95:
        reason = "paired bootstrap confidence is below 95%"
    else:
        reason = (
            f"challenger improved paired replay score by {improvement:.3f} "
            f"with confidence {confidence:.3f} and no safety regression"
        )
    return PolicyTournamentDecision(
        site_uid=site_uid,
        champion_before=champion.policy_id,
        challenger_id=challenger.policy_id,
        champion_after=challenger.policy_id if promoted else champion.policy_id,
        promoted=promoted,
        improvement_fraction=improvement,
        paired_confidence=confidence,
        safety_gate_passed=safety_gate,
        reason=reason,
    )


def build_policy_frontier(
    site_uid: str,
    candidates: list[PolicyCandidate],
    evaluations: list[PolicyEvaluation],
) -> PolicyFrontier:
    by_candidate = {item.policy_id: item for item in candidates}
    usable = [
        item
        for item in evaluations
        if item.mean_score is not None and item.policy_id in by_candidate
    ]

    def dominates(left: PolicyEvaluation, right: PolicyEvaluation) -> bool:
        left_values = (
            left.mean_score or math.inf,
            left.predicted_emergency_breaches,
            left.actual_safety_incidents,
            left.auxiliary_energy_wh,
            left.deferred_load_wh,
            left.battery_throughput_wh,
        )
        right_values = (
            right.mean_score or math.inf,
            right.predicted_emergency_breaches,
            right.actual_safety_incidents,
            right.auxiliary_energy_wh,
            right.deferred_load_wh,
            right.battery_throughput_wh,
        )
        weak = all(a <= b for a, b in zip(left_values, right_values, strict=True))
        strict = any(a < b for a, b in zip(left_values, right_values, strict=True))
        return weak and strict

    frontier = [
        item
        for item in usable
        if not any(dominates(other, item) for other in usable if other is not item)
    ]
    points = [
        PolicyParetoPoint(
            policy_id=item.policy_id,
            objective=by_candidate[item.policy_id].objective,
            regime=by_candidate[item.policy_id].regime,
            mean_score=item.mean_score or 0.0,
            predicted_emergency_breaches=item.predicted_emergency_breaches,
            actual_safety_incidents=item.actual_safety_incidents,
            auxiliary_energy_wh=item.auxiliary_energy_wh,
            deferred_load_wh=item.deferred_load_wh,
            battery_throughput_wh=item.battery_throughput_wh,
        )
        for item in sorted(frontier, key=lambda value: value.mean_score or math.inf)
    ]
    return PolicyFrontier(site_uid=site_uid, points=points)


def best_regime_candidates(
    candidates: list[PolicyCandidate],
    evaluations: list[PolicyEvaluation],
) -> dict[str, str]:
    by_eval = {item.policy_id: item for item in evaluations}
    result: dict[str, str] = {}
    for regime in PolicyRegime:
        matching = [
            item
            for item in candidates
            if item.regime is regime
            and item.policy_id in by_eval
            and by_eval[item.policy_id].mean_score is not None
        ]
        if matching:
            result[regime.value] = min(
                matching,
                key=lambda item: by_eval[item.policy_id].score_by_regime.get(
                    regime.value,
                    math.inf,
                ),
            ).policy_id
    return result


def decompose_regret(
    site_uid: str,
    evaluations: list[CounterfactualEvaluation],
) -> RegretDecomposition:
    buckets = {
        "weather_model": 0.0,
        "pv_model": 0.0,
        "load_model": 0.0,
        "battery_model": 0.0,
        "policy_selection": 0.0,
        "optimizer_approximation": 0.0,
        "irreducible_uncertainty": 0.0,
    }
    total = 0.0
    for evaluation in evaluations:
        regret = max(0.0, evaluation.decision_regret)
        total += regret
        attribution = evaluation.feedback.primary_attribution
        if attribution == "weather_or_pv_model":
            buckets["weather_model"] += regret * 0.55
            buckets["pv_model"] += regret * 0.45
        elif attribution == "load_model":
            buckets["load_model"] += regret
        elif attribution == "battery_model":
            buckets["battery_model"] += regret
        elif attribution == "optimizer_or_policy":
            buckets["policy_selection"] += regret * 0.70
            buckets["optimizer_approximation"] += regret * 0.30
        elif attribution == "mixed":
            buckets["weather_model"] += regret * 0.20
            buckets["pv_model"] += regret * 0.15
            buckets["load_model"] += regret * 0.20
            buckets["battery_model"] += regret * 0.15
            buckets["policy_selection"] += regret * 0.20
            buckets["optimizer_approximation"] += regret * 0.10
        else:
            buckets["irreducible_uncertainty"] += regret
    return RegretDecomposition(
        site_uid=site_uid,
        evaluation_count=len(evaluations),
        total_regret=total,
        **buckets,
    )


def build_decision_sensitivity(
    site_uid: str,
    evaluations: list[CounterfactualEvaluation],
) -> DecisionSensitivitySummary:
    buckets: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for evaluation in evaluations:
        feedback = evaluation.feedback
        regret = max(0.0, evaluation.regret_percent)
        if feedback.solar_mae_w is not None:
            buckets["weather_pv"].append(
                (min(3.0, feedback.solar_mae_w / 500.0), regret)
            )
        if feedback.load_mae_w is not None:
            buckets["load"].append((min(3.0, feedback.load_mae_w / 500.0), regret))
        if feedback.soc_mae_percent is not None:
            buckets["battery"].append(
                (min(3.0, feedback.soc_mae_percent / 20.0), regret)
            )
        if feedback.primary_attribution in {"optimizer_or_policy", "mixed"}:
            buckets["policy_optimizer"].append((min(3.0, regret / 50.0), regret))

    signals = []
    for source, values in buckets.items():
        mean_error = statistics.fmean(item[0] for item in values)
        mean_regret = statistics.fmean(item[1] for item in values)
        signals.append(
            DecisionSensitivitySignal(
                source=source,
                sample_count=len(values),
                mean_normalized_error=mean_error,
                mean_regret_percent=mean_regret,
                priority_score=mean_error * (1.0 + mean_regret / 100.0),
            )
        )
    signals.sort(key=lambda item: item.priority_score, reverse=True)
    return DecisionSensitivitySummary(site_uid=site_uid, signals=signals)


def build_intelligence_score(
    site_uid: str,
    adaptive: AdaptiveWorldSnapshot | None,
    champion: PolicyEvaluation | None,
    shadow_evaluations: list[CounterfactualEvaluation],
) -> AutonomyIntelligenceScore:
    feedback_confidence = [item.feedback.confidence for item in shadow_evaluations]
    forecast_accuracy = (
        45.0 + 55.0 * statistics.fmean(feedback_confidence)
        if feedback_confidence
        else 45.0
    )
    regrets = [item.regret_percent for item in shadow_evaluations]
    decision_quality = (
        clamp(100.0 - statistics.fmean(regrets), 0.0, 100.0)
        if regrets
        else 50.0
    )
    uncertainty = 50.0
    world = 50.0
    battery = 40.0
    stability = 70.0
    if adaptive is not None:
        if adaptive.uncertainty is not None:
            closeness = [
                clamp(
                    100.0
                    - abs(item.empirical_coverage - item.nominal_coverage) * 250.0,
                    0.0,
                    100.0,
                )
                for item in adaptive.uncertainty.metrics
                if item.empirical_coverage is not None
            ]
            if closeness:
                uncertainty = statistics.fmean(closeness)
        if adaptive.weather_skill is not None and adaptive.weather_skill.skills:
            world = clamp(
                statistics.fmean(item.skill_score for item in adaptive.weather_skill.skills)
                * 100.0,
                0.0,
                100.0,
            )
        if adaptive.battery is not None:
            battery = clamp(adaptive.battery.sample_count / 48.0 * 100.0, 0.0, 100.0)
        if adaptive.change_points:
            stability = clamp(
                100.0 - max(item.probability for item in adaptive.change_points) * 100.0,
                0.0,
                100.0,
            )
    policy_quality = 50.0
    if champion is not None and champion.mean_score is not None:
        policy_quality = clamp(
            100.0 / (1.0 + champion.mean_score / 5000.0),
            0.0,
            100.0,
        )
    components = {
        "forecast_accuracy": forecast_accuracy,
        "uncertainty_calibration": uncertainty,
        "world_model_confidence": world,
        "decision_quality": decision_quality,
        "policy_quality": policy_quality,
        "battery_model_confidence": battery,
        "change_stability": stability,
    }
    return AutonomyIntelligenceScore(
        site_uid=site_uid,
        overall=statistics.fmean(components.values()),
        biggest_opportunity=min(components, key=components.get),
        **components,
    )


def build_policy_scorecard(
    site_uid: str,
    champion: PolicyCandidate,
    evaluations: list[PolicyEvaluation],
    tournament: PolicyTournamentDecision,
    frontier: PolicyFrontier,
    promotion_count: int,
    regime_champions: dict[str, str],
) -> PolicyLabScorecard:
    replay_count = max((item.evaluation_count for item in evaluations), default=0)
    return PolicyLabScorecard(
        site_uid=site_uid,
        champion_policy_id=champion.policy_id,
        replay_count=replay_count,
        candidates_evaluated=sum(item.evaluation_count > 0 for item in evaluations),
        promotions=promotion_count,
        pareto_policies=len(frontier.points),
        regime_champions=regime_champions,
        latest_improvement_fraction=tournament.improvement_fraction,
        latest_paired_confidence=tournament.paired_confidence,
    )
