# src/powersite_autonomy/adaptive_weather_learning.py
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import UTC, datetime

from .adaptive_models import (
    HorizonBucket,
    WeatherForecastRun,
    WeatherModelSkill,
    WeatherRunScore,
    WeatherSkillSummary,
)
from .models import HistoryPoint, SiteCalibration, SiteConfig
from .pv import estimate_site_pv_power_w


def hour_key(timestamp: datetime) -> datetime:
    value = timestamp.astimezone(UTC)
    return value.replace(minute=0, second=0, microsecond=0)


def series_map(points: list[HistoryPoint]) -> dict[datetime, float]:
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for point in points:
        buckets[hour_key(point.timestamp)].append(point.value)
    return {key: statistics.fmean(values) for key, values in buckets.items()}


def horizon_bucket(index: int) -> HorizonBucket:
    if index < 12:
        return HorizonBucket.SHORT
    if index < 36:
        return HorizonBucket.MEDIUM
    if index < 72:
        return HorizonBucket.LONG
    return HorizonBucket.EXTENDED


def score_weather_run(
    run: WeatherForecastRun,
    actual_solar: dict[datetime, float],
    config: SiteConfig,
    calibration: SiteCalibration | None,
) -> list[WeatherRunScore]:
    errors: dict[HorizonBucket, list[float]] = defaultdict(list)
    actuals: dict[HorizonBucket, list[float]] = defaultdict(list)
    for index, point in enumerate(run.points):
        actual = actual_solar.get(hour_key(point.timestamp))
        if actual is None:
            continue
        predicted = estimate_site_pv_power_w(point, config, calibration)
        bucket = horizon_bucket(index)
        errors[bucket].append(predicted - max(0.0, actual))
        actuals[bucket].append(max(0.0, actual))

    scores: list[WeatherRunScore] = []
    for bucket in HorizonBucket:
        bucket_errors = errors.get(bucket, [])
        if not bucket_errors:
            continue
        mae = statistics.fmean(abs(value) for value in bucket_errors)
        bias = statistics.fmean(bucket_errors)
        scale = max(50.0, statistics.fmean(actuals[bucket]))
        scores.append(
            WeatherRunScore(
                run_id=run.run_id,
                site_uid=run.site_uid,
                model=run.model,
                horizon_bucket=bucket,
                sample_count=len(bucket_errors),
                pv_mae_w=mae,
                pv_bias_w=bias,
                normalized_error=mae / scale,
            )
        )
    return scores


def build_weather_skill_summary(
    site_uid: str,
    scores: list[WeatherRunScore],
    *,
    minimum_samples: int = 24,
) -> WeatherSkillSummary:
    grouped: dict[tuple[str, HorizonBucket], list[WeatherRunScore]] = defaultdict(list)
    for score in scores:
        grouped[(score.model, score.horizon_bucket)].append(score)

    skills: list[WeatherModelSkill] = []
    raw_by_bucket: dict[HorizonBucket, dict[str, float]] = defaultdict(dict)
    for (model, bucket), group in grouped.items():
        sample_count = sum(item.sample_count for item in group)
        weighted_mae = sum((item.pv_mae_w or 0.0) * item.sample_count for item in group)
        weighted_bias = sum((item.pv_bias_w or 0.0) * item.sample_count for item in group)
        weighted_error = sum((item.normalized_error or 1.0) * item.sample_count for item in group)
        denominator = max(1, sample_count)
        mae = weighted_mae / denominator
        bias = weighted_bias / denominator
        normalized_error = weighted_error / denominator
        skill = 1.0 / (1.0 + normalized_error)
        evidence_fraction = min(1.0, sample_count / max(1, minimum_samples))
        raw_weight = 0.15 + skill * evidence_fraction
        raw_by_bucket[bucket][model] = raw_weight
        skills.append(
            WeatherModelSkill(
                model=model,
                horizon_bucket=bucket,
                sample_count=sample_count,
                pv_mae_w=mae,
                pv_bias_w=bias,
                skill_score=skill,
            )
        )

    weights_by_horizon: dict[str, dict[str, float]] = {}
    for bucket, raw_weights in raw_by_bucket.items():
        total = sum(raw_weights.values()) or 1.0
        normalized = {model: weight / total for model, weight in raw_weights.items()}
        weights_by_horizon[bucket.value] = normalized
        for skill in skills:
            if skill.horizon_bucket == bucket:
                skill.weight = normalized.get(skill.model, 0.0)

    return WeatherSkillSummary(
        site_uid=site_uid,
        skills=sorted(skills, key=lambda item: (item.horizon_bucket.value, -item.weight)),
        weights_by_horizon=weights_by_horizon,
    )
