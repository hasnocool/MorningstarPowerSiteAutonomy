from powersite_autonomy.config import load_settings


def test_policy_lab_settings_parse(tmp_path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        """
[policy_lab]
enabled = true
history_limit = 300
minimum_replays = 18
max_candidates = 9
promotion_margin = 0.12
bootstrap_samples = 250
dynamic_reserve_max_percent = 55
reserve_min_percent = 12
reserve_max_percent = 58
morning_soc_min_percent = 30
morning_soc_max_percent = 75

[sites.sys_default]
array_watts = 910
battery_capacity_wh = 4000
reserve_percent = 25
latitude = 48.4
longitude = -123.3
"""
    )
    settings = load_settings(config)
    assert settings.policy_lab_enabled is True
    assert settings.policy_lab_history_limit == 300
    assert settings.policy_lab_minimum_replays == 18
    assert settings.policy_lab_max_candidates == 9
    assert settings.policy_lab_promotion_margin == 0.12
    assert settings.policy_lab_bootstrap_samples == 250
    assert settings.policy_lab_dynamic_reserve_max_percent == 55
    assert settings.policy_lab_reserve_min_percent == 12
    assert settings.policy_lab_reserve_max_percent == 58
    assert settings.policy_lab_morning_soc_min_percent == 30
    assert settings.policy_lab_morning_soc_max_percent == 75
