from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import UTC, datetime

from .models import AdditionalLoad, ForecastPoint, ForecastSummary, SiteConfig, WeatherHour
from .upstream import SiteState


@dataclass(frozen=True, slots=True)
class ForecastInputs:
    site_uid: str
    config: SiteConfig
    state: SiteState
    weather: list[WeatherHour]
    additional_loads: tuple[AdditionalLoad, ...] = ()


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


def build_forecast(
    inputs: ForecastInputs,
    *,
    samples: int = 300,
    seed: int | None = None,
) -> ForecastSummary:
    config = inputs.config
    hours = len(inputs.weather)
    initial_soc = (
        inputs.state.soc_percent
        if inputs.state.soc_percent is not None
        else config.initial_soc_fallback_percent
    )
    base_load = (
        inputs.state.load_power_w
        if inputs.state.load_power_w is not None
        else config.load_watts_fallback
    )
    reserve_wh = config.battery_capacity_wh * config.reserve_percent / 100
    initial_wh = config.battery_capacity_wh * initial_soc / 100
    seed_value = seed if seed is not None else hash((inputs.site_uid, hours)) & 0xFFFFFFFF
    rng = random.Random(seed_value)

    solar_samples: list[list[float]] = [[] for _ in range(hours)]
    load_samples: list[list[float]] = [[] for _ in range(hours)]
    soc_samples: list[list[float]] = [[] for _ in range(hours)]
    breach_count = 0
    first_breaches: list[datetime] = []

    for _ in range(max(20, samples)):
        energy_wh = initial_wh
        breached = False
        first_breach: datetime | None = None
        for index, weather in enumerate(inputs.weather):
            nominal_solar_w = min(
                config.array_watts,
                config.array_watts
                * (weather.shortwave_radiation_w_m2 / 1000.0)
                * config.performance_ratio,
            )
            solar_sigma = 0.12 + 0.20 * ((weather.cloud_cover_percent or 0) / 100)
            solar_w = max(0.0, rng.gauss(nominal_solar_w, nominal_solar_w * solar_sigma))
            load_w = max(0.0, rng.gauss(base_load, max(8.0, base_load * 0.12)))
            load_w += sum(
                item.power_w
                for item in inputs.additional_loads
                if item.start_hour <= index < item.start_hour + item.duration_hours
            )
            net_wh = solar_w - load_w
            if net_wh >= 0:
                energy_wh += net_wh * config.charge_efficiency
            else:
                energy_wh += net_wh / config.discharge_efficiency
            energy_wh = min(config.battery_capacity_wh, max(0.0, energy_wh))
            soc = 100 * energy_wh / config.battery_capacity_wh
            solar_samples[index].append(solar_w)
            load_samples[index].append(load_w)
            soc_samples[index].append(soc)
            if not breached and energy_wh <= reserve_wh:
                breached = True
                first_breach = weather.timestamp
        if breached:
            breach_count += 1
            if first_breach is not None:
                first_breaches.append(first_breach)

    points = [
        ForecastPoint(
            timestamp=weather.timestamp,
            solar_p10_w=_percentile(solar_samples[i], 10),
            solar_p50_w=_percentile(solar_samples[i], 50),
            solar_p90_w=_percentile(solar_samples[i], 90),
            load_p10_w=_percentile(load_samples[i], 10),
            load_p50_w=_percentile(load_samples[i], 50),
            load_p90_w=_percentile(load_samples[i], 90),
            soc_p10_percent=_percentile(soc_samples[i], 10),
            soc_p50_percent=_percentile(soc_samples[i], 50),
            soc_p90_percent=_percentile(soc_samples[i], 90),
        )
        for i, weather in enumerate(inputs.weather)
    ]

    expected_solar_wh = sum(point.solar_p50_w for point in points)
    expected_load_wh = sum(point.load_p50_w for point in points)
    minimum_p10 = min((point.soc_p10_percent for point in points), default=initial_soc)
    minimum_p50 = min((point.soc_p50_percent for point in points), default=initial_soc)
    minimum_p90 = min((point.soc_p90_percent for point in points), default=initial_soc)
    usable_above_reserve = max(0.0, initial_wh - reserve_wh)
    autonomy_hours = (
        None
        if base_load <= 0
        else usable_above_reserve * config.discharge_efficiency / base_load
    )
    discretionary = max(
        0.0,
        usable_above_reserve
        + expected_solar_wh * config.charge_efficiency
        - expected_load_wh / config.discharge_efficiency,
    )
    quality = dict(inputs.state.input_quality)
    quality["weather"] = "forecast"
    confidence = "high"
    if "fallback" in quality.values():
        confidence = "medium"
    if inputs.state.soc_percent is None and inputs.state.load_power_w is None:
        confidence = "low"

    return ForecastSummary(
        site_uid=inputs.site_uid,
        generated_at=datetime.now(UTC),
        horizon_hours=hours,
        minimum_soc_p10_percent=minimum_p10,
        minimum_soc_p50_percent=minimum_p50,
        minimum_soc_p90_percent=minimum_p90,
        reserve_breach_probability=breach_count / max(20, samples),
        first_reserve_breach_at=min(first_breaches) if first_breaches else None,
        expected_solar_wh=expected_solar_wh,
        expected_load_wh=expected_load_wh,
        discretionary_energy_wh=discretionary,
        autonomy_hours_if_no_solar=autonomy_hours,
        confidence=confidence,
        input_quality=quality,
        points=points,
    )
