# src/powersite_autonomy/adaptive_models.py
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

from .models import WeatherHour


class HorizonBucket(StrEnum):
    SHORT = "0-12h"
    MEDIUM = "12-36h"
    LONG = "36-72h"
    EXTENDED = "72h+"


class WeatherForecastRun(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    group_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    model: str
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    points: list[WeatherHour]
    evaluated: bool = False


class WeatherRunScore(BaseModel):
    score_id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    site_uid: str
    model: str
    horizon_bucket: HorizonBucket
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sample_count: int = Field(ge=0)
    pv_mae_w: float | None = Field(default=None, ge=0)
    pv_bias_w: float | None = None
    normalized_error: float | None = Field(default=None, ge=0)


class WeatherModelSkill(BaseModel):
    model: str
    horizon_bucket: HorizonBucket
    sample_count: int = Field(ge=0)
    pv_mae_w: float | None = Field(default=None, ge=0)
    pv_bias_w: float | None = None
    skill_score: float = Field(default=0.0, ge=0, le=1)
    weight: float = Field(default=0.0, ge=0, le=1)


class WeatherSkillSummary(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    skills: list[WeatherModelSkill] = Field(default_factory=list)
    weights_by_horizon: dict[str, dict[str, float]] = Field(default_factory=dict)


class SeasonalCell(BaseModel):
    month: int = Field(ge=1, le=12)
    local_hour: int = Field(ge=0, le=23)
    sample_count: int = Field(ge=0)
    pv_residual_scale: float = Field(default=1.0, ge=0.4, le=1.8)
    load_mean_w: float | None = Field(default=None, ge=0)
    load_sigma_w: float | None = Field(default=None, ge=0)


class SeasonalCalibrationOverlay(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_version: str = "seasonal-overlay-v1"
    history_days: int = Field(ge=1)
    minimum_samples_per_cell: int = Field(default=4, ge=1)
    cells: list[SeasonalCell] = Field(default_factory=list)
    active: bool = False

    def cell(self, month: int, local_hour: int) -> SeasonalCell | None:
        for item in self.cells:
            if item.month == month and item.local_hour == local_hour:
                return item
        return None


class LoadEventCluster(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    delta_power_w: float = Field(ge=0)
    duration_hours_p50: float = Field(gt=0)
    local_start_hour_p50: int = Field(ge=0, le=23)
    occurrence_probability: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=1)
    confidence: float = Field(ge=0, le=1)


class ManagedLoadCompletionEvidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    plan_id: str
    load_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    planned_energy_wh: float = Field(ge=0)
    matched_incremental_energy_wh: float = Field(ge=0)
    completion_ratio_estimate: float = Field(ge=0, le=1.5)
    observed_hours: int = Field(ge=0)
    expected_hours: int = Field(ge=0)
    confidence: float = Field(ge=0, le=1)
    evidence_only: bool = True
    note: str = (
        "Read-only telemetry match only; this does not prove the shadow action was executed."
    )


class BatteryDegradationSnapshot(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    chemistry: str
    configured_capacity_wh: float = Field(gt=0)
    estimated_usable_capacity_wh: float | None = Field(default=None, gt=0)
    estimated_health_percent: float | None = Field(default=None, ge=0, le=150)
    estimated_internal_resistance_ohm: float | None = Field(default=None, ge=0)
    throughput_wh: float = Field(default=0.0, ge=0)
    equivalent_full_cycles: float = Field(default=0.0, ge=0)
    capacity_change_percent_30d: float | None = None
    resistance_change_percent_30d: float | None = None
    sample_count: int = Field(default=0, ge=0)


class UncertaintyMetricCalibration(BaseModel):
    metric: Literal["solar", "load", "soc"]
    sample_count: int = Field(ge=0)
    nominal_coverage: float = Field(default=0.80, gt=0, lt=1)
    empirical_coverage: float | None = Field(default=None, ge=0, le=1)
    scale_multiplier: float = Field(default=1.0, ge=0.5, le=3.0)


class UncertaintyCalibration(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metrics: list[UncertaintyMetricCalibration] = Field(default_factory=list)

    def scale_for(self, metric: str) -> float:
        return next(
            (item.scale_multiplier for item in self.metrics if item.metric == metric),
            1.0,
        )


class ChangePointSignal(BaseModel):
    signal_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    parameter: Literal["pv", "load", "battery_capacity", "battery_resistance"]
    probability: float = Field(ge=0, le=1)
    standardized_shift: float
    fractional_shift: float | None = None
    direction: Literal["increase", "decrease", "stable"]
    model_epoch_recommended: bool = False


class AdaptiveModelCandidate(BaseModel):
    candidate_id: str
    model_kind: Literal["world_model", "weather_ensemble", "uncertainty"]
    model_version: str
    prediction_error: float = Field(ge=0)
    evaluation_count: int = Field(ge=0)
    prior_weight: float = Field(default=1.0, gt=0)
    status: Literal["champion", "challenger", "rejected"] = "challenger"
    metadata: dict[str, float | str | bool] = Field(default_factory=dict)


class ModelPromotionDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    champion_before: str
    champion_after: str
    promoted: bool
    promotion_reason: str
    posterior_weights: dict[str, float] = Field(default_factory=dict)


class AdaptiveForecastContext(BaseModel):
    weather_weights_by_horizon: dict[str, dict[str, float]] = Field(default_factory=dict)
    seasonal_overlay: SeasonalCalibrationOverlay | None = None
    solar_uncertainty_scale: float = Field(default=1.0, ge=0.5, le=3.0)
    load_uncertainty_scale: float = Field(default=1.0, ge=0.5, le=3.0)
    soc_uncertainty_scale: float = Field(default=1.0, ge=0.5, le=3.0)


class AdaptiveWorldSnapshot(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    weather_skill: WeatherSkillSummary | None = None
    seasonal_overlay: SeasonalCalibrationOverlay | None = None
    load_events: list[LoadEventCluster] = Field(default_factory=list)
    managed_load_evidence: list[ManagedLoadCompletionEvidence] = Field(default_factory=list)
    battery: BatteryDegradationSnapshot | None = None
    uncertainty: UncertaintyCalibration | None = None
    change_points: list[ChangePointSignal] = Field(default_factory=list)
    promotion: ModelPromotionDecision | None = None
    champion_model: str = "baseline-v2"
    read_only: bool = True


class AdaptiveScorecard(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    retained_weather_runs: int = Field(ge=0)
    evaluated_weather_runs: int = Field(ge=0)
    weather_models_ranked: int = Field(ge=0)
    seasonal_cells: int = Field(ge=0)
    discovered_load_events: int = Field(ge=0)
    managed_load_evidence_count: int = Field(ge=0)
    uncertainty_metrics_calibrated: int = Field(ge=0)
    change_points_detected: int = Field(ge=0)
    model_promotions: int = Field(ge=0)
    champion_model: str
    battery_health_percent: float | None = None
