# tests/test_adaptive_storage.py
from __future__ import annotations

from powersite_autonomy.adaptive_models import (
    HorizonBucket,
    SeasonalCalibrationOverlay,
    SeasonalCell,
    UncertaintyCalibration,
    UncertaintyMetricCalibration,
    WeatherModelSkill,
    WeatherSkillSummary,
)
from powersite_autonomy.adaptive_storage import AdaptiveStorage


async def test_adaptive_storage_builds_active_forecast_context(tmp_path) -> None:
    storage = AdaptiveStorage(str(tmp_path / "autonomy.db"))
    await storage.initialize()
    skill = WeatherSkillSummary(
        site_uid="site",
        skills=[
            WeatherModelSkill(
                model="a",
                horizon_bucket=HorizonBucket.SHORT,
                sample_count=50,
                pv_mae_w=20,
                skill_score=0.9,
                weight=0.8,
            )
        ],
        weights_by_horizon={"0-12h": {"a": 0.8, "b": 0.2}},
    )
    overlay = SeasonalCalibrationOverlay(
        site_uid="site",
        history_days=120,
        active=True,
        cells=[SeasonalCell(month=7, local_hour=12, sample_count=20, pv_residual_scale=1.1)],
    )
    uncertainty = UncertaintyCalibration(
        site_uid="site",
        metrics=[
            UncertaintyMetricCalibration(
                metric="solar",
                sample_count=100,
                empirical_coverage=0.6,
                scale_multiplier=1.2,
            ),
            UncertaintyMetricCalibration(
                metric="load",
                sample_count=100,
                empirical_coverage=0.8,
                scale_multiplier=0.95,
            ),
        ],
    )
    await storage.save_weather_skill(skill)
    await storage.save_seasonal_overlay(overlay)
    await storage.save_uncertainty(uncertainty)

    context = await storage.forecast_context("site")
    assert context.weather_weights_by_horizon["0-12h"]["a"] == 0.8
    assert context.seasonal_overlay is not None and context.seasonal_overlay.active
    assert context.solar_uncertainty_scale == 1.2
    assert context.load_uncertainty_scale == 0.95
