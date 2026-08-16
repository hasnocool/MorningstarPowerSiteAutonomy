# tests/test_planning.py
from datetime import UTC, datetime, timedelta

from powersite_autonomy.forecast import ForecastInputs
from powersite_autonomy.models import (
    AuxiliaryPlanRequest,
    FlexibleLoadRequest,
    OptimizationRequest,
    SiteConfig,
    WeatherHour,
)
from powersite_autonomy.planning import optimize_site, plan_auxiliary_energy, schedule_flexible_load
from powersite_autonomy.upstream import SiteState


def _weather(hours: int, radiation: float = 750) -> list[WeatherHour]:
    start = datetime(2026, 8, 16, tzinfo=UTC)
    return [
        WeatherHour(
            timestamp=start + timedelta(hours=index),
            shortwave_radiation_w_m2=radiation if 7 <= index % 24 <= 18 else 0,
            cloud_cover_percent=20,
            temperature_c=20,
        )
        for index in range(hours)
    ]


def _inputs(hours: int = 24, *, soc: float = 70, load: float = 100, radiation: float = 750):
    config = SiteConfig(
        array_watts=1200,
        battery_capacity_wh=5000,
        reserve_percent=25,
        latitude=48.4,
        longitude=-123.3,
    )
    state = SiteState(soc, load, 13.1, {"battery_soc": "measured", "load_power": "measured"})
    return ForecastInputs(
        site_uid="sys_default",
        config=config,
        state=state,
        weather=_weather(hours, radiation),
    )


def test_scheduler_finds_a_valid_window() -> None:
    result = schedule_flexible_load(
        _inputs(),
        FlexibleLoadRequest(
            horizon_hours=24,
            energy_required_wh=300,
            max_power_w=100,
            earliest_start_hour=0,
            deadline_hour=24,
        ),
        samples=60,
    )
    assert result.scheduled_energy_wh == 300
    assert result.segments
    assert result.candidate_count > 1


def test_optimizer_returns_ranked_candidates() -> None:
    result = optimize_site(
        _inputs(),
        OptimizationRequest(
            horizon_hours=24,
            array_watts_min=800,
            array_watts_max=1400,
            array_watts_step=300,
            battery_capacity_wh_min=3000,
            battery_capacity_wh_max=6000,
            battery_capacity_wh_step=1500,
            max_candidates=20,
        ),
        samples=50,
    )
    assert result.evaluated_candidates > 0
    assert result.candidates


def test_auxiliary_plan_is_read_only_and_quantified() -> None:
    inputs = _inputs(soc=28, load=240, radiation=80)
    result = plan_auxiliary_energy(
        inputs,
        AuxiliaryPlanRequest(
            horizon_hours=24,
            target_reserve_breach_probability=0.10,
            source_power_w=500,
            max_energy_wh=2500,
            earliest_start_hour=0,
            latest_end_hour=24,
        ),
        samples=80,
    )
    assert result.operator_action_required is True
    assert result.executable is False
    assert result.required_energy_wh >= 0
