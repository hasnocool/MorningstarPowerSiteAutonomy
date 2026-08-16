# src/powersite_autonomy/adaptive_service.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from .adaptive_models import SeasonalCalibrationOverlay, UncertaintyCalibration, WeatherSkillSummary
from .adaptive_service_base import AdaptiveWorldService as _AdaptiveWorldService
from .models import SiteCalibration, SiteConfig


class AdaptiveWorldService(_AdaptiveWorldService):
    """Adaptive service with reversible champion activation."""

    async def _activate_runtime_model(
        self,
        site_uid: str,
        config: SiteConfig,
        calibration_dicts: list[dict],
        overlay: SeasonalCalibrationOverlay,
        uncertainty: UncertaintyCalibration,
        weather_skill: WeatherSkillSummary,
        champion: str,
    ) -> None:
        self.autonomy.weather.set_adaptive_profile(
            config,
            weights_by_horizon=weather_skill.weights_by_horizon,
            spread_scale=uncertainty.scale_for("solar"),
        )
        calibrations = [SiteCalibration.model_validate(item) for item in calibration_dicts]
        base = next(
            (item for item in calibrations if "+world-" not in item.calibration_version),
            None,
        )
        if base is None:
            return
        latest = calibrations[0] if calibrations else None
        if champion != "adaptive-seasonal-v1":
            restore_version = f"{base.calibration_version}+world-baseline"
            if latest is not None and latest.calibration_version == restore_version:
                return
            if latest is not None and "+world-" in latest.calibration_version:
                restored = base.model_copy(
                    update={
                        "generated_at": datetime.now(UTC),
                        "calibration_version": restore_version,
                        "notes": [
                            *base.notes,
                            "Adaptive World Model restored the baseline champion calibration.",
                        ],
                    }
                )
                await self.autonomy.storage.save_calibration(restored)
            return

        local = datetime.now(UTC) + timedelta(hours=config.utc_offset_hours)
        version = (
            f"{base.calibration_version}+world-"
            f"{overlay.generated_at.astimezone(UTC).strftime('%Y%m%dT%H%MZ')}"
        )
        pv_scale_by_hour = list(base.pv_scale_by_hour)
        load_profile = list(base.hourly_load_profile_w)
        load_sigma = list(base.hourly_load_sigma_w)
        load_uncertainty = uncertainty.scale_for("load")
        for hour in range(24):
            cell = overlay.cell(local.month, hour)
            if cell is None or cell.sample_count < overlay.minimum_samples_per_cell:
                load_sigma[hour] *= load_uncertainty
                continue
            pv_scale_by_hour[hour] = max(
                0.3,
                min(2.0, base.pv_scale_by_hour[hour] * cell.pv_residual_scale),
            )
            if cell.load_mean_w is not None:
                load_profile[hour] = cell.load_mean_w
            if cell.load_sigma_w is not None:
                load_sigma[hour] = max(8.0, cell.load_sigma_w * load_uncertainty)
        applied = base.model_copy(
            update={
                "generated_at": datetime.now(UTC),
                "calibration_version": version,
                "pv_scale_by_hour": pv_scale_by_hour,
                "hourly_load_profile_w": load_profile,
                "hourly_load_sigma_w": load_sigma,
                "notes": [
                    *base.notes,
                    (
                        "Adaptive World Model champion applied current-month seasonal residuals "
                        "and empirical load uncertainty."
                    ),
                ],
            }
        )
        await self.autonomy.storage.save_calibration(applied)
