# src/powersite_autonomy/policy_models.py
from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from statistics import fmean
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from .shadow_models import EnergyPolicy


class PolicyRegime(StrEnum):
    NORMAL = "normal"
    SUNNY_SURPLUS = "sunny_surplus"
    LOW_SOLAR = "low_solar"
    EXTENDED_SCARCITY = "extended_scarcity"
    HIGH_LOAD = "high_load"
    BATTERY_DEGRADED = "battery_degraded"
    WEATHER_UNCERTAIN = "weather_uncertain"
    RECENT_CHANGE = "recent_change"


class PolicyObjective(StrEnum):
    BALANCED = "balanced"
    RESILIENCE = "resilience"
    SOLAR_UTILIZATION = "solar_utilization"
    BATTERY_PRESERVATION = "battery_preservation"
    MINIMUM_AUXILIARY = "minimum_auxiliary"


class PolicySearchBounds(BaseModel):
    minimum_reserve_min_percent: float = Field(default=10.0, ge=0, le=95)
    minimum_reserve_max_percent: float = Field(default=60.0, ge=0, le=95)
    morning_soc_min_percent: float = Field(default=25.0, ge=0, le=100)
    morning_soc_max_percent: float = Field(default=80.0, ge=0, le=100)
    reserve_risk_weight_min: float = Field(default=25.0, ge=0)
    reserve_risk_weight_max: float = Field(default=300.0, ge=0)
    battery_degradation_weight_min: float = Field(default=0.0, ge=0)
    battery_degradation_weight_max: float = Field(default=80.0, ge=0)
    curtailed_solar_weight_min: float = Field(default=0.0, ge=0)
    curtailed_solar_weight_max: float = Field(default=50.0, ge=0)
    auxiliary_energy_weight_min: float = Field(default=0.0, ge=0)
    auxiliary_energy_weight_max: float = Field(default=150.0, ge=0)
    deferred_load_weight_min: float = Field(default=0.0, ge=0)
    deferred_load_weight_max: float = Field(default=50.0, ge=0)

    @model_validator(mode="after")
    def validate_ranges(self) -> PolicySearchBounds:
        pairs = (
            (self.minimum_reserve_min_percent, self.minimum_reserve_max_percent),
            (self.morning_soc_min_percent, self.morning_soc_max_percent),
            (self.reserve_risk_weight_min, self.reserve_risk_weight_max),
            (self.battery_degradation_weight_min, self.battery_degradation_weight_max),
            (self.curtailed_solar_weight_min, self.curtailed_solar_weight_max),
            (self.auxiliary_energy_weight_min, self.auxiliary_energy_weight_max),
            (self.deferred_load_weight_min, self.deferred_load_weight_max),
        )
        if any(low > high for low, high in pairs):
            raise ValueError("policy search minimums must not exceed maximums")
        return self


class PolicyCandidate(BaseModel):
    policy_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    parent_policy_id: str | None = None
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    objective: PolicyObjective = PolicyObjective.BALANCED
    regime: PolicyRegime | None = None
    policy: EnergyPolicy
    status: Literal["champion", "challenger", "rejected"] = "challenger"
    origin: Literal["operator", "generated", "promoted"] = "generated"


class ReserveHorizonTarget(BaseModel):
    horizon_hours: int = Field(ge=1, le=168)
    target_reserve_percent: float = Field(ge=0, le=95)
    minimum_soc_p10_percent: float
    pressure: float = Field(ge=0, le=1)


class DynamicReserveRecommendation(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    regime: PolicyRegime
    base_reserve_percent: float = Field(ge=0, le=95)
    effective_reserve_percent: float = Field(ge=0, le=95)
    lower_bound_percent: float = Field(ge=0, le=95)
    upper_bound_percent: float = Field(ge=0, le=95)
    adjustments: dict[str, float] = Field(default_factory=dict)
    horizon_targets: list[ReserveHorizonTarget] = Field(default_factory=list)
    read_only: bool = True


class PolicyReplayRecord(BaseModel):
    plan_id: str
    generated_at: datetime
    regime: PolicyRegime
    selected_mode: Literal["conservative", "balanced", "maximum_utilization"]
    point_in_time_score: float = Field(ge=0)
    observed_penalty: float = Field(ge=0)
    total_score: float = Field(ge=0)
    predicted_emergency_breach: bool
    actual_reserve_breached: bool
    actual_safety_incident: bool
    actual_unserved_energy_wh: float = Field(ge=0)
    auxiliary_energy_wh: float = Field(ge=0)
    deferred_load_wh: float = Field(ge=0)
    scheduled_load_wh: float = Field(ge=0)
    battery_throughput_wh: float = Field(ge=0)
    surplus_energy_wh: float = Field(ge=0)


class PolicyEvaluation(BaseModel):
    evaluation_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    policy_id: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_count: int = Field(ge=0)
    mean_score: float | None = Field(default=None, ge=0)
    median_score: float | None = Field(default=None, ge=0)
    rolling_origin_fold_scores: list[float] = Field(default_factory=list)
    predicted_emergency_breaches: int = Field(default=0, ge=0)
    actual_safety_incidents: int = Field(default=0, ge=0)
    actual_unserved_energy_wh: float = Field(default=0.0, ge=0)
    auxiliary_energy_wh: float = Field(default=0.0, ge=0)
    deferred_load_wh: float = Field(default=0.0, ge=0)
    battery_throughput_wh: float = Field(default=0.0, ge=0)
    unused_surplus_wh: float = Field(default=0.0, ge=0)
    score_by_regime: dict[str, float] = Field(default_factory=dict)
    sample_scores: dict[str, float] = Field(default_factory=dict)

    @property
    def average_fold_score(self) -> float | None:
        return fmean(self.rolling_origin_fold_scores) if self.rolling_origin_fold_scores else None


class PolicyTournamentDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    champion_before: str
    challenger_id: str | None = None
    champion_after: str
    promoted: bool = False
    improvement_fraction: float = 0.0
    paired_confidence: float = Field(default=0.0, ge=0, le=1)
    safety_gate_passed: bool = False
    reason: str


class PolicyParetoPoint(BaseModel):
    policy_id: str
    objective: PolicyObjective
    regime: PolicyRegime | None = None
    mean_score: float = Field(ge=0)
    predicted_emergency_breaches: int = Field(ge=0)
    actual_safety_incidents: int = Field(ge=0)
    auxiliary_energy_wh: float = Field(ge=0)
    deferred_load_wh: float = Field(ge=0)
    battery_throughput_wh: float = Field(ge=0)


class PolicyFrontier(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    points: list[PolicyParetoPoint] = Field(default_factory=list)


class RegretDecomposition(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evaluation_count: int = Field(ge=0)
    total_regret: float = Field(default=0.0, ge=0)
    weather_model: float = Field(default=0.0, ge=0)
    pv_model: float = Field(default=0.0, ge=0)
    load_model: float = Field(default=0.0, ge=0)
    battery_model: float = Field(default=0.0, ge=0)
    policy_selection: float = Field(default=0.0, ge=0)
    optimizer_approximation: float = Field(default=0.0, ge=0)
    irreducible_uncertainty: float = Field(default=0.0, ge=0)


class DecisionSensitivitySignal(BaseModel):
    source: Literal["weather_pv", "load", "battery", "policy_optimizer"]
    sample_count: int = Field(ge=0)
    mean_normalized_error: float = Field(default=0.0, ge=0)
    mean_regret_percent: float = Field(default=0.0, ge=0)
    priority_score: float = Field(default=0.0, ge=0)


class DecisionSensitivitySummary(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    signals: list[DecisionSensitivitySignal] = Field(default_factory=list)


class AutonomyIntelligenceScore(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    forecast_accuracy: float = Field(ge=0, le=100)
    uncertainty_calibration: float = Field(ge=0, le=100)
    world_model_confidence: float = Field(ge=0, le=100)
    decision_quality: float = Field(ge=0, le=100)
    policy_quality: float = Field(ge=0, le=100)
    battery_model_confidence: float = Field(ge=0, le=100)
    change_stability: float = Field(ge=0, le=100)
    overall: float = Field(ge=0, le=100)
    biggest_opportunity: str


class PolicyLabScorecard(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    champion_policy_id: str
    replay_count: int = Field(ge=0)
    candidates_evaluated: int = Field(ge=0)
    promotions: int = Field(ge=0)
    pareto_policies: int = Field(ge=0)
    regime_champions: dict[str, str] = Field(default_factory=dict)
    latest_improvement_fraction: float = 0.0
    latest_paired_confidence: float = Field(default=0.0, ge=0, le=1)
    read_only: bool = True


class PolicyLabSnapshot(BaseModel):
    site_uid: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    champion: PolicyCandidate
    candidates: list[PolicyCandidate]
    evaluations: list[PolicyEvaluation]
    tournament: PolicyTournamentDecision
    frontier: PolicyFrontier
    regret: RegretDecomposition
    decision_sensitivity: DecisionSensitivitySummary
    intelligence: AutonomyIntelligenceScore
    scorecard: PolicyLabScorecard
    read_only: bool = True
    executable: bool = False
