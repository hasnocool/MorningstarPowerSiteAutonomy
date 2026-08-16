# tests/test_adaptive_config.py
from __future__ import annotations

from powersite_autonomy.config import load_settings


def test_adaptive_world_settings_load_from_toml(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[adaptive_world]
enabled = true
interval_seconds = 3600
history_days = 180
weather_horizon_hours = 72
weather_evaluation_delay_hours = 84
minimum_samples = 60
minimum_samples_per_cell = 5
promotion_margin = 0.10

[sites.site]
array_watts = 1000
battery_capacity_wh = 4000
latitude = 48.3
longitude = -123.7
"""
    )
    settings = load_settings(config)
    assert settings.adaptive_world_enabled is True
    assert settings.adaptive_interval_seconds == 3600
    assert settings.adaptive_history_days == 180
    assert settings.adaptive_minimum_samples == 60
    assert settings.adaptive_minimum_samples_per_cell == 5
    assert settings.adaptive_promotion_margin == 0.10
