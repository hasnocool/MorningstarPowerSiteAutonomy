# src/powersite_autonomy/scoring.py
from __future__ import annotations

import statistics
from datetime import UTC, datetime

from .calibration import derive_power_series
from .models import ForecastScoreSummary, ForecastSummary, HistoryPoint, MetricScore


def _hour_key(timestamp: datetime) -> datetime:
    value = timestamp.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


def _actual_map(points: list[HistoryPoint]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = {}
    for point in points:
        buckets.setdefault(_hour_key(point.timestamp), []).append(point.value)
    return {timestamp: statistics.fmean(values) for timestamp, values in buckets.items()}


def _score_metric(
    metric: str,
    forecasts: list[ForecastSummary],
    actual: dict[datetime, float],
    attrs: tuple[str, str, str],
    *,
    horizon_hours: int | None = None,
) -> MetricScore:
    errors: list[float] = []
    covered: list[bool] = []
    p10_attr, p50_attr, p90_attr = attrs
    now = datetime.now(UTC)
    for forecast in forecasts:
        for index, point in enumerate(forecast.points, start=1):
            if horizon_hours is not None and index != horizon_hours:
                continue
            if point.timestamp > now:
                continue
            actual_value = actual.get(_hour_key(point.timestamp))
            if actual_value is None:
                continue
            p10 = float(getattr(point, p10_attr))
            p50 = float(getattr(point, p50_attr))
            p90 = float(getattr(point, p90_attr))
            errors.append(p50 - actual_value)
            covered.append(p10 <= actual_value <= p90)

    if not errors:
        return MetricScore(
            metric=metric,
            horizon_hours=horizon_hours,
            sample_count=0,
            mae=None,
            bias=None,
            p10_p90_coverage=None,
        )
    return MetricScore(
        metric=metric,
        horizon_hours=horizon_hours,
        sample_count=len(errors),
        mae=statistics.fmean(abs(value) for value in errors),
        bias=statistics.fmean(errors),
        p10_p90_coverage=sum(covered) / len(covered),
    )


def score_forecasts(
    *,
    site_uid: str,
    forecasts: list[ForecastSummary],
    history: dict[str, list[HistoryPoint]],
) -> ForecastScoreSummary:
    load_points = derive_power_series(
        history,
        ("system_load_power_w", "dc_load_power_w", "load_power_w"),
        "system_load_current_a",
        "load_voltage_v",
    )
    metric_inputs = [
        (
            "solar_power_w",
            _actual_map(history.get("solar_input_power_w", [])),
            ("solar_p10_w", "solar_p50_w", "solar_p90_w"),
        ),
        (
            "load_power_w",
            _actual_map(load_points),
            ("load_p10_w", "load_p50_w", "load_p90_w"),
        ),
        (
            "battery_soc_percent",
            _actual_map(history.get("battery_soc_percent", [])),
            ("soc_p10_percent", "soc_p50_percent", "soc_p90_percent"),
        ),
    ]
    metrics: list[MetricScore] = []
    for metric, actual, attrs in metric_inputs:
        metrics.append(_score_metric(metric, forecasts, actual, attrs))
        for horizon in (1, 6, 24, 48, 72):
            if any(len(forecast.points) >= horizon for forecast in forecasts):
                metrics.append(
                    _score_metric(
                        metric,
                        forecasts,
                        actual,
                        attrs,
                        horizon_hours=horizon,
                    )
                )
    return ForecastScoreSummary(
        site_uid=site_uid,
        generated_at=datetime.now(UTC),
        forecast_count=len(forecasts),
        metrics=metrics,
    )
