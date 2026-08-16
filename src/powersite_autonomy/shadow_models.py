# src/powersite_autonomy/shadow_models.py
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .models import ForecastSummary, LoadPriority


class PolicyWeights(BaseModel):
    reserve_risk: float = Field(default=100.0, ge=0)
    unserved_critical_load: float = Field(default=1000.0, ge=0)
    battery_degradation: float = Field(default=15.0, ge=0)
    curtailed_solar: float = Field(default=3.0, ge=0)
    auxiliary_energy: float = Field(default=20.0, ge=0)
    deferred_load: float = Field(default=5.0, ge=0)
    load_interruptions: float = Field(default=2.0, ge=0)


class EnergyPolicy(BaseModel):
    policy_version: str = "energy-policy-v1"
    minimum_reserve_percent: float = Field(default=25.0, ge=0, le=95)
    emergency_reserve_percent: float = Field(default=15.0, ge=0, le=95)
    target_morning_soc_percent: float = Field(default=40.0, ge=0, le=100)
    target_reserve_breach_probability: float = Field(default=0.05, ge=0, le=1)
    maximize_solar_self_consumption: bool = True
    minimize_auxiliary_energy: bool = True
    minimize_battery_degradation: bool = True
    auxiliary_source_power_w: float | None = Field(default=None, gt=0)
    auxiliary_max_energy_wh: float = Field(default=0.0, ge=0)
    feedback_enabled: bool = True
    weights: PolicyWeights = Field(default_factory=PolicyWeights)

    @model_validator(mode="after")
    def validate_reserves(self) -> EnergyPolicy:
        if self.emergency_reserve_percent > self.minimum_reserve_percent:
            raise ValueError("emergency_reserve_percent must not exceed minimum_reserve_percent")
        return self


class ManagedLoad(BaseModel):
    load_id: str = Field(min_length=1)
    name: str | None = None
    priority: LoadPriority = LoadPriority.FLEXIBLE
    power_w: float = Field(gt=0)
    energy_required_wh: float = Field(gt=0)
    earliest_start_hour: int = Field(default=0, ge=0, le=167)
    deadline_hour: int = Field(default=24, ge=1, le=168)
    interruptible: bool = False
    enabled: bool = True

    @model_validator(mode="after")
    def validate_window(self) -> ManagedLoad:
        if self.earliest_start_hour >= self.deadline_hour:
            raise ValueError("earliest_start_hour must be before deadline_hour")
        capacity_wh = self.power_w * (self.deadline_hour - self.earliest_start_hour)
        if self.energy_required_wh > capacity_wh + 1e-6:
            raise ValueError("managed load energy cannot fit inside its scheduling window")
        return self


class ShadowAction(BaseModel):
    action_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime
    kind: Literal[
        "schedule_load",
        "defer_load",
        "preserve_reserve",
        "use_surplus",
        "plan_auxiliary_source",
        "improve_observability",
    ]
    target: str
    operation: str
    planned_power_w: float | None = Field(default=None, ge=0)
    planned_energy_wh: float = Field(default=0.0, ge=0)
    start_hour: int | None = Field(default=None, ge=0, le=167)
    duration_hours: int | None = Field(default=None, ge=0, le=168)
    window_start_hour: int | None = Field(default=None, ge=0, le=167)
    window_end_hour: int | None = Field(default=None, ge=1, le=168)
    expected_risk_delta: float = 0.0
    expected_min_soc_delta_percent: float = 0.0
    confidence: float = Field(default=0.5, ge=0, le=1)
    reason: str
    evidence_codes: list[str] = Field(default_factory=list)
    preconditions: list[str] = Field(default_factory=list)
    safety_constraints: list[str] = Field(default_factory=list)
    fallback: str = "Replan from fresh telemetry; do not execute stale shadow actions."
    policy_version: str
    forecast_model_version: str
    calibration_version: str | None = None
    model_epoch_id: str | None = None
    executable: bool = False
    requires_operator_approval: bool = True


class PlanAlternative(BaseModel):
    name: Literal["conservative", "balanced", "maximum_utilization"]
    objective_score: float
    reserve_breach_probability: float = Field(ge=0, le=1)
    minimum_soc_p10_percent: float
    minimum_soc_p50_percent: float
    expected_surplus_wh: float
    scheduled_load_wh: float
    deferred_load_wh: float
    auxiliary_energy_wh: float
    action_count: int


class ShadowAutopilotPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    horizon_hours: int = Field(ge=1, le=168)
    policy: EnergyPolicy
    baseline: ForecastSummary
    planned: ForecastSummary
    objective_score: float
    selected_mode: Literal["conservative", "balanced", "maximum_utilization"]
    alternatives: list[PlanAlternative]
    managed_loads: list[ManagedLoad]
    actions: list[ShadowAction]
    scheduled_load_wh: float = Field(ge=0)
    deferred_load_wh: float = Field(ge=0)
    auxiliary_energy_wh: float = Field(ge=0)
    model_epoch_id: str | None = None
    read_only: bool = True
    executable: bool = False


class DecisionScore(BaseModel):
    total_penalty: float = Field(ge=0)
    minimum_soc_percent: float
    reserve_breached: bool
    reserve_violation_wh: float = Field(ge=0)
    unserved_energy_wh: float = Field(ge=0)
    surplus_energy_wh: float = Field(ge=0)
    auxiliary_energy_wh: float = Field(ge=0)
    deferred_load_wh: float = Field(ge=0)
    battery_throughput_wh: float = Field(ge=0)
    load_interruptions: int = Field(ge=0)


class ModelFeedback(BaseModel):
    feedback_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    plan_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sample_count: int = Field(ge=0)
    solar_mae_w: float | None = Field(default=None, ge=0)
    solar_bias_w: float | None = None
    load_mae_w: float | None = Field(default=None, ge=0)
    load_bias_w: float | None = None
    soc_mae_percent: float | None = Field(default=None, ge=0)
    soc_bias_percent: float | None = None
    recommended_pv_scale_multiplier: float = Field(default=1.0, ge=0.5, le=1.5)
    recommended_load_scale_multiplier: float = Field(default=1.0, ge=0.5, le=1.5)
    primary_attribution: Literal[
        "weather_or_pv_model",
        "load_model",
        "battery_model",
        "optimizer_or_policy",
        "mixed",
        "insufficient_data",
    ] = "insufficient_data"
    confidence: float = Field(default=0.0, ge=0, le=1)
    applied_to_calibration: bool = False
    notes: list[str] = Field(default_factory=list)


class CounterfactualEvaluation(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: str(uuid4()))
    plan_id: str
    site_uid: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    observed_hours: int = Field(ge=0)
    actual: DecisionScore
    shadow: DecisionScore
    hindsight: DecisionScore
    decision_regret: float = Field(ge=0)
    regret_percent: float = Field(ge=0)
    shadow_improvement_vs_actual_percent: float
    feedback: ModelFeedback
    evidence_quality: Literal["low", "medium", "high"]
    notes: list[str] = Field(default_factory=list)


class ModelEpoch(BaseModel):
    epoch_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reason: Literal[
        "initial_shadow_autopilot_epoch",
        "pv_change_point",
        "load_change_point",
        "battery_capacity_change_point",
        "battery_impedance_change_point",
        "multiple_change_points",
    ]
    calibration_version: str | None = None
    previous_calibration_version: str | None = None
    signals: dict[str, float] = Field(default_factory=dict)


class AutopilotScorecard(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_count: int = Field(ge=0)
    average_decision_regret_percent: float | None = None
    median_decision_regret_percent: float | None = None
    average_shadow_improvement_percent: float | None = None
    actual_reserve_breaches: int = Field(ge=0)
    shadow_reserve_breaches: int = Field(ge=0)
    hindsight_reserve_breaches: int = Field(ge=0)
    potential_surplus_recovered_wh: float = Field(ge=0)
    shadow_auxiliary_energy_wh: float = Field(ge=0)
    shadow_deferred_load_wh: float = Field(ge=0)
    average_feedback_confidence: float | None = None


class AutopilotTickResult(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    plan: ShadowAutopilotPlan
    evaluations_created: int = Field(ge=0)
    feedback_adjustments_applied: int = Field(ge=0)
    model_epoch_created: ModelEpoch | None = None
