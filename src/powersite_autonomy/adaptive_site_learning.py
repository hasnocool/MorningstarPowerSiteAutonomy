# src/powersite_autonomy/adaptive_site_learning.py
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from .adaptive_models import (
    LoadEventCluster,
    ManagedLoadCompletionEvidence,
    SeasonalCalibrationOverlay,
    SeasonalCell,
)
from .calibration import derive_power_series
from .models import HistoryPoint, SiteCalibration, SiteConfig, WeatherHour
from .pv import estimate_site_pv_power_w
from .shadow_models import ShadowAutopilotPlan


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


def build_seasonal_overlay(
    *,
    site_uid: str,
    config: SiteConfig,
    calibration: SiteCalibration | None,
    history: dict[str, list[HistoryPoint]],
    weather_history: list[WeatherHour],
    history_days: int,
    minimum_samples_per_cell: int = 4,
) -> SeasonalCalibrationOverlay:
    solar = series_map(history.get("solar_input_power_w", []))
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    load = series_map(load_points)
    weather = {hour_key(item.timestamp): item for item in weather_history}
    pv_ratios: dict[tuple[int, int], list[float]] = defaultdict(list)
    loads: dict[tuple[int, int], list[float]] = defaultdict(list)

    for timestamp, observed in solar.items():
        conditions = weather.get(timestamp)
        if conditions is None or conditions.shortwave_radiation_w_m2 < 80:
            continue
        predicted = estimate_site_pv_power_w(conditions, config, calibration)
        if predicted < 20:
            continue
        local = local_datetime(timestamp, config.utc_offset_hours)
        ratio = max(0.4, min(1.8, max(0.0, observed) / predicted))
        pv_ratios[(local.month, local.hour)].append(ratio)

    for timestamp, observed in load.items():
        local = local_datetime(timestamp, config.utc_offset_hours)
        loads[(local.month, local.hour)].append(max(0.0, observed))

    keys = sorted(set(pv_ratios) | set(loads))
    cells: list[SeasonalCell] = []
    for month, hour in keys:
        pv_values = pv_ratios.get((month, hour), [])
        load_values = loads.get((month, hour), [])
        sample_count = max(len(pv_values), len(load_values))
        if sample_count < minimum_samples_per_cell:
            continue
        load_mean = statistics.fmean(load_values) if load_values else None
        load_sigma = (
            max(8.0, statistics.pstdev(load_values))
            if len(load_values) >= 2
            else (max(8.0, (load_mean or 0.0) * 0.12) if load_mean is not None else None)
        )
        cells.append(
            SeasonalCell(
                month=month,
                local_hour=hour,
                sample_count=sample_count,
                pv_residual_scale=statistics.median(pv_values) if pv_values else 1.0,
                load_mean_w=load_mean,
                load_sigma_w=load_sigma,
            )
        )
    return SeasonalCalibrationOverlay(
        site_uid=site_uid,
        history_days=history_days,
        minimum_samples_per_cell=minimum_samples_per_cell,
        cells=cells,
    )


def discover_load_events(
    *,
    site_uid: str,
    config: SiteConfig,
    calibration: SiteCalibration | None,
    history: dict[str, list[HistoryPoint]],
) -> list[LoadEventCluster]:
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    load = series_map(load_points)
    if not load:
        return []

    ordered = sorted(load.items())
    events: list[tuple[datetime, int, float]] = []
    current_start: datetime | None = None
    current_values: list[float] = []
    previous_time: datetime | None = None

    def baseline_for(timestamp: datetime) -> tuple[float, float]:
        local = local_datetime(timestamp, config.utc_offset_hours)
        if calibration is None:
            mean = config.load_watts_fallback
            return mean, max(8.0, mean * 0.12)
        mean = calibration.hourly_load_profile_w[local.hour]
        mean *= calibration.weekday_load_multiplier[local.weekday()]
        return mean, calibration.hourly_load_sigma_w[local.hour]

    def flush() -> None:
        nonlocal current_start, current_values
        if current_start is not None and current_values:
            events.append((current_start, len(current_values), statistics.fmean(current_values)))
        current_start = None
        current_values = []

    for timestamp, value in ordered:
        baseline, sigma = baseline_for(timestamp)
        delta = max(0.0, value - baseline)
        active = delta >= max(25.0, 1.75 * sigma)
        contiguous = previous_time is not None and timestamp - previous_time <= timedelta(hours=1.5)
        if active:
            if current_start is None or not contiguous:
                flush()
                current_start = timestamp
            current_values.append(delta)
        else:
            flush()
        previous_time = timestamp
    flush()

    grouped: dict[tuple[int, int], list[tuple[datetime, int, float]]] = defaultdict(list)
    for event in events:
        _, duration, delta = event
        delta_bucket = max(25, int(round(delta / 25.0) * 25))
        duration_bucket = min(8, duration)
        grouped[(delta_bucket, duration_bucket)].append(event)

    days = max(1, len({local_datetime(ts, config.utc_offset_hours).date() for ts in load}))
    clusters: list[LoadEventCluster] = []
    for (_, _), group in grouped.items():
        if len(group) < 2:
            continue
        starts = sorted(local_datetime(item[0], config.utc_offset_hours).hour for item in group)
        durations = sorted(item[1] for item in group)
        deltas = [item[2] for item in group]
        confidence = min(0.98, 0.35 + 0.08 * len(group))
        clusters.append(
            LoadEventCluster(
                site_uid=site_uid,
                delta_power_w=statistics.median(deltas),
                duration_hours_p50=float(statistics.median(durations)),
                local_start_hour_p50=int(statistics.median(starts)),
                occurrence_probability=min(1.0, len(group) / days),
                sample_count=len(group),
                confidence=confidence,
            )
        )
    return sorted(
        clusters,
        key=lambda item: item.delta_power_w * item.occurrence_probability,
        reverse=True,
    )[:12]


def infer_managed_load_completion(
    *,
    site_uid: str,
    plans: list[ShadowAutopilotPlan],
    history: dict[str, list[HistoryPoint]],
) -> list[ManagedLoadCompletionEvidence]:
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    actual_load = series_map(load_points)
    results: list[ManagedLoadCompletionEvidence] = []
    for plan in plans:
        for action in plan.actions:
            if action.kind != "schedule_load":
                continue
            if action.start_hour is None or action.duration_hours is None:
                continue
            if action.planned_energy_wh <= 0:
                continue
            observed = 0.0
            observed_hours = 0
            expected_hours = max(0, action.duration_hours)
            for offset in range(action.duration_hours):
                index = action.start_hour + offset
                if index >= len(plan.baseline.points):
                    continue
                timestamp = hour_key(plan.baseline.points[index].timestamp)
                actual = actual_load.get(timestamp)
                if actual is None:
                    continue
                baseline = plan.baseline.points[index].load_p50_w
                observed += max(0.0, actual - baseline)
                observed_hours += 1
            if observed_hours == 0:
                continue
            coverage = observed_hours / max(1, expected_hours)
            ratio = min(1.5, observed / action.planned_energy_wh)
            closeness = max(0.0, 1.0 - abs(1.0 - min(1.0, ratio)))
            confidence = min(0.70, 0.15 + 0.40 * coverage + 0.15 * closeness)
            results.append(
                ManagedLoadCompletionEvidence(
                    evidence_id=f"{plan.plan_id}:{action.target}",
                    site_uid=site_uid,
                    plan_id=plan.plan_id,
                    load_id=action.target,
                    planned_energy_wh=action.planned_energy_wh,
                    matched_incremental_energy_wh=observed,
                    completion_ratio_estimate=ratio,
                    observed_hours=observed_hours,
                    expected_hours=expected_hours,
                    confidence=confidence,
                )
            )
    return results
