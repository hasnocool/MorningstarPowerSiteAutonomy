# tests/test_forecast.py
from datetime import UTC, datetime, timedelta

from powersite_autonomy.forecast import ForecastInputs, build_forecast
from powersite_autonomy.models import AdditionalLoad, SiteConfig, WeatherHour
from powersite_autonomy.upstream import SiteState


def site() -> SiteConfig:
    return SiteConfig(
        array_watts=1000,
        battery_capacity_wh=4000,
        reserve_percent=25,
        latitude=48.4,
        longitude=-123.3,
        load_watts_fallback=100,
    )


def weather(hours: int = 24) -> list[WeatherHour]:
    start = datetime(2026, 8, 16, tzinfo=UTC)
    return [
        WeatherHour(
            timestamp=start + timedelta(hours=i),
            shortwave_radiation_w_m2=700 if 7 <= i <= 18 else 0,
            cloud_cover_percent=20,
            temperature_c=22,
        )
        for i in range(hours)
    ]


def test_forecast_is_bounded_and_probabilistic() -> None:
    result = build_forecast(
        ForecastInputs(
            site_uid="sys_default",
            config=site(),
            state=SiteState(60, 120, 13.2, {"battery_soc": "measured", "load_power": "measured"}),
            weather=weather(),
        ),
        samples=120,
        seed=1,
    )
    assert len(result.points) == 24
    assert 0 <= result.reserve_breach_probability <= 1
    assert 0 <= result.unmet_load_probability <= 1
    assert all(0 <= point.soc_p10_percent <= 100 for point in result.points)
    assert result.expected_solar_wh > 0
    assert result.expected_surplus_wh >= 0


def test_additional_load_increases_risk_or_reduces_soc() -> None:
    baseline = build_forecast(
        ForecastInputs(
            site_uid="sys_default",
            config=site(),
            state=SiteState(50, 130, 13.0, {"battery_soc": "measured", "load_power": "measured"}),
            weather=weather(),
        ),
        samples=200,
        seed=7,
    )
    loaded = build_forecast(
        ForecastInputs(
            site_uid="sys_default",
            config=site(),
            state=SiteState(50, 130, 13.0, {"battery_soc": "measured", "load_power": "measured"}),
            weather=weather(),
            additional_loads=(AdditionalLoad(power_w=500, start_hour=0, duration_hours=10),),
        ),
        samples=200,
        seed=7,
    )
    assert loaded.minimum_soc_p50_percent < baseline.minimum_soc_p50_percent
    assert loaded.reserve_breach_probability >= baseline.reserve_breach_probability
