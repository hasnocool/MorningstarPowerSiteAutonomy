# src/powersite_autonomy/calibration.py
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime

from .models import HistoryPoint, RecurringLoadSignature, SiteCalibration, SiteConfig, WeatherHour
from .pv import estimate_site_pv_power_w


def _hour_key(timestamp: datetime) -> datetime:
    value = timestamp.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


def _local_hour(timestamp: datetime, utc_offset_hours: float) -> int:
    return int((timestamp.astimezone(UTC).hour + utc_offset_hours) % 24)


def _mean(values: list[float], fallback: float) -> float:
    return statistics.fmean(values) if values else fallback


def _sigma(values: list[float], mean: float) -> float:
    if len(values) >= 2:
        return max(8.0, statistics.pstdev(values))
    return max(8.0, abs(mean) * 0.12)


def _series_map(points: list[HistoryPoint]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for point in points:
        buckets[_hour_key(point.timestamp)].append(point.value)
    return {timestamp: statistics.fmean(values) for timestamp, values in buckets.items()}


def derive_power_series(
    history: dict[str, list[HistoryPoint]],
    power_names: tuple[str, ...],
    current_name: str,
    voltage_name: str,
) -> list[HistoryPoint]:
    for name in power_names:
        if history.get(name):
            return history[name]

    current = _series_map(history.get(current_name, []))
    voltage = _series_map(history.get(voltage_name, []))
    shared = sorted(current.keys() & voltage.keys())
    return [
        HistoryPoint(timestamp=timestamp, value=max(0.0, current[timestamp] * voltage[timestamp]))
        for timestamp in shared
    ]


def _build_load_profile(
    load_points: list[HistoryPoint],
    config: SiteConfig,
) -> tuple[list[float], list[float], list[float], list[RecurringLoadSignature]]:
    by_hour: dict[int, list[float]] = defaultdict(list)
    by_weekday: dict[int, list[float]] = defaultdict(list)
    all_values: list[float] = []
    for point in load_points:
        value = max(0.0, point.value)
        local_hour = _local_hour(point.timestamp, config.utc_offset_hours)
        local_weekday = point.timestamp.astimezone(UTC).weekday()
        by_hour[local_hour].append(value)
        by_weekday[local_weekday].append(value)
        all_values.append(value)

    global_mean = _mean(all_values, config.load_watts_fallback)
    hourly_mean = [_mean(by_hour[hour], global_mean) for hour in range(24)]
    hourly_sigma = [_sigma(by_hour[hour], hourly_mean[hour]) for hour in range(24)]
    weekday_multiplier = [
        max(0.4, min(2.5, _mean(by_weekday[day], global_mean) / max(1.0, global_mean)))
        for day in range(7)
    ]

    baseline = min(hourly_mean) if hourly_mean else global_mean
    threshold = max(25.0, baseline * 0.20)
    signatures: list[RecurringLoadSignature] = []
    for hour, mean_value in enumerate(hourly_mean):
        increment = max(0.0, mean_value - baseline)
        samples = by_hour[hour]
        if increment < threshold or len(samples) < 2:
            continue
        high_count = sum(value >= baseline + threshold for value in samples)
        signatures.append(
            RecurringLoadSignature(
                signature_id=f"hour-{hour:02d}",
                local_hour=hour,
                incremental_power_w=increment,
                occurrence_probability=high_count / len(samples),
                sample_count=len(samples),
            )
        )
    return hourly_mean, hourly_sigma, weekday_multiplier, signatures


def _build_pv_scaling(
    solar_points: list[HistoryPoint],
    weather_history: list[WeatherHour],
    config: SiteConfig,
) -> tuple[float, list[float], int]:
    solar = _series_map(solar_points)
    weather = {_hour_key(item.timestamp): item for item in weather_history}
    ratios: list[float] = []
    ratios_by_hour: dict[int, list[float]] = defaultdict(list)
    for timestamp in sorted(solar.keys() & weather.keys()):
        observed = max(0.0, solar[timestamp])
        conditions = weather[timestamp]
        if conditions.shortwave_radiation_w_m2 < 80:
            continue
        predicted = estimate_site_pv_power_w(conditions, config, calibration=None)
        if predicted < 20:
            continue
        ratio = max(0.2, min(2.0, observed / predicted))
        ratios.append(ratio)
        ratios_by_hour[_local_hour(timestamp, config.utc_offset_hours)].append(ratio)

    global_scale = statistics.median(ratios) if ratios else 1.0
    hourly_scale = []
    for hour in range(24):
        bucket = ratios_by_hour[hour]
        local = statistics.median(bucket) if len(bucket) >= 3 else global_scale
        # Keep the hourly factor relative to the learned global scale so it does not double count.
        hourly_scale.append(max(0.5, min(1.5, local / max(0.2, global_scale))))
    return global_scale, hourly_scale, len(ratios)


def _estimate_battery_capacity(
    history: dict[str, list[HistoryPoint]],
    config: SiteConfig,
) -> tuple[float | None, int]:
    soc_points = history.get("battery_soc_percent", [])
    if len(soc_points) < 2:
        return None, 0

    net_power = derive_power_series(
        history,
        ("battery_net_power_w",),
        "battery_net_current_a",
        "battery_voltage_v",
    )
    if not net_power:
        return None, 0

    soc = _series_map(soc_points)
    power = _series_map(net_power)
    timestamps = sorted(soc.keys() & power.keys())
    candidates: list[float] = []
    for first, second in zip(timestamps, timestamps[1:], strict=False):
        delta_hours = (second - first).total_seconds() / 3600
        if not 0.5 <= delta_hours <= 2.0:
            continue
        delta_soc = soc[second] - soc[first]
        if abs(delta_soc) < 2.0:
            continue
        average_power = (abs(power[first]) + abs(power[second])) / 2
        energy_wh = average_power * delta_hours
        estimated_capacity = energy_wh / (abs(delta_soc) / 100)
        lower_bound = 0.2 * config.battery_capacity_wh
        upper_bound = 1.5 * config.battery_capacity_wh
        if lower_bound <= estimated_capacity <= upper_bound:
            candidates.append(estimated_capacity)
    if len(candidates) < 3:
        return None, len(candidates)
    return statistics.median(candidates), len(candidates)


def _estimate_internal_resistance(
    history: dict[str, list[HistoryPoint]],
) -> tuple[float | None, int]:
    current = _series_map(history.get("battery_net_current_a", []))
    voltage = _series_map(history.get("battery_voltage_v", []))
    timestamps = sorted(current.keys() & voltage.keys())
    estimates: list[float] = []
    for first, second in zip(timestamps, timestamps[1:], strict=False):
        delta_i = current[second] - current[first]
        delta_v = voltage[second] - voltage[first]
        if abs(delta_i) < 1.0:
            continue
        resistance = abs(delta_v / delta_i)
        if 0.0001 <= resistance <= 0.5:
            estimates.append(resistance)
    if len(estimates) < 3:
        return None, len(estimates)
    return statistics.median(estimates), len(estimates)


def build_calibration(
    *,
    site_uid: str,
    config: SiteConfig,
    history: dict[str, list[HistoryPoint]],
    weather_history: list[WeatherHour],
    history_days: int,
    generated_at: datetime | None = None,
) -> SiteCalibration:
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    hourly_load, hourly_sigma, weekday_multiplier, signatures = _build_load_profile(
        load_points,
        config,
    )
    solar_points = history.get("solar_input_power_w", [])
    pv_scale, pv_scale_by_hour, pv_samples = _build_pv_scaling(
        solar_points,
        weather_history,
        config,
    )
    estimated_capacity, capacity_samples = _estimate_battery_capacity(history, config)
    estimated_resistance, resistance_samples = _estimate_internal_resistance(history)

    notes: list[str] = []
    if not load_points:
        notes.append(
            "load profile uses configured fallback because historical load evidence was unavailable"
        )
    if pv_samples == 0:
        notes.append(
            "PV scale remains neutral because aligned solar/weather history was unavailable"
        )
    if estimated_capacity is None:
        notes.append(
            "usable battery capacity remains configured because history did not support an estimate"
        )

    sample_counts = {name: len(points) for name, points in history.items()}
    sample_counts.update(
        {
            "derived_load": len(load_points),
            "pv_calibration_pairs": pv_samples,
            "battery_capacity_windows": capacity_samples,
            "internal_resistance_windows": resistance_samples,
        }
    )
    return SiteCalibration(
        site_uid=site_uid,
        generated_at=generated_at or datetime.now(UTC),
        history_days=history_days,
        hourly_load_profile_w=hourly_load,
        hourly_load_sigma_w=hourly_sigma,
        weekday_load_multiplier=weekday_multiplier,
        pv_scale_factor=max(0.2, min(2.0, pv_scale)),
        pv_scale_by_hour=pv_scale_by_hour,
        estimated_usable_battery_capacity_wh=estimated_capacity,
        estimated_internal_resistance_ohm=estimated_resistance,
        recurring_load_signatures=signatures,
        sample_counts=sample_counts,
        notes=notes,
    )
