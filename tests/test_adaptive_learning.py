# tests/test_adaptive_learning.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from powersite_autonomy.adaptive_learning import (
    build_seasonal_overlay,
    build_uncertainty_calibration,
    build_weather_skill_summary,
    decide_model_promotion,
    infer_managed_load_completion,
)
from powersite_autonomy.adaptive_models import (
    AdaptiveModelCandidate,
    HorizonBucket,
    WeatherRunScore,
)
from powersite_autonomy.models import (
    ForecastPoint,
    ForecastScoreSummary,
    ForecastSummary,
    HistoryPoint,
    MetricScore,
    SiteConfig,
    WeatherHour,
)
from powersite_autonomy.pv import estimate_site_pv_power_w
from powersite_autonomy.shadow_models import (
    EnergyPolicy,
    ShadowAction,
    ShadowAutopilotPlan,
)


def _config() -> SiteConfig:
    return SiteConfig(
        array_watts=1000,
        battery_capacity_wh=4000,
        latitude=48.3,
        longitude=-123.7,
        utc_offset_hours=-7,
    )


def test_weather_skill_gives_better_model_more_weight() -> None:
    scores = [
        WeatherRunScore(
            run_id="a",
            site_uid="site",
            model="model-a",
            horizon_bucket=HorizonBucket.SHORT,
            sample_count=48,
            pv_mae_w=20,
            pv_bias_w=0,
            normalized_error=0.10,
        ),
        WeatherRunScore(
            run_id="b",
            site_uid="site",
            model="model-b",
            horizon_bucket=HorizonBucket.SHORT,
            sample_count=48,
            pv_mae_w=100,
            pv_bias_w=0,
            normalized_error=0.50,
        ),
    ]
    summary = build_weather_skill_summary("site", scores, minimum_samples=24)
    weights = summary.weights_by_horizon[HorizonBucket.SHORT.value]
    assert weights["model-a"] > weights["model-b"]
    assert sum(weights.values()) == pytest.approx(1.0)


def test_uncertainty_calibration_tracks_empirical_coverage() -> None:
    score = ForecastScoreSummary(
        site_uid="site",
        generated_at=datetime.now(UTC),
        forecast_count=20,
        metrics=[
            MetricScore(
                metric="solar_power_w",
                sample_count=100,
                mae=40,
                bias=5,
                p10_p90_coverage=0.50,
            ),
            MetricScore(
                metric="load_power_w",
                sample_count=100,
                mae=20,
                bias=0,
                p10_p90_coverage=0.95,
            ),
        ],
    )
    calibration = build_uncertainty_calibration("site", score)
    assert calibration.scale_for("solar") > 1.0
    assert calibration.scale_for("load") < 1.0


def test_seasonal_overlay_learns_residual_and_load_level() -> None:
    config = _config()
    start = datetime(2026, 7, 1, 19, tzinfo=UTC)
    weather: list[WeatherHour] = []
    solar: list[HistoryPoint] = []
    load: list[HistoryPoint] = []
    for day in range(6):
        timestamp = start + timedelta(days=day)
        conditions = WeatherHour(
            timestamp=timestamp,
            shortwave_radiation_w_m2=700,
            cloud_cover_percent=10,
            temperature_c=22,
        )
        predicted = estimate_site_pv_power_w(conditions, config, None)
        weather.append(conditions)
        solar.append(HistoryPoint(timestamp=timestamp, value=predicted * 1.20))
        load.append(HistoryPoint(timestamp=timestamp, value=175 + day))

    overlay = build_seasonal_overlay(
        site_uid="site",
        config=config,
        calibration=None,
        history={"solar_input_power_w": solar, "system_load_power_w": load},
        weather_history=weather,
        history_days=30,
        minimum_samples_per_cell=4,
    )
    local_hour = int((start.hour + config.utc_offset_hours) % 24)
    cell = overlay.cell(7, local_hour)
    assert cell is not None
    assert cell.pv_residual_scale == pytest.approx(1.20, rel=0.02)
    assert cell.load_mean_w is not None and cell.load_mean_w > 175


def test_challenger_promotes_only_with_evidence_and_margin() -> None:
    candidates = [
        AdaptiveModelCandidate(
            candidate_id="baseline-v2",
            model_kind="world_model",
            model_version="forecast-v2",
            prediction_error=0.40,
            evaluation_count=100,
            status="champion",
        ),
        AdaptiveModelCandidate(
            candidate_id="adaptive-seasonal-v1",
            model_kind="world_model",
            model_version="seasonal-overlay-v1",
            prediction_error=0.10,
            evaluation_count=100,
        ),
    ]
    decision = decide_model_promotion(
        site_uid="site",
        candidates=candidates,
        current_champion="baseline-v2",
        promotion_margin=0.05,
        minimum_samples=48,
    )
    assert decision.promoted is True
    assert decision.champion_after == "adaptive-seasonal-v1"


def test_managed_load_completion_is_evidence_only() -> None:
    start = datetime(2026, 8, 1, tzinfo=UTC)
    points = [
        ForecastPoint(
            timestamp=start + timedelta(hours=index),
            solar_p10_w=0,
            solar_p50_w=0,
            solar_p90_w=0,
            load_p10_w=90,
            load_p50_w=100,
            load_p90_w=110,
            surplus_p10_w=0,
            surplus_p50_w=0,
            surplus_p90_w=0,
            soc_p10_percent=50,
            soc_p50_percent=55,
            soc_p90_percent=60,
        )
        for index in range(4)
    ]
    forecast = ForecastSummary(
        site_uid="site",
        generated_at=start,
        horizon_hours=4,
        minimum_soc_p10_percent=50,
        minimum_soc_p50_percent=55,
        minimum_soc_p90_percent=60,
        reserve_breach_probability=0,
        unmet_load_probability=0,
        first_reserve_breach_at=None,
        expected_solar_wh=0,
        expected_load_wh=400,
        expected_surplus_wh=0,
        discretionary_energy_wh=0,
        safe_discretionary_energy_wh=0,
        autonomy_hours_if_no_solar=10,
        effective_battery_capacity_wh=4000,
        confidence="high",
        input_quality={},
        points=points,
    )
    action = ShadowAction(
        created_at=start,
        expires_at=start + timedelta(hours=4),
        kind="schedule_load",
        target="batch",
        operation="schedule",
        planned_power_w=50,
        planned_energy_wh=100,
        start_hour=1,
        duration_hours=2,
        reason="test",
        policy_version="p1",
        forecast_model_version="f1",
    )
    plan = ShadowAutopilotPlan(
        site_uid="site",
        generated_at=start,
        horizon_hours=4,
        policy=EnergyPolicy(),
        baseline=forecast,
        planned=forecast,
        objective_score=0,
        selected_mode="balanced",
        alternatives=[],
        managed_loads=[],
        actions=[action],
        scheduled_load_wh=100,
        deferred_load_wh=0,
        auxiliary_energy_wh=0,
    )
    history = {
        "system_load_power_w": [
            HistoryPoint(timestamp=start + timedelta(hours=1), value=150),
            HistoryPoint(timestamp=start + timedelta(hours=2), value=150),
        ]
    }
    evidence = infer_managed_load_completion(site_uid="site", plans=[plan], history=history)
    assert len(evidence) == 1
    assert evidence[0].completion_ratio_estimate == 1.0
    assert evidence[0].confidence <= 0.70
    assert evidence[0].evidence_only is True
