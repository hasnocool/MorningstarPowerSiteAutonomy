# src/powersite_autonomy/forecast.py
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from .battery import build_battery_twin
from .models import (
    AdditionalLoad,
    AdditionalSource,
    ForecastPoint,
    ForecastSummary,
    SentinelFeedback,
    SiteCalibration,
    SiteConfig,
    WeatherHour,
)
from .pv import estimate_site_pv_power_w
from .upstream import SiteState


@dataclass(frozen=True, slots=True)
class ForecastInputs:
    site_uid: str
    config: SiteConfig
    state: SiteState
    weather: list[WeatherHour]
    calibration: SiteCalibration | None = None
    sentinel_feedback: SentinelFeedback | None = None
    additional_loads: tuple[AdditionalLoad, ...] = ()
    additional_sources: tuple[AdditionalSource, ...] = ()


def _percentile(values: list[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = (len(ordered) - 1) * percentile / 100
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _local_datetime(timestamp: datetime, offset_hours: float) -> datetime:
    return timestamp.astimezone(UTC) + timedelta(hours=offset_hours)


def _live_load_scale(inputs: ForecastInputs) -> float:
    if inputs.calibration is None or inputs.state.load_power_w is None:
        return 1.0
    now_local = _local_datetime(datetime.now(UTC), inputs.config.utc_offset_hours)
    expected = inputs.calibration.hourly_load_profile_w[now_local.hour]
    if expected <= 1:
        return 1.0
    return max(0.5, min(2.0, inputs.state.load_power_w / expected))


def _load_parameters(
    inputs: ForecastInputs,
    weather: WeatherHour,
    *,
    live_scale: float,
) -> tuple[float, float]:
    calibration = inputs.calibration
    if calibration is None:
        base = (
            inputs.state.load_power_w
            if inputs.state.load_power_w is not None
            else inputs.config.load_watts_fallback
        )
        return max(0.0, base), max(8.0, base * 0.12)

    local = _local_datetime(weather.timestamp, inputs.config.utc_offset_hours)
    mean = calibration.hourly_load_profile_w[local.hour]
    mean *= calibration.weekday_load_multiplier[local.weekday()]
    mean *= live_scale
    sigma = calibration.hourly_load_sigma_w[local.hour]
    return max(0.0, mean), max(8.0, sigma)


def _active_window_power(items: tuple[AdditionalLoad, ...], hour_index: int) -> float:
    return sum(
        item.power_w
        for item in items
        if item.start_hour <= hour_index < item.start_hour + item.duration_hours
    )


def _active_source_power(items: tuple[AdditionalSource, ...], hour_index: int) -> float:
    return sum(
        item.power_w
        for item in items
        if item.start_hour <= hour_index < item.start_hour + item.duration_hours
    )


def build_forecast(
    inputs: ForecastInputs,
    *,
    samples: int = 300,
    seed: int | None = None,
) -> ForecastSummary:
    config = inputs.config
    hours = len(inputs.weather)
    sentinel = inputs.sentinel_feedback or SentinelFeedback()
    battery = build_battery_twin(config, inputs.state, inputs.calibration)
    effective_capacity_wh = battery.effective_capacity_wh
    reserve_wh = effective_capacity_wh * config.reserve_percent / 100
    base_soc = battery.soc_percent
    seed_value = (
        seed
        if seed is not None
        else hash((inputs.site_uid, hours, "forecast-v2")) & 0xFFFFFFFF
    )
    rng = random.Random(seed_value)
    uncertainty_multiplier = sentinel.forecast_uncertainty_multiplier
    live_scale = _live_load_scale(inputs)

    solar_samples: list[list[float]] = [[] for _ in range(hours)]
    load_samples: list[list[float]] = [[] for _ in range(hours)]
    surplus_samples: list[list[float]] = [[] for _ in range(hours)]
    soc_samples: list[list[float]] = [[] for _ in range(hours)]
    breach_count = 0
    unmet_count = 0
    first_breaches: list[datetime] = []

    soc_sigma = 2.0 if inputs.state.soc_percent is not None else 8.0
    if not sentinel.soc_reliable:
        soc_sigma = max(soc_sigma, 8.0)
    soc_sigma *= uncertainty_multiplier

    actual_samples = max(20, samples)
    for _ in range(actual_samples):
        sampled_soc = max(0.0, min(100.0, rng.gauss(base_soc, soc_sigma)))
        energy_wh = effective_capacity_wh * sampled_soc / 100
        breached = False
        unmet = False
        first_breach: datetime | None = None

        for index, weather in enumerate(inputs.weather):
            nominal_solar_w = estimate_site_pv_power_w(weather, config, inputs.calibration)
            nominal_solar_w *= sentinel.pv_derate_factor
            cloud_fraction = (weather.cloud_cover_percent or 0.0) / 100
            relative_sigma = 0.08 + 0.18 * cloud_fraction
            if (
                weather.shortwave_radiation_spread_w_m2 is not None
                and weather.shortwave_radiation_w_m2 > 20
            ):
                ensemble_relative = (
                    weather.shortwave_radiation_spread_w_m2
                    / weather.shortwave_radiation_w_m2
                )
                relative_sigma = max(relative_sigma, min(0.75, ensemble_relative))
            relative_sigma *= uncertainty_multiplier
            solar_w = max(
                0.0,
                rng.gauss(nominal_solar_w, max(4.0, nominal_solar_w * relative_sigma)),
            )

            load_mean, load_sigma = _load_parameters(inputs, weather, live_scale=live_scale)
            load_w = max(
                0.0,
                rng.gauss(load_mean, load_sigma * uncertainty_multiplier),
            )
            load_w += _active_window_power(inputs.additional_loads, index)
            auxiliary_w = _active_source_power(inputs.additional_sources, index)
            production_w = solar_w + auxiliary_w
            raw_surplus_w = max(0.0, solar_w - load_w)
            net_w = production_w - load_w

            if net_w >= 0:
                accepted_w = net_w
                if battery.max_charge_power_w is not None:
                    accepted_w = min(accepted_w, battery.max_charge_power_w)
                energy_wh += accepted_w * config.charge_efficiency
                energy_wh = min(effective_capacity_wh, energy_wh)
            else:
                deficit_w = -net_w
                discharge_limit_w = deficit_w
                if battery.max_discharge_power_w is not None:
                    discharge_limit_w = min(discharge_limit_w, battery.max_discharge_power_w)
                energy_limit_w = max(0.0, energy_wh * config.discharge_efficiency)
                delivered_w = min(discharge_limit_w, energy_limit_w)
                energy_wh -= delivered_w / config.discharge_efficiency
                energy_wh = max(0.0, energy_wh)
                if delivered_w + 1e-6 < deficit_w:
                    unmet = True

            soc = 100 * energy_wh / effective_capacity_wh
            solar_samples[index].append(solar_w)
            load_samples[index].append(load_w)
            surplus_samples[index].append(raw_surplus_w)
            soc_samples[index].append(soc)
            if not breached and energy_wh <= reserve_wh:
                breached = True
                first_breach = weather.timestamp

        if breached:
            breach_count += 1
            if first_breach is not None:
                first_breaches.append(first_breach)
        if unmet:
            unmet_count += 1

    points = [
        ForecastPoint(
            timestamp=weather.timestamp,
            solar_p10_w=_percentile(solar_samples[i], 10),
            solar_p50_w=_percentile(solar_samples[i], 50),
            solar_p90_w=_percentile(solar_samples[i], 90),
            load_p10_w=_percentile(load_samples[i], 10),
            load_p50_w=_percentile(load_samples[i], 50),
            load_p90_w=_percentile(load_samples[i], 90),
            surplus_p10_w=_percentile(surplus_samples[i], 10),
            surplus_p50_w=_percentile(surplus_samples[i], 50),
            surplus_p90_w=_percentile(surplus_samples[i], 90),
            soc_p10_percent=_percentile(soc_samples[i], 10),
            soc_p50_percent=_percentile(soc_samples[i], 50),
            soc_p90_percent=_percentile(soc_samples[i], 90),
        )
        for i, weather in enumerate(inputs.weather)
    ]

    expected_solar_wh = sum(point.solar_p50_w for point in points)
    expected_load_wh = sum(point.load_p50_w for point in points)
    expected_surplus_wh = sum(point.surplus_p50_w for point in points)
    minimum_p10 = min((point.soc_p10_percent for point in points), default=base_soc)
    minimum_p50 = min((point.soc_p50_percent for point in points), default=base_soc)
    minimum_p90 = min((point.soc_p90_percent for point in points), default=base_soc)
    initial_wh = effective_capacity_wh * base_soc / 100
    usable_above_reserve = max(0.0, initial_wh - reserve_wh)
    mean_load_w = expected_load_wh / max(1, hours)
    autonomy_hours = (
        None
        if mean_load_w <= 0
        else usable_above_reserve * config.discharge_efficiency / mean_load_w
    )
    discretionary = max(
        0.0,
        usable_above_reserve
        + expected_solar_wh * config.charge_efficiency
        - expected_load_wh / config.discharge_efficiency,
    )
    conservative_solar_wh = sum(point.solar_p10_w for point in points)
    conservative_load_wh = sum(point.load_p90_w for point in points)
    safe_discretionary = max(
        0.0,
        usable_above_reserve
        + conservative_solar_wh * config.charge_efficiency
        - conservative_load_wh / config.discharge_efficiency,
    )

    quality = dict(inputs.state.input_quality)
    quality["weather"] = (
        "ensemble_forecast"
        if any(item.shortwave_radiation_spread_w_m2 for item in inputs.weather)
        else "forecast"
    )
    quality["calibration"] = "learned" if inputs.calibration is not None else "unavailable"
    quality["sentinel"] = "reachable" if sentinel.reachable else "unavailable"

    confidence: str = "high"
    if "fallback" in quality.values() or inputs.calibration is None:
        confidence = "medium"
    if inputs.state.soc_percent is None and inputs.state.load_power_w is None:
        confidence = "low"
    if not sentinel.telemetry_reliable:
        confidence = "low" if confidence == "medium" else "medium"

    return ForecastSummary(
        site_uid=inputs.site_uid,
        generated_at=datetime.now(UTC),
        horizon_hours=hours,
        calibration_version=(
            inputs.calibration.calibration_version if inputs.calibration is not None else None
        ),
        minimum_soc_p10_percent=minimum_p10,
        minimum_soc_p50_percent=minimum_p50,
        minimum_soc_p90_percent=minimum_p90,
        reserve_breach_probability=breach_count / actual_samples,
        unmet_load_probability=unmet_count / actual_samples,
        first_reserve_breach_at=min(first_breaches) if first_breaches else None,
        expected_solar_wh=expected_solar_wh,
        expected_load_wh=expected_load_wh,
        expected_surplus_wh=expected_surplus_wh,
        discretionary_energy_wh=discretionary,
        safe_discretionary_energy_wh=safe_discretionary,
        autonomy_hours_if_no_solar=autonomy_hours,
        effective_battery_capacity_wh=effective_capacity_wh,
        confidence=confidence,  # type: ignore[arg-type]
        input_quality=quality,
        points=points,
    )
