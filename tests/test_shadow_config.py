# tests/test_shadow_config.py
from __future__ import annotations

from powersite_autonomy.config import load_settings


def test_shadow_policy_and_managed_loads_load_from_toml(tmp_path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        """
[sites.sys_default]
array_watts = 1000
battery_capacity_wh = 4000
reserve_percent = 25
latitude = 48.4
longitude = -123.3

[sites.sys_default.shadow_policy]
minimum_reserve_percent = 30
emergency_reserve_percent = 15
target_reserve_breach_probability = 0.03

[[sites.sys_default.shadow_loads]]
load_id = "batch"
power_w = 100
energy_required_wh = 200
earliest_start_hour = 2
deadline_hour = 10
interruptible = true
"""
    )
    settings = load_settings(path)
    assert settings.shadow_autopilot_enabled is True
    assert settings.shadow_policies["sys_default"].minimum_reserve_percent == 30
    assert settings.shadow_loads["sys_default"][0].load_id == "batch"
