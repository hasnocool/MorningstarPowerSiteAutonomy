from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


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


class WeatherHour(BaseModel):
    timestamp: datetime
    shortwave_radiation_w_m2: float = Field(ge=0)
    cloud_cover_percent: float | None = Field(default=None, ge=0, le=100)
    temperature_c: float | None = None


class ForecastPoint(BaseModel):
    timestamp: datetime
    solar_p10_w: float
    solar_p50_w: float
    solar_p90_w: float
    load_p10_w: float
    load_p50_w: float
    load_p90_w: float
    soc_p10_percent: float
    soc_p50_percent: float
    soc_p90_percent: float


class ForecastSummary(BaseModel):
    site_uid: str
    generated_at: datetime
    horizon_hours: int
    minimum_soc_p10_percent: float
    minimum_soc_p50_percent: float
    minimum_soc_p90_percent: float
    reserve_breach_probability: float = Field(ge=0, le=1)
    first_reserve_breach_at: datetime | None
    expected_solar_wh: float
    expected_load_wh: float
    discretionary_energy_wh: float
    autonomy_hours_if_no_solar: float | None
    confidence: Literal["low", "medium", "high"]
    input_quality: dict[str, str]
    points: list[ForecastPoint]


class AdditionalLoad(BaseModel):
    power_w: float = Field(gt=0)
    start_hour: int = Field(default=0, ge=0)
    duration_hours: int = Field(gt=0, le=168)


class ScenarioRequest(BaseModel):
    horizon_hours: int = Field(default=72, ge=1, le=168)
    additional_loads: list[AdditionalLoad] = Field(default_factory=list)
    array_watts: float | None = Field(default=None, gt=0)
    battery_capacity_wh: float | None = Field(default=None, gt=0)
    reserve_percent: float | None = Field(default=None, ge=0, le=95)

    @model_validator(mode="after")
    def validate_load_window(self) -> ScenarioRequest:
        for load in self.additional_loads:
            if load.start_hour + load.duration_hours > self.horizon_hours:
                raise ValueError("additional load extends past scenario horizon")
        return self


class ScenarioResult(BaseModel):
    site_uid: str
    generated_at: datetime
    baseline: ForecastSummary
    scenario: ForecastSummary
    additional_energy_wh: float
    risk_delta: float
    recommendation: Literal["low_risk", "elevated_risk", "high_risk"]


class SiteDescriptor(BaseModel):
    site_uid: str
    name: str | None = None
