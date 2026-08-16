# src/powersite_autonomy/shadow_feedback.py
from __future__ import annotations

from datetime import UTC, datetime
from statistics import mean, median

from .models import SiteCalibration
from .shadow_models import (
    AutopilotScorecard,
    CounterfactualEvaluation,
    ModelEpoch,
    ModelFeedback,
)


def _bounded_step(multiplier: float, max_fraction: float) -> float:
    requested = multiplier - 1.0
    return max(-max_fraction, min(max_fraction, requested))


def apply_model_feedback(
    calibration: SiteCalibration,
    feedback: ModelFeedback,
    *,
    max_adjustment_fraction: float = 0.05,
    minimum_samples: int = 6,
    minimum_confidence: float = 0.35,
) -> SiteCalibration | None:
    if feedback.sample_count < minimum_samples or feedback.confidence < minimum_confidence:
        return None
    max_step = max(0.001, min(0.10, max_adjustment_fraction))
    pv_step = _bounded_step(feedback.recommended_pv_scale_multiplier, max_step)
    load_step = _bounded_step(feedback.recommended_load_scale_multiplier, max_step)
    if abs(pv_step) < 0.005 and abs(load_step) < 0.005:
        return None

    new_pv_scale = max(0.2, min(2.0, calibration.pv_scale_factor * (1.0 + pv_step)))
    new_load_profile = [
        max(0.0, value * (1.0 + load_step)) for value in calibration.hourly_load_profile_w
    ]
    version_suffix = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    notes = [
        *calibration.notes,
        (
            "Shadow feedback applied bounded calibration correction: "
            f"PV {pv_step:+.2%}, load {load_step:+.2%}."
        ),
    ]
    return calibration.model_copy(
        update={
            "generated_at": datetime.now(UTC),
            "calibration_version": f"{calibration.calibration_version}+shadow-{version_suffix}",
            "pv_scale_factor": new_pv_scale,
            "hourly_load_profile_w": new_load_profile,
            "notes": notes,
        }
    )


def _ratio_delta(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or abs(previous) < 1e-9:
        return None
    return current / previous - 1.0


def detect_change_point(
    site_uid: str,
    previous: SiteCalibration,
    current: SiteCalibration,
) -> ModelEpoch | None:
    signals: dict[str, float] = {}
    reasons: list[str] = []

    pv_delta = _ratio_delta(current.pv_scale_factor, previous.pv_scale_factor)
    if pv_delta is not None and abs(pv_delta) >= 0.25:
        signals["pv_scale_fraction_change"] = pv_delta
        reasons.append("pv_change_point")

    previous_load = mean(previous.hourly_load_profile_w)
    current_load = mean(current.hourly_load_profile_w)
    load_delta = _ratio_delta(current_load, previous_load)
    if load_delta is not None and abs(load_delta) >= 0.30:
        signals["mean_load_fraction_change"] = load_delta
        reasons.append("load_change_point")

    capacity_delta = _ratio_delta(
        current.estimated_usable_battery_capacity_wh,
        previous.estimated_usable_battery_capacity_wh,
    )
    if capacity_delta is not None and abs(capacity_delta) >= 0.30:
        signals["battery_capacity_fraction_change"] = capacity_delta
        reasons.append("battery_capacity_change_point")

    resistance_delta = _ratio_delta(
        current.estimated_internal_resistance_ohm,
        previous.estimated_internal_resistance_ohm,
    )
    if resistance_delta is not None and abs(resistance_delta) >= 0.50:
        signals["battery_impedance_fraction_change"] = resistance_delta
        reasons.append("battery_impedance_change_point")

    if not reasons:
        return None
    reason = reasons[0] if len(reasons) == 1 else "multiple_change_points"
    return ModelEpoch(
        site_uid=site_uid,
        reason=reason,  # type: ignore[arg-type]
        calibration_version=current.calibration_version,
        previous_calibration_version=previous.calibration_version,
        signals=signals,
    )


def build_scorecard(
    site_uid: str,
    evaluations: list[CounterfactualEvaluation],
) -> AutopilotScorecard:
    if not evaluations:
        return AutopilotScorecard(site_uid=site_uid, evaluation_count=0)
    regrets = [item.regret_percent for item in evaluations]
    improvements = [item.shadow_improvement_vs_actual_percent for item in evaluations]
    potential_recovered = sum(
        max(0.0, item.actual.surplus_energy_wh - item.shadow.surplus_energy_wh)
        for item in evaluations
    )
    return AutopilotScorecard(
        site_uid=site_uid,
        evaluation_count=len(evaluations),
        average_decision_regret_percent=mean(regrets),
        median_decision_regret_percent=median(regrets),
        average_shadow_improvement_percent=mean(improvements),
        actual_reserve_breaches=sum(item.actual.reserve_breached for item in evaluations),
        shadow_reserve_breaches=sum(item.shadow.reserve_breached for item in evaluations),
        hindsight_reserve_breaches=sum(item.hindsight.reserve_breached for item in evaluations),
        potential_surplus_recovered_wh=potential_recovered,
        shadow_auxiliary_energy_wh=sum(
            item.shadow.auxiliary_energy_wh for item in evaluations
        ),
        shadow_deferred_load_wh=sum(item.shadow.deferred_load_wh for item in evaluations),
        average_feedback_confidence=mean(item.feedback.confidence for item in evaluations),
    )
