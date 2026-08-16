# src/powersite_autonomy/models.py
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class BatteryChemistry(StrEnum):
    LEAD_ACID = "lead_acid"
    AGM = "agm"
    GEL = "gel"
    LIFEPO4 = "lifepo4"
    OTHER = "other"


class LoadPriority(StrEnum):
    CRITICAL = "critical"
    ESSENTIAL = "essential"
    NORMAL = "normal"
    FLEXIBLE = "flexible"
    DEFERRABLE = "deferrable"
    SURPLUS_ONLY = "surplus_only"


class PVArrayConfig(BaseModel):
    name: str = "array"
    rated_watts: float = Field(gt=0)
    tilt_deg: float = Field(default=0.0, ge=0, le=90)
    azimuth_deg: float = Field(default=0.0, ge=-180, le=180)
    performance_ratio: float = Field(default=0.90, gt=0, le=1.2)
    wiring_loss_fraction: float = Field(default=0.02, ge=0, le=0.30)
    controller_efficiency: float = Field(default=0.97, gt=0, le=1)
    controller_max_power_w: float | None = Field(default=None, gt=0)
    temperature_coefficient_per_c: float = Field(default=-0.004, ge=-0.02, le=0)
    noct_c: float = Field(default=45.0, ge=20, le=80)
    ground_albedo: float = Field(default=0.20, ge=0, le=1)
    shading_by_hour: list[float] = Field(default_factory=lambda: [1.0] * 24)

    @model_validator(mode="after")
    def validate_shading_profile(self) -> PVArrayConfig:
        if len(self.shading_by_hour) != 24:
            raise ValueError("shading_by_hour must contain exactly 24 hourly factors")
        if any(value < 0 or value > 1 for value in self.shading_by_hour):
            raise ValueError("shading_by_hour values must be between 0 and 1")
        return self


class SiteConfig(BaseModel):
    array_watts: float = Field(gt=0)
    battery_capacity_wh: float = Field(gt=0)
    reserve_percent: float = Field(default=25.0, ge=0, le=95)
    initial_soc_fallback_percent: float = Field(default=50.0, ge=0, le=100)
    load_watts_fallback: float = Field(default=100.0, ge=0)
    performance_ratio: float = Field(default=0.78, gt=0, le=1.2)
    charge_efficiency: float = Field(default=0.95, gt=0, le=1)
    discharge_efficiency: float = Field(default=0.95, gt=0, le=1)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    utc_offset_hours: float = Field(default=0.0, ge=-12, le=14)
    battery_chemistry: BatteryChemistry = BatteryChemistry.OTHER
    battery_usable_capacity_percent: float = Field(default=100.0, gt=0, le=100)
    battery_health_percent: float = Field(default=100.0, gt=0, le=120)
    battery_temperature_c_fallback: float | None = None
    max_charge_power_w: float | None = Field(default=None, gt=0)
    max_discharge_power_w: float | None = Field(default=None, gt=0)
    pv_arrays: list[PVArrayConfig] = Field(default_factory=list)

    def resolved_pv_arrays(self) -> list[PVArrayConfig]:
        if self.pv_arrays:
            return self.pv_arrays
        return [
            PVArrayConfig(
                name="legacy-array",
                rated_watts=self.array_watts,
                performance_ratio=self.performance_ratio,
            )
        ]


class WeatherHour(BaseModel):
    timestamp: datetime
    shortwave_radiation_w_m2: float = Field(ge=0)
    cloud_cover_percent: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = None
    shortwave_radiation_spread_w_m2: float | None = Field(default=None, ge=0)


class HistoryPoint(BaseModel):
    timestamp: datetime
    value: float
    quality: str | None = None


class RecurringLoadSignature(BaseModel):
    signature_id: str
    local_hour: int = Field(ge=0, le=23)
    incremental_power_w: float = Field(ge=0)
    occurrence_probability: float = Field(ge=0, le=1)
    sample_count: int = Field(ge=0)


class SiteCalibration(BaseModel):
    site_uid: str
    generated_at: datetime
    calibration_version: str = "site-calibration-v1"
    history_days: int = Field(ge=1)
    hourly_load_profile_w: list[float] = Field(min_length=24, max_length=24)
    hourly_load_sigma_w: list[float] = Field(min_length=24, max_length=24)
    weekday_load_multiplier: list[float] = Field(min_length=7, max_length=7)
    pv_scale_factor: float = Field(default=1.0, ge=0.2, le=2.0)
    pv_scale_by_hour: list[float] = Field(default_factory=lambda: [1.0] * 24)
    estimated_usable_battery_capacity_wh: float | None = Field(default=None, gt=0)
    estimated_internal_resistance_ohm: float | None = Field(default=None, ge=0)
    recurring_load_signatures: list[RecurringLoadSignature] = Field(default_factory=list)
    sample_counts: dict[str, int] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_hourly_scaling(self) -> SiteCalibration:
        if len(self.pv_scale_by_hour) != 24:
            raise ValueError("pv_scale_by_hour must contain exactly 24 values")
        return self


class SentinelFeedback(BaseModel):
    reachable: bool = True
    telemetry_reliable: bool = True
    soc_reliable: bool = True
    forecast_uncertainty_multiplier: float = Field(default=1.0, ge=1.0, le=4.0)
    pv_derate_factor: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence_codes: list[str] = Field(default_factory=list)


class BatteryTwinSnapshot(BaseModel):
    chemistry: BatteryChemistry
    nominal_capacity_wh: float
    effective_capacity_wh: float
    configured_usable_capacity_percent: float
    estimated_health_percent: float
    temperature_c: float | None
    temperature_capacity_factor: float
    max_charge_power_w: float | None
    max_discharge_power_w: float | None
    estimated_internal_resistance_ohm: float | None
    soc_percent: float
    soc_confidence: Literal["low", "medium", "high"]


class ForecastPoint(BaseModel):
    timestamp: datetime
    solar_p10_w: float
    solar_p50_w: float
    solar_p90_w: float
    load_p10_w: float
    load_p50_w: float
    load_p90_w: float
    surplus_p10_w: float
    surplus_p50_w: float
    surplus_p90_w: float
    soc_p10_percent: float
    soc_p50_percent: float
    soc_p90_percent: float


class ForecastSummary(BaseModel):
    site_uid: str
    generated_at: datetime
    horizon_hours: int
    model_version: str = "forecast-v2"
    calibration_version: str | None = None
    minimum_soc_p10_percent: float
    minimum_soc_p50_percent: float
    minimum_soc_p90_percent: float
    reserve_breach_probability: float = Field(ge=0, le=1)
    unmet_load_probability: float = Field(default=0.0, ge=0, le=1)
    first_reserve_breach_at: datetime | None
    expected_solar_wh: float
    expected_load_wh: float
    expected_surplus_wh: float
    discretionary_energy_wh: float
    safe_discretionary_energy_wh: float
    autonomy_hours_if_no_solar: float | None
    effective_battery_capacity_wh: float
    confidence: Literal["low", "medium", "high"]
    input_quality: dict[str, str]
    points: list[ForecastPoint]


class AdditionalLoad(BaseModel):
    power_w: float = Field(gt=0)
    start_hour: int = Field(default=0, ge=0)
    duration_hours: int = Field(gt=0, le=168)


class AdditionalSource(BaseModel):
    power_w: float = Field(gt=0)
    start_hour: int = Field(default=0, ge=0)
    duration_hours: int = Field(gt=0, le=168)


class ScenarioRequest(BaseModel):
    horizon_hours: int = Field(default=72, ge=1, le=168)
    additional_loads: list[AdditionalLoad] = Field(default_factory=list)
    additional_sources: list[AdditionalSource] = Field(default_factory=list)
    array_watts: float | None = Field(default=None, gt=0)
    battery_capacity_wh: float | None = Field(default=None, gt=0)
    reserve_percent: float | None = Field(default=None, ge=0, le=95)

    @model_validator(mode="after")
    def validate_windows(self) -> ScenarioRequest:
        for item in [*self.additional_loads, *self.additional_sources]:
            if item.start_hour + item.duration_hours > self.horizon_hours:
                raise ValueError("scenario window extends past scenario horizon")
        return self


class ScenarioResult(BaseModel):
    site_uid: str
    generated_at: datetime
    baseline: ForecastSummary
    scenario: ForecastSummary
    additional_energy_wh: float
    additional_source_energy_wh: float
    risk_delta: float
    recommendation: Literal["low_risk", "elevated_risk", "high_risk"]


class FlexibleLoadRequest(BaseModel):
    horizon_hours: int = Field(default=72, ge=1, le=168)
    energy_required_wh: float = Field(gt=0)
    max_power_w: float = Field(gt=0)
    earliest_start_hour: int = Field(default=0, ge=0)
    deadline_hour: int = Field(ge=1, le=168)
    priority: LoadPriority = LoadPriority.FLEXIBLE
    interruptible: bool = False

    @model_validator(mode="after")
    def validate_window(self) -> FlexibleLoadRequest:
        if self.deadline_hour > self.horizon_hours:
            raise ValueError("deadline_hour cannot exceed horizon_hours")
        if self.earliest_start_hour >= self.deadline_hour:
            raise ValueError("earliest_start_hour must be before deadline_hour")
        if self.energy_required_wh > self.max_power_w * (
            self.deadline_hour - self.earliest_start_hour
        ):
            raise ValueError("requested energy cannot fit inside the scheduling window")
        return self


class ScheduledLoadSegment(BaseModel):
    start_hour: int
    duration_hours: int
    power_w: float
    energy_wh: float


class FlexibleLoadScheduleResult(BaseModel):
    site_uid: str
    generated_at: datetime
    priority: LoadPriority
    interruptible: bool
    segments: list[ScheduledLoadSegment]
    scheduled_energy_wh: float
    baseline_risk: float
    scheduled_risk: float
    minimum_soc_p50_percent: float
    candidate_count: int
    recommendation: Literal["schedule", "defer", "surplus_only"]


class OptimizationRequest(BaseModel):
    horizon_hours: int = Field(default=72, ge=1, le=168)
    target_reserve_breach_probability: float = Field(default=0.02, ge=0, le=1)
    array_watts_min: float | None = Field(default=None, gt=0)
    array_watts_max: float | None = Field(default=None, gt=0)
    array_watts_step: float = Field(default=100.0, gt=0)
    battery_capacity_wh_min: float | None = Field(default=None, gt=0)
    battery_capacity_wh_max: float | None = Field(default=None, gt=0)
    battery_capacity_wh_step: float = Field(default=500.0, gt=0)
    pv_cost_per_w: float | None = Field(default=None, ge=0)
    battery_cost_per_wh: float | None = Field(default=None, ge=0)
    max_candidates: int = Field(default=200, ge=1, le=500)

    @model_validator(mode="after")
    def validate_ranges(self) -> OptimizationRequest:
        if (
            self.array_watts_min is not None
            and self.array_watts_max is not None
            and self.array_watts_min > self.array_watts_max
        ):
            raise ValueError("array_watts_min must not exceed array_watts_max")
        if (
            self.battery_capacity_wh_min is not None
            and self.battery_capacity_wh_max is not None
            and self.battery_capacity_wh_min > self.battery_capacity_wh_max
        ):
            raise ValueError("battery_capacity_wh_min must not exceed battery_capacity_wh_max")
        return self


class OptimizationCandidate(BaseModel):
    array_watts: float
    battery_capacity_wh: float
    reserve_breach_probability: float
    minimum_soc_p50_percent: float
    safe_discretionary_energy_wh: float
    incremental_cost: float | None = None
    meets_target: bool


class OptimizationResult(BaseModel):
    site_uid: str
    generated_at: datetime
    baseline: OptimizationCandidate
    target_reserve_breach_probability: float
    evaluated_candidates: int
    candidates: list[OptimizationCandidate]


class AuxiliaryPlanRequest(BaseModel):
    horizon_hours: int = Field(default=72, ge=1, le=168)
    target_reserve_breach_probability: float = Field(default=0.05, ge=0, le=1)
    source_power_w: float = Field(gt=0)
    max_energy_wh: float = Field(gt=0)
    earliest_start_hour: int = Field(default=0, ge=0)
    latest_end_hour: int = Field(default=72, ge=1, le=168)

    @model_validator(mode="after")
    def validate_window(self) -> AuxiliaryPlanRequest:
        if self.latest_end_hour > self.horizon_hours:
            raise ValueError("latest_end_hour cannot exceed horizon_hours")
        if self.earliest_start_hour >= self.latest_end_hour:
            raise ValueError("earliest_start_hour must be before latest_end_hour")
        return self


class AuxiliaryPlanResult(BaseModel):
    site_uid: str
    generated_at: datetime
    required_energy_wh: float
    source_power_w: float
    start_hour: int | None
    duration_hours: int
    baseline_risk: float
    planned_risk: float
    target_risk: float
    feasible: bool
    operator_action_required: bool = True
    executable: bool = False


class MetricScore(BaseModel):
    metric: str
    horizon_hours: int | None = None
    sample_count: int
    mae: float | None
    bias: float | None
    p10_p90_coverage: float | None


class ForecastScoreSummary(BaseModel):
    site_uid: str
    generated_at: datetime
    forecast_count: int
    metrics: list[MetricScore]


class ReserveRiskFeed(BaseModel):
    site_uid: str
    generated_at: datetime
    horizon_hours: int
    reserve_breach_probability: float = Field(ge=0, le=1)
    first_reserve_breach_at: datetime | None
    minimum_soc_p10_percent: float
    minimum_soc_p50_percent: float
    confidence: Literal["low", "medium", "high"]
    forecast_model_version: str
    calibration_version: str | None
    signature: str | None = None


class SiteDigitalTwin(BaseModel):
    site_uid: str
    generated_at: datetime
    battery: BatteryTwinSnapshot
    pv_arrays: list[PVArrayConfig]
    component_graph: dict
    energy_ledger: dict
    calibration: SiteCalibration | None
    input_quality: dict[str, str]


class ActionPlanAction(BaseModel):
    kind: Literal[
        "use_surplus",
        "defer_flexible_loads",
        "preserve_reserve",
        "plan_auxiliary_source",
        "improve_observability",
    ]
    priority: Literal["low", "medium", "high"]
    reason: str
    executable: bool = False
    requires_operator_approval: bool = True


class ActionPlan(BaseModel):
    site_uid: str
    generated_at: datetime
    forecast_model_version: str
    reserve_breach_probability: float
    actions: list[ActionPlanAction]
    read_only: bool = True


class SiteDescriptor(BaseModel):
    site_uid: str
    name: str | None = None
