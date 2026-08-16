# src/powersite_autonomy/economics.py
from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from .fleet import HardwarePerformanceSummary


class SiteEconomics(BaseModel):
    average_load_w: float = Field(gt=0)
    current_array_w: float = Field(ge=0)
    current_battery_wh: float = Field(gt=0)
    annual_auxiliary_energy_wh: float = Field(ge=0, default=0)
    auxiliary_energy_cost_per_kwh: float = Field(ge=0, default=0)
    unserved_energy_value_per_kwh: float = Field(ge=0, default=0)
    discount_rate: float = Field(ge=0, le=1, default=0.06)
    analysis_years: int = Field(ge=1, le=30, default=10)


class HardwareUpgrade(BaseModel):
    upgrade_id: str
    name: str
    category: Literal["pv", "battery", "controller", "inverter", "generator", "mixed"]
    hardware_key: str | None = None
    capex: float = Field(ge=0)
    added_array_w: float = Field(ge=0, default=0)
    added_battery_wh: float = Field(ge=0, default=0)
    nominal_efficiency: float = Field(gt=0, le=1.2, default=1.0)
    annual_degradation_rate: float = Field(ge=0, le=1, default=0.0)
    expected_lifetime_years: float = Field(gt=0, default=10)
    annual_maintenance_cost: float = Field(ge=0, default=0)
    replacement_cost: float | None = Field(default=None, ge=0)


class UpgradeEvaluation(BaseModel):
    upgrade_id: str
    name: str
    expected_efficiency: float
    effective_added_array_w: float
    effective_added_battery_wh: float
    added_autonomy_hours: float
    cost_per_added_autonomy_hour: float | None
    annual_avoided_auxiliary_wh: float
    annual_expected_value: float
    annualized_degradation_cost: float
    net_annual_value: float
    simple_payback_years: float | None
    discounted_roi: float
    replacement_year: float
    score: float
    recommendation: Literal["strong", "positive", "marginal", "defer"]


class ReplacementDecision(BaseModel):
    hardware_key: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    current_age_years: float
    estimated_remaining_life_years: float
    annual_keep_cost: float
    annual_replace_cost: float
    recommended_action: Literal["keep", "plan_replacement", "replace"]
    replacement_window_years: float


def _fleet_metric(
    summaries: list[HardwarePerformanceSummary],
    hardware_key: str | None,
    metric: str,
) -> HardwarePerformanceSummary | None:
    if hardware_key is None:
        return None
    return next(
        (
            item
            for item in summaries
            if item.hardware_key == hardware_key and item.metric == metric
        ),
        None,
    )


def _discount_factor(rate: float, years: int) -> float:
    if rate == 0:
        return float(years)
    return sum(1 / ((1 + rate) ** year) for year in range(1, years + 1))


def evaluate_upgrade(
    site: SiteEconomics,
    upgrade: HardwareUpgrade,
    fleet: list[HardwarePerformanceSummary] | None = None,
) -> UpgradeEvaluation:
    fleet = fleet or []
    efficiency_summary = _fleet_metric(fleet, upgrade.hardware_key, "conversion_efficiency")
    degradation_summary = _fleet_metric(fleet, upgrade.hardware_key, "annual_degradation_rate")
    lifetime_summary = _fleet_metric(fleet, upgrade.hardware_key, "lifetime_years")

    expected_efficiency = (
        efficiency_summary.p50 if efficiency_summary is not None else upgrade.nominal_efficiency
    )
    expected_efficiency = max(0.01, min(expected_efficiency, 1.2))
    degradation_rate = (
        degradation_summary.p50
        if degradation_summary is not None
        else upgrade.annual_degradation_rate
    )
    expected_lifetime = (
        lifetime_summary.p50
        if lifetime_summary is not None
        else upgrade.expected_lifetime_years
    )
    expected_lifetime = max(0.25, expected_lifetime)

    effective_pv = upgrade.added_array_w * expected_efficiency
    effective_battery = upgrade.added_battery_wh * expected_efficiency
    added_autonomy_hours = effective_battery / site.average_load_w

    # Approximate annual solar contribution with a conservative 3 peak-sun-hour/day prior.
    # The surrounding forecast/sizing engine can provide better site-specific candidate values.
    annual_added_pv_wh = effective_pv * 3.0 * 365.0
    annual_storage_value_wh = effective_battery * 120.0
    gross_energy_value_wh = annual_added_pv_wh + annual_storage_value_wh
    avoidable_auxiliary_wh = min(site.annual_auxiliary_energy_wh, gross_energy_value_wh)

    avoided_auxiliary_value = (
        avoidable_auxiliary_wh / 1000.0 * site.auxiliary_energy_cost_per_kwh
    )
    resilience_value = (
        min(gross_energy_value_wh, site.average_load_w * 24 * 30)
        / 1000.0
        * site.unserved_energy_value_per_kwh
    )
    annual_expected_value = avoided_auxiliary_value + resilience_value

    annualized_degradation_cost = upgrade.capex * degradation_rate
    net_annual_value = max(
        0.0,
        annual_expected_value - annualized_degradation_cost - upgrade.annual_maintenance_cost,
    )
    payback = upgrade.capex / net_annual_value if net_annual_value > 0 else None

    horizon = min(site.analysis_years, max(1, math.ceil(expected_lifetime)))
    present_value = net_annual_value * _discount_factor(site.discount_rate, horizon)
    replacement_cost = (
        upgrade.replacement_cost
        if upgrade.replacement_cost is not None
        else upgrade.capex
    )
    if expected_lifetime < site.analysis_years:
        replacement_year = max(1, math.ceil(expected_lifetime))
        present_value -= replacement_cost / ((1 + site.discount_rate) ** replacement_year)
    discounted_roi = (present_value - upgrade.capex) / max(upgrade.capex, 1.0)

    cost_per_autonomy = (
        upgrade.capex / added_autonomy_hours if added_autonomy_hours > 0 else None
    )
    autonomy_component = min(2.0, added_autonomy_hours / 12.0)
    roi_component = max(-2.0, min(3.0, discounted_roi))
    payback_component = 0.0 if payback is None else max(0.0, 2.0 - payback / 5.0)
    score = roi_component + autonomy_component + payback_component

    if discounted_roi >= 0.5 and score >= 2.0:
        recommendation = "strong"
    elif discounted_roi >= 0:
        recommendation = "positive"
    elif discounted_roi >= -0.25:
        recommendation = "marginal"
    else:
        recommendation = "defer"

    return UpgradeEvaluation(
        upgrade_id=upgrade.upgrade_id,
        name=upgrade.name,
        expected_efficiency=expected_efficiency,
        effective_added_array_w=effective_pv,
        effective_added_battery_wh=effective_battery,
        added_autonomy_hours=added_autonomy_hours,
        cost_per_added_autonomy_hour=cost_per_autonomy,
        annual_avoided_auxiliary_wh=avoidable_auxiliary_wh,
        annual_expected_value=annual_expected_value,
        annualized_degradation_cost=annualized_degradation_cost,
        net_annual_value=net_annual_value,
        simple_payback_years=payback,
        discounted_roi=discounted_roi,
        replacement_year=expected_lifetime,
        score=score,
        recommendation=recommendation,
    )


def rank_upgrades(
    site: SiteEconomics,
    upgrades: list[HardwareUpgrade],
    fleet: list[HardwarePerformanceSummary] | None = None,
) -> list[UpgradeEvaluation]:
    results = [evaluate_upgrade(site, upgrade, fleet) for upgrade in upgrades]
    return sorted(
        results,
        key=lambda item: (
            -item.score,
            -(item.discounted_roi),
            item.cost_per_added_autonomy_hour
            if item.cost_per_added_autonomy_hour is not None
            else float("inf"),
        ),
    )


def replacement_timing(
    *,
    hardware_key: str,
    current_age_years: float,
    expected_lifetime_years: float,
    current_annual_maintenance_cost: float,
    replacement_capex: float,
    replacement_lifetime_years: float,
    annual_failure_risk: float = 0.0,
    failure_cost: float = 0.0,
) -> ReplacementDecision:
    remaining = max(0.0, expected_lifetime_years - current_age_years)
    annual_keep_cost = current_annual_maintenance_cost + annual_failure_risk * failure_cost
    annual_replace_cost = replacement_capex / max(replacement_lifetime_years, 0.25)

    if remaining <= 0.25 or annual_keep_cost > annual_replace_cost * 1.5:
        action = "replace"
        window = 0.0
    elif remaining <= 2.0 or annual_keep_cost > annual_replace_cost:
        action = "plan_replacement"
        window = min(remaining, 2.0)
    else:
        action = "keep"
        window = max(1.0, min(remaining - 1.0, 5.0))

    return ReplacementDecision(
        hardware_key=hardware_key,
        current_age_years=current_age_years,
        estimated_remaining_life_years=remaining,
        annual_keep_cost=annual_keep_cost,
        annual_replace_cost=annual_replace_cost,
        recommended_action=action,
        replacement_window_years=window,
    )
