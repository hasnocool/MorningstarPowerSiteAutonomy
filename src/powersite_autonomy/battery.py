# src/powersite_autonomy/battery.py
from __future__ import annotations

from typing import Protocol

from .models import BatteryChemistry, BatteryTwinSnapshot, SiteCalibration, SiteConfig


class BatteryStateLike(Protocol):
    soc_percent: float | None
    battery_temperature_c: float | None
    input_quality: dict[str, str]


def _temperature_capacity_factor(chemistry: BatteryChemistry, temperature_c: float | None) -> float:
    if temperature_c is None:
        return 1.0
    if chemistry == BatteryChemistry.LIFEPO4:
        if temperature_c <= -10:
            return 0.72
        if temperature_c < 0:
            return 0.82
        if temperature_c < 10:
            return 0.92
        if temperature_c > 50:
            return 0.88
        if temperature_c > 40:
            return 0.95
        return 1.0
    if chemistry in {BatteryChemistry.LEAD_ACID, BatteryChemistry.AGM, BatteryChemistry.GEL}:
        if temperature_c <= -20:
            return 0.55
        if temperature_c <= -10:
            return 0.68
        if temperature_c < 0:
            return 0.80
        if temperature_c < 10:
            return 0.90
        if temperature_c > 45:
            return 0.92
        return 1.0
    if temperature_c < 0:
        return 0.85
    if temperature_c > 45:
        return 0.92
    return 1.0


def build_battery_twin(
    config: SiteConfig,
    state: BatteryStateLike,
    calibration: SiteCalibration | None = None,
) -> BatteryTwinSnapshot:
    temperature_c = (
        state.battery_temperature_c
        if state.battery_temperature_c is not None
        else config.battery_temperature_c_fallback
    )
    temperature_factor = _temperature_capacity_factor(config.battery_chemistry, temperature_c)
    configured_usable = config.battery_capacity_wh * config.battery_usable_capacity_percent / 100
    configured_healthy = configured_usable * config.battery_health_percent / 100
    calibrated = (
        calibration.estimated_usable_battery_capacity_wh
        if calibration is not None
        else None
    )
    base_effective = calibrated if calibrated is not None else configured_healthy
    effective = max(1.0, min(config.battery_capacity_wh * 1.2, base_effective * temperature_factor))

    soc = (
        state.soc_percent
        if state.soc_percent is not None
        else config.initial_soc_fallback_percent
    )
    soc_quality = state.input_quality.get("battery_soc", "fallback")
    if soc_quality == "measured" and calibrated is not None:
        confidence = "high"
    elif soc_quality != "fallback" or calibrated is not None:
        confidence = "medium"
    else:
        confidence = "low"

    health_percent = 100 * base_effective / max(1.0, configured_usable)
    return BatteryTwinSnapshot(
        chemistry=config.battery_chemistry,
        nominal_capacity_wh=config.battery_capacity_wh,
        effective_capacity_wh=effective,
        configured_usable_capacity_percent=config.battery_usable_capacity_percent,
        estimated_health_percent=max(0.0, min(120.0, health_percent)),
        temperature_c=temperature_c,
        temperature_capacity_factor=temperature_factor,
        max_charge_power_w=config.max_charge_power_w,
        max_discharge_power_w=config.max_discharge_power_w,
        estimated_internal_resistance_ohm=(
            calibration.estimated_internal_resistance_ohm if calibration is not None else None
        ),
        soc_percent=max(0.0, min(100.0, soc)),
        soc_confidence=confidence,
    )
