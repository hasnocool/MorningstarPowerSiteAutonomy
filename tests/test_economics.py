# tests/test_economics.py
from __future__ import annotations

from powersite_autonomy.economics import (
    HardwareUpgrade,
    SiteEconomics,
    evaluate_upgrade,
    rank_upgrades,
    replacement_timing,
)
from powersite_autonomy.fleet import HardwarePerformanceSummary


def _site() -> SiteEconomics:
    return SiteEconomics(
        average_load_w=120,
        current_array_w=1200,
        current_battery_wh=4000,
        annual_auxiliary_energy_wh=500_000,
        auxiliary_energy_cost_per_kwh=0.65,
        unserved_energy_value_per_kwh=2.0,
        analysis_years=10,
    )


def test_battery_upgrade_exposes_cost_per_added_autonomy() -> None:
    result = evaluate_upgrade(
        _site(),
        HardwareUpgrade(
            upgrade_id="battery-2kwh",
            name="2 kWh battery expansion",
            category="battery",
            capex=900,
            added_battery_wh=2000,
            annual_degradation_rate=0.02,
            expected_lifetime_years=10,
        ),
    )
    assert result.added_autonomy_hours > 16
    assert result.cost_per_added_autonomy_hour is not None
    assert result.replacement_year == 10


def test_fleet_evidence_adjusts_hardware_efficiency() -> None:
    fleet = [
        HardwarePerformanceSummary(
            hardware_key="controller-x",
            metric="conversion_efficiency",
            unit="ratio",
            sample_count=20,
            site_count=5,
            p10=0.90,
            p50=0.94,
            p90=0.97,
            mean=0.94,
        )
    ]
    result = evaluate_upgrade(
        _site(),
        HardwareUpgrade(
            upgrade_id="pv",
            name="PV expansion",
            category="pv",
            hardware_key="controller-x",
            capex=500,
            added_array_w=500,
            nominal_efficiency=0.99,
        ),
        fleet,
    )
    assert result.expected_efficiency == 0.94
    assert result.effective_added_array_w == 470


def test_rank_upgrades_prefers_higher_value_candidate() -> None:
    upgrades = [
        HardwareUpgrade(
            upgrade_id="small",
            name="Small battery",
            category="battery",
            capex=1000,
            added_battery_wh=500,
        ),
        HardwareUpgrade(
            upgrade_id="large",
            name="Large battery",
            category="battery",
            capex=900,
            added_battery_wh=2500,
        ),
    ]
    ranked = rank_upgrades(_site(), upgrades)
    assert ranked[0].upgrade_id == "large"


def test_replacement_timing_flags_expired_hardware() -> None:
    decision = replacement_timing(
        hardware_key="battery-a",
        current_age_years=8.2,
        expected_lifetime_years=8,
        current_annual_maintenance_cost=80,
        replacement_capex=1200,
        replacement_lifetime_years=10,
        annual_failure_risk=0.2,
        failure_cost=1000,
    )
    assert decision.recommended_action == "replace"
    assert decision.replacement_window_years == 0
