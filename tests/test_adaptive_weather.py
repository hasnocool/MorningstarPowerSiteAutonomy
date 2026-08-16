# tests/test_adaptive_weather.py
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from powersite_autonomy.models import WeatherHour
from powersite_autonomy.weather import _combine_ensemble


def test_weighted_ensemble_prefers_locally_skilled_model() -> None:
    timestamp = datetime(2026, 8, 16, 18, tzinfo=UTC)
    series = {
        "good": [
            WeatherHour(
                timestamp=timestamp,
                shortwave_radiation_w_m2=300,
                cloud_cover_percent=10,
                temperature_c=20,
            )
        ],
        "weak": [
            WeatherHour(
                timestamp=timestamp,
                shortwave_radiation_w_m2=100,
                cloud_cover_percent=80,
                temperature_c=16,
            )
        ],
    }
    result = _combine_ensemble(
        series,
        1,
        weights_by_horizon={"0-12h": {"good": 0.9, "weak": 0.1}},
    )
    assert result[0].shortwave_radiation_w_m2 == pytest.approx(280)
    assert result[0].cloud_cover_percent == pytest.approx(17)
    assert result[0].shortwave_radiation_spread_w_m2 is not None
