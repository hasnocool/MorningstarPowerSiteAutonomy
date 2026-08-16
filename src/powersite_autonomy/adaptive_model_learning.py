# src/powersite_autonomy/adaptive_model_learning.py
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .adaptive_models import (
    AdaptiveModelCandidate,
    BatteryDegradationSnapshot,
    ChangePointSignal,
    ModelPromotionDecision,
    SeasonalCalibrationOverlay,
    UncertaintyCalibration,
    UncertaintyMetricCalibration,
)
from .calibration import derive_power_series
from .evidence import TwinCandidate, run_tournament
from .models import ForecastScoreSummary, HistoryPoint, SiteCalibration, SiteConfig, WeatherHour
from .pv import estimate_site_pv_power_w


def hour_key(timestamp: datetime) -> datetime:
    value = timestamp.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


def local_datetime(timestamp: datetime, utc_offset_hours: float) -> datetime:
    return timestamp.astimezone(UTC) + timedelta(hours=utc_offset_hours)


def series_map(points: list[HistoryPoint]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for point in points:
        buckets[hour_key(point.timestamp)].append(point.value)
    return {key: statistics.fmean(values) for key, values in buckets.items()}


def build_battery_degradation_snapshot(
    *,
    site_uid: str,
    config: SiteConfig,
    history: dict[str, list[HistoryPoint]],
    calibrations: list[SiteCalibration],
) -> BatteryDegradationSnapshot:
    power_points = derive_power_series(
        history,
        ("battery_net_power_w",),
        "battery_net_current_a",
        "battery_voltage_v",
    )
    throughput = sum(abs(point.value) for point in power_points)
    equivalent_cycles = throughput / max(1.0, 2.0 * config.battery_capacity_wh)
    latest = calibrations[0] if calibrations else None

    def trend(field: str) -> float | None:
        usable = [item for item in calibrations if getattr(item, field) is not None]
        if len(usable) < 2:
            return None
        newest, oldest = usable[0], usable[-1]
        new_value = float(getattr(newest, field))
        old_value = float(getattr(oldest, field))
        elapsed_days = max(1.0, (newest.generated_at - oldest.generated_at).total_seconds() / 86400)
        if abs(old_value) < 1e-9:
            return None
        return (new_value / old_value - 1.0) * (30.0 / elapsed_days) * 100.0

    capacity = latest.estimated_usable_battery_capacity_wh if latest is not None else None
    resistance = latest.estimated_internal_resistance_ohm if latest is not None else None
    health = None if capacity is None else 100.0 * capacity / config.battery_capacity_wh
    return BatteryDegradationSnapshot(
        site_uid=site_uid,
        chemistry=str(config.battery_chemistry),
        configured_capacity_wh=config.battery_capacity_wh,
        estimated_usable_capacity_wh=capacity,
        estimated_health_percent=None if health is None else max(0.0, min(150.0, health)),
        estimated_internal_resistance_ohm=resistance,
        throughput_wh=throughput,
        equivalent_full_cycles=equivalent_cycles,
        capacity_change_percent_30d=trend("estimated_usable_battery_capacity_wh"),
        resistance_change_percent_30d=trend("estimated_internal_resistance_ohm"),
        sample_count=len(power_points),
    )


def build_uncertainty_calibration(
    site_uid: str,
    score: ForecastScoreSummary,
    *,
    nominal_coverage: float = 0.80,
    minimum_samples: int = 20,
) -> UncertaintyCalibration:
    mapping = {
        "solar_power_w": "solar",
        "load_power_w": "load",
        "battery_soc_percent": "soc",
    }
    metrics: list[UncertaintyMetricCalibration] = []
    for item in score.metrics:
        if item.horizon_hours is not None or item.metric not in mapping:
            continue
        scale = 1.0
        coverage = item.p10_p90_coverage
        if item.sample_count >= minimum_samples and coverage is not None and coverage > 0:
            scale = math.sqrt(nominal_coverage / coverage)
            scale = max(0.65, min(2.25, scale))
        metrics.append(
            UncertaintyMetricCalibration(
                metric=mapping[item.metric],  # type: ignore[arg-type]
                sample_count=item.sample_count,
                nominal_coverage=nominal_coverage,
                empirical_coverage=coverage,
                scale_multiplier=scale,
            )
        )
    return UncertaintyCalibration(site_uid=site_uid, metrics=metrics)


def _probability_from_shift(fractional_shift: float, expected_noise: float) -> tuple[float, float]:
    z_score = fractional_shift / max(0.01, expected_noise)
    probability = 1.0 - math.exp(-0.5 * z_score * z_score)
    return max(0.0, min(0.999, probability)), z_score


def detect_probabilistic_change_points(
    *,
    site_uid: str,
    previous_overlay: SeasonalCalibrationOverlay | None,
    current_overlay: SeasonalCalibrationOverlay,
    previous_battery: BatteryDegradationSnapshot | None,
    current_battery: BatteryDegradationSnapshot,
) -> list[ChangePointSignal]:
    signals: list[ChangePointSignal] = []

    def direction(value: float) -> str:
        if value > 0.02:
            return "increase"
        if value < -0.02:
            return "decrease"
        return "stable"

    if previous_overlay is not None:
        previous_pv = [cell.pv_residual_scale for cell in previous_overlay.cells]
        current_pv = [cell.pv_residual_scale for cell in current_overlay.cells]
        if previous_pv and current_pv:
            old = statistics.median(previous_pv)
            new = statistics.median(current_pv)
            shift = new / max(0.01, old) - 1.0
            probability, z_score = _probability_from_shift(shift, 0.08)
            signals.append(
                ChangePointSignal(
                    site_uid=site_uid,
                    parameter="pv",
                    probability=probability,
                    standardized_shift=z_score,
                    fractional_shift=shift,
                    direction=direction(shift),  # type: ignore[arg-type]
                    model_epoch_recommended=probability >= 0.95,
                )
            )
        previous_load = [cell.load_mean_w for cell in previous_overlay.cells if cell.load_mean_w]
        current_load = [cell.load_mean_w for cell in current_overlay.cells if cell.load_mean_w]
        if previous_load and current_load:
            old = statistics.median(previous_load)
            new = statistics.median(current_load)
            shift = new / max(1.0, old) - 1.0
            probability, z_score = _probability_from_shift(shift, 0.12)
            signals.append(
                ChangePointSignal(
                    site_uid=site_uid,
                    parameter="load",
                    probability=probability,
                    standardized_shift=z_score,
                    fractional_shift=shift,
                    direction=direction(shift),  # type: ignore[arg-type]
                    model_epoch_recommended=probability >= 0.95,
                )
            )

    if previous_battery is not None:
        pairs = [
            (
                "battery_capacity",
                previous_battery.estimated_usable_capacity_wh,
                current_battery.estimated_usable_capacity_wh,
                0.08,
            ),
            (
                "battery_resistance",
                previous_battery.estimated_internal_resistance_ohm,
                current_battery.estimated_internal_resistance_ohm,
                0.15,
            ),
        ]
        for parameter, old, new, noise in pairs:
            if old is None or new is None or abs(old) < 1e-9:
                continue
            shift = new / old - 1.0
            probability, z_score = _probability_from_shift(shift, noise)
            signals.append(
                ChangePointSignal(
                    site_uid=site_uid,
                    parameter=parameter,  # type: ignore[arg-type]
                    probability=probability,
                    standardized_shift=z_score,
                    fractional_shift=shift,
                    direction=direction(shift),  # type: ignore[arg-type]
                    model_epoch_recommended=probability >= 0.95,
                )
            )
    return signals


def evaluate_world_model_candidates(
    *,
    config: SiteConfig,
    calibration: SiteCalibration | None,
    overlay: SeasonalCalibrationOverlay,
    history: dict[str, list[HistoryPoint]],
    weather_history: list[WeatherHour],
    current_champion: str,
) -> list[AdaptiveModelCandidate]:
    solar = series_map(history.get("solar_input_power_w", []))
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    load = series_map(load_points)
    weather = {hour_key(item.timestamp): item for item in weather_history}
    baseline_errors: list[float] = []
    adaptive_errors: list[float] = []
    observed_scale: list[float] = []

    for timestamp in sorted(solar.keys() & weather.keys()):
        conditions = weather[timestamp]
        if conditions.shortwave_radiation_w_m2 < 80:
            continue
        actual = max(0.0, solar[timestamp])
        baseline = estimate_site_pv_power_w(conditions, config, calibration)
        local = local_datetime(timestamp, config.utc_offset_hours)
        cell = overlay.cell(local.month, local.hour)
        adaptive = baseline * (cell.pv_residual_scale if cell is not None else 1.0)
        baseline_errors.append(abs(baseline - actual))
        adaptive_errors.append(abs(adaptive - actual))
        observed_scale.append(actual)

    for timestamp, actual in load.items():
        local = local_datetime(timestamp, config.utc_offset_hours)
        if calibration is None:
            baseline = config.load_watts_fallback
        else:
            baseline = calibration.hourly_load_profile_w[local.hour]
            baseline *= calibration.weekday_load_multiplier[local.weekday()]
        cell = overlay.cell(local.month, local.hour)
        adaptive = (
            cell.load_mean_w
            if cell is not None and cell.load_mean_w is not None
            else baseline
        )
        baseline_errors.append(abs(baseline - actual))
        adaptive_errors.append(abs(adaptive - actual))
        observed_scale.append(max(1.0, actual))

    sample_count = len(baseline_errors)
    scale = max(50.0, statistics.fmean(observed_scale)) if observed_scale else 100.0
    baseline_error = (
        statistics.fmean(baseline_errors) / scale if baseline_errors else 1.0
    )
    adaptive_error = (
        statistics.fmean(adaptive_errors) / scale if adaptive_errors else 1.0
    )
    return [
        AdaptiveModelCandidate(
            candidate_id="baseline-v2",
            model_kind="world_model",
            model_version="forecast-v2",
            prediction_error=max(0.0, baseline_error),
            evaluation_count=sample_count,
            status="champion" if current_champion == "baseline-v2" else "challenger",
        ),
        AdaptiveModelCandidate(
            candidate_id="adaptive-seasonal-v1",
            model_kind="world_model",
            model_version=overlay.model_version,
            prediction_error=max(0.0, adaptive_error),
            evaluation_count=sample_count,
            status=(
                "champion" if current_champion == "adaptive-seasonal-v1" else "challenger"
            ),
            metadata={"seasonal_cells": len(overlay.cells)},
        ),
    ]


def decide_model_promotion(
    *,
    site_uid: str,
    candidates: list[AdaptiveModelCandidate],
    current_champion: str,
    promotion_margin: float = 0.08,
    minimum_samples: int = 48,
) -> ModelPromotionDecision:
    twins = [
        TwinCandidate(
            twin_id=item.candidate_id,
            prior_weight=item.prior_weight,
            prediction_error=item.prediction_error,
            evaluation_count=item.evaluation_count,
            is_champion=item.candidate_id == current_champion,
        )
        for item in candidates
    ]
    result = run_tournament(
        twins,
        promotion_margin=promotion_margin,
        min_evaluations=minimum_samples,
    )
    if result is None:
        return ModelPromotionDecision(
            site_uid=site_uid,
            champion_before=current_champion,
            champion_after=current_champion,
            promoted=False,
            promotion_reason="no model candidates were available",
        )
    return ModelPromotionDecision(
        site_uid=site_uid,
        champion_before=current_champion,
        champion_after=result.champion_id,
        promoted=result.promoted,
        promotion_reason=result.promotion_reason,
        posterior_weights={item.twin_id: item.posterior_weight for item in result.scores},
    )
