# tests/test_calibration.py
from datetime import UTC, datetime, timedelta

from powersite_autonomy.calibration import build_calibration
from powersite_autonomy.models import HistoryPoint, SiteConfig, WeatherHour
from powersite_autonomy.pv import estimate_site_pv_power_w


def test_calibration_learns_load_profile_and_pv_scale() -> None:
    config = SiteConfig(
        array_watts=1000,
        battery_capacity_wh=4000,
        latitude=48.4,
        longitude=-123.3,
        utc_offset_hours=-7,
        load_watts_fallback=90,
    )
    start = datetime(2026, 7, 1, tzinfo=UTC)
    weather: list[WeatherHour] = []
    load: list[HistoryPoint] = []
    solar: list[HistoryPoint] = []
    for index in range(24 * 7):
        timestamp = start + timedelta(hours=index)
        local_hour = int((timestamp.hour - 7) % 24)
        item = WeatherHour(
            timestamp=timestamp,
            shortwave_radiation_w_m2=700 if 7 <= local_hour <= 18 else 0,
            cloud_cover_percent=15,
            temperature_c=22,
        )
        weather.append(item)
        load_w = 80 + (120 if 17 <= local_hour <= 21 else 0)
        load.append(HistoryPoint(timestamp=timestamp, value=load_w))
        expected = estimate_site_pv_power_w(item, config)
        solar.append(HistoryPoint(timestamp=timestamp, value=expected * 0.82))

    calibration = build_calibration(
        site_uid="sys_default",
        config=config,
        history={"system_load_power_w": load, "solar_input_power_w": solar},
        weather_history=weather,
        history_days=7,
    )

    assert calibration.hourly_load_profile_w[18] > calibration.hourly_load_profile_w[3]
    assert 0.75 <= calibration.pv_scale_factor <= 0.9
    assert calibration.sample_counts["pv_calibration_pairs"] > 0
    assert calibration.recurring_load_signatures
