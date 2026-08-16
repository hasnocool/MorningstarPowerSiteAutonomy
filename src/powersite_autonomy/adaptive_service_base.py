# src/powersite_autonomy/adaptive_service.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from .adaptive_learning import (
    build_battery_degradation_snapshot,
    build_seasonal_overlay,
    build_uncertainty_calibration,
    build_weather_skill_summary,
    decide_model_promotion,
    detect_probabilistic_change_points,
    discover_load_events,
    evaluate_world_model_candidates,
    infer_managed_load_completion,
    score_weather_run,
    series_map,
)
from .adaptive_models import (
    AdaptiveScorecard,
    AdaptiveWorldSnapshot,
    SeasonalCalibrationOverlay,
    UncertaintyCalibration,
    WeatherForecastRun,
)
from .adaptive_storage import AdaptiveStorage
from .config import Settings
from .models import SiteCalibration
from .scoring import score_forecasts
from .service import AutonomyService, HISTORY_METRICS
from .shadow_models import ModelEpoch
from .shadow_storage import ShadowStorage


class AdaptiveWorldService:
    def __init__(
        self,
        settings: Settings,
        autonomy: AutonomyService,
        storage: AdaptiveStorage,
        shadow_storage: ShadowStorage | None = None,
    ) -> None:
        self.settings = settings
        self.autonomy = autonomy
        self.storage = storage
        self.shadow_storage = shadow_storage

    async def capture_weather_run(
        self,
        site_uid: str,
        hours: int | None = None,
    ) -> list[WeatherForecastRun]:
        config = self.autonomy.site_config(site_uid)
        horizon = max(
            1,
            min(hours or self.settings.adaptive_weather_horizon_hours, 168),
        )
        members = await self.autonomy.weather.forecast_members(
            config,
            horizon,
            models=self.settings.weather_models,
        )
        issued_at = datetime.now(UTC)
        group_id = str(uuid4())
        runs = [
            WeatherForecastRun(
                group_id=group_id,
                site_uid=site_uid,
                model=model,
                issued_at=issued_at,
                points=points,
            )
            for model, points in members.items()
            if points
        ]
        await self.storage.save_weather_runs(runs)
        return runs

    async def refresh(
        self,
        site_uid: str,
        history_days: int | None = None,
    ) -> AdaptiveWorldSnapshot:
        config = self.autonomy.site_config(site_uid)
        days = max(14, min(history_days or self.settings.adaptive_history_days, 365))
        end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)

        calibration_task = self.autonomy.storage.latest_calibration(site_uid)
        calibrations_task = self.autonomy.storage.recent_calibrations(site_uid, limit=50)
        history_task = self.autonomy.morningstar.get_history_bundle(
            site_uid,
            HISTORY_METRICS,
            resolution="1h",
            start=start,
            end=end,
        )
        weather_task = self.autonomy.weather.history(config, start.date(), end.date())
        forecasts_task = self.autonomy.storage.recent_forecast_models(site_uid, limit=100)
        previous_overlay_task = self.storage.latest_seasonal_overlay(site_uid)
        previous_battery_task = self.storage.latest_battery(site_uid)
        champion_task = self.storage.champion_model(site_uid)
        plans_task = (
            self.shadow_storage.recent_plans(site_uid, limit=100)
            if self.shadow_storage is not None
            else asyncio.sleep(0, result=[])
        )
        (
            calibration,
            calibration_dicts,
            history,
            weather_history,
            forecasts,
            previous_overlay,
            previous_battery,
            champion,
            shadow_plans,
        ) = await asyncio.gather(
            calibration_task,
            calibrations_task,
            history_task,
            weather_task,
            forecasts_task,
            previous_overlay_task,
            previous_battery_task,
            champion_task,
            plans_task,
        )
        calibrations = [SiteCalibration.model_validate(item) for item in calibration_dicts]
        base_calibration = next(
            (item for item in calibrations if "+world-" not in item.calibration_version),
            calibration,
        )
        validation_days = max(14, min(45, days // 4))
        validation_cutoff = end - timedelta(days=validation_days)
        training_history = {
            name: [point for point in points if point.timestamp < validation_cutoff]
            for name, points in history.items()
        }
        validation_history = {
            name: [point for point in points if point.timestamp >= validation_cutoff]
            for name, points in history.items()
        }
        training_weather = [
            point for point in weather_history if point.timestamp < validation_cutoff
        ]
        validation_weather = [
            point for point in weather_history if point.timestamp >= validation_cutoff
        ]

        seasonal_task = asyncio.to_thread(
            build_seasonal_overlay,
            site_uid=site_uid,
            config=config,
            calibration=base_calibration,
            history=history,
            weather_history=weather_history,
            history_days=days,
            minimum_samples_per_cell=self.settings.adaptive_minimum_samples_per_cell,
        )
        challenger_task = asyncio.to_thread(
            build_seasonal_overlay,
            site_uid=site_uid,
            config=config,
            calibration=base_calibration,
            history=training_history,
            weather_history=training_weather,
            history_days=max(1, days - validation_days),
            minimum_samples_per_cell=self.settings.adaptive_minimum_samples_per_cell,
        )
        load_events_task = asyncio.to_thread(
            discover_load_events,
            site_uid=site_uid,
            config=config,
            calibration=calibration,
            history=history,
        )
        battery_task = asyncio.to_thread(
            build_battery_degradation_snapshot,
            site_uid=site_uid,
            config=config,
            history=history,
            calibrations=calibrations,
        )
        forecast_score_task = asyncio.to_thread(
            score_forecasts,
            site_uid=site_uid,
            forecasts=forecasts,
            history=history,
        )
        managed_load_evidence_task = asyncio.to_thread(
            infer_managed_load_completion,
            site_uid=site_uid,
            plans=shadow_plans,
            history=history,
        )
        (
            seasonal,
            challenger,
            load_events,
            battery,
            forecast_score,
            managed_load_evidence,
        ) = await asyncio.gather(
            seasonal_task,
            challenger_task,
            load_events_task,
            battery_task,
            forecast_score_task,
            managed_load_evidence_task,
        )
        uncertainty = await asyncio.to_thread(
            build_uncertainty_calibration,
            site_uid,
            forecast_score,
            minimum_samples=self.settings.adaptive_minimum_samples,
        )

        await self._evaluate_weather_runs(site_uid, config, base_calibration, history)
        weather_scores = await self.storage.recent_weather_scores(site_uid, limit=2000)
        weather_skill = await asyncio.to_thread(
            build_weather_skill_summary,
            site_uid,
            weather_scores,
            minimum_samples=self.settings.adaptive_minimum_samples,
        )

        candidates = await asyncio.to_thread(
            evaluate_world_model_candidates,
            config=config,
            calibration=base_calibration,
            overlay=challenger,
            history=validation_history,
            weather_history=validation_weather,
            current_champion=champion,
        )
        promotion = await asyncio.to_thread(
            decide_model_promotion,
            site_uid=site_uid,
            candidates=candidates,
            current_champion=champion,
            promotion_margin=self.settings.adaptive_promotion_margin,
            minimum_samples=self.settings.adaptive_minimum_samples,
        )
        active_champion = promotion.champion_after
        seasonal = seasonal.model_copy(
            update={"active": active_champion == "adaptive-seasonal-v1"}
        )
        change_points = await asyncio.to_thread(
            detect_probabilistic_change_points,
            site_uid=site_uid,
            previous_overlay=previous_overlay,
            current_overlay=seasonal,
            previous_battery=previous_battery,
            current_battery=battery,
        )

        await self._activate_runtime_model(
            site_uid,
            config,
            calibration_dicts,
            seasonal,
            uncertainty,
            weather_skill,
            active_champion,
        )

        generated_at = datetime.now(UTC)
        await asyncio.gather(
            self.storage.save_weather_skill(weather_skill),
            self.storage.save_seasonal_overlay(seasonal),
            self.storage.replace_load_events(site_uid, load_events),
            self.storage.save_managed_load_evidence(managed_load_evidence),
            self.storage.save_battery(battery),
            self.storage.save_uncertainty(uncertainty),
            self.storage.save_change_points(change_points),
            self.storage.save_candidates(site_uid, generated_at, candidates),
            self.storage.save_promotion(promotion),
        )
        await self._maybe_create_shadow_epoch(site_uid, change_points, calibration)

        snapshot = AdaptiveWorldSnapshot(
            site_uid=site_uid,
            weather_skill=weather_skill,
            seasonal_overlay=seasonal,
            load_events=load_events,
            managed_load_evidence=managed_load_evidence,
            battery=battery,
            uncertainty=uncertainty,
            change_points=change_points,
            promotion=promotion,
            champion_model=active_champion,
        )
        await self.storage.save_snapshot(snapshot)
        return snapshot

    async def tick(self, site_uid: str) -> AdaptiveWorldSnapshot:
        await self.capture_weather_run(site_uid)
        return await self.refresh(site_uid)

    async def snapshot(self, site_uid: str) -> AdaptiveWorldSnapshot:
        self.autonomy.site_config(site_uid)
        value = await self.storage.latest_snapshot(site_uid)
        if value is not None:
            return value
        return await self.refresh(site_uid)

    async def scorecard(self, site_uid: str) -> AdaptiveScorecard:
        self.autonomy.site_config(site_uid)
        (
            runs,
            scores,
            skill,
            overlay,
            events,
            managed_evidence,
            battery,
            uncertainty,
            changes,
            promotions,
            champion,
        ) = await asyncio.gather(
            self.storage.recent_weather_runs(site_uid, 1000),
            self.storage.recent_weather_scores(site_uid, 5000),
            self.storage.latest_weather_skill(site_uid),
            self.storage.latest_seasonal_overlay(site_uid),
            self.storage.load_events(site_uid, 200),
            self.storage.managed_load_evidence(site_uid, 1000),
            self.storage.latest_battery(site_uid),
            self.storage.latest_uncertainty(site_uid),
            self.storage.recent_change_points(site_uid, 500),
            self.storage.recent_promotions(site_uid, 500),
            self.storage.champion_model(site_uid),
        )
        evaluated_run_ids = {item.run_id for item in scores}
        calibrated_metrics = (
            sum(
                item.sample_count >= self.settings.adaptive_minimum_samples
                for item in uncertainty.metrics
            )
            if uncertainty is not None
            else 0
        )
        return AdaptiveScorecard(
            site_uid=site_uid,
            retained_weather_runs=len(runs),
            evaluated_weather_runs=len(evaluated_run_ids),
            weather_models_ranked=len({item.model for item in skill.skills}) if skill else 0,
            seasonal_cells=len(overlay.cells) if overlay else 0,
            discovered_load_events=len(events),
            managed_load_evidence_count=len(managed_evidence),
            uncertainty_metrics_calibrated=calibrated_metrics,
            change_points_detected=sum(item.probability >= 0.95 for item in changes),
            model_promotions=sum(item.promoted for item in promotions),
            champion_model=champion,
            battery_health_percent=(battery.estimated_health_percent if battery else None),
        )

    async def restore_runtime_profile(self, site_uid: str) -> None:
        config = self.autonomy.site_config(site_uid)
        skill, uncertainty = await asyncio.gather(
            self.storage.latest_weather_skill(site_uid),
            self.storage.latest_uncertainty(site_uid),
        )
        self.autonomy.weather.set_adaptive_profile(
            config,
            weights_by_horizon=(skill.weights_by_horizon if skill is not None else {}),
            spread_scale=(uncertainty.scale_for("solar") if uncertainty is not None else 1.0),
        )

    async def _activate_runtime_model(
        self,
        site_uid: str,
        config,
        calibration_dicts: list[dict],
        overlay: SeasonalCalibrationOverlay,
        uncertainty: UncertaintyCalibration,
        weather_skill,
        champion: str,
    ) -> None:
        self.autonomy.weather.set_adaptive_profile(
            config,
            weights_by_horizon=weather_skill.weights_by_horizon,
            spread_scale=uncertainty.scale_for("solar"),
        )
        if champion != "adaptive-seasonal-v1":
            return
        calibrations = [SiteCalibration.model_validate(item) for item in calibration_dicts]
        base = next(
            (item for item in calibrations if "+world-" not in item.calibration_version),
            None,
        )
        if base is None:
            return
        local = datetime.now(UTC) + timedelta(hours=config.utc_offset_hours)
        version = f"{base.calibration_version}+world-{local.month:02d}"
        latest = calibrations[0] if calibrations else None
        if latest is not None and latest.calibration_version == version:
            return
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

    async def _evaluate_weather_runs(
        self,
        site_uid: str,
        config,
        calibration,
        history,
    ) -> None:
        cutoff = datetime.now(UTC) - timedelta(
            hours=self.settings.adaptive_weather_evaluation_delay_hours
        )
        runs = await self.storage.unevaluated_weather_runs(site_uid, cutoff, limit=100)
        if not runs:
            return
        actual_solar = series_map(history.get("solar_input_power_w", []))
        for run in runs:
            scores = await asyncio.to_thread(
                score_weather_run,
                run,
                actual_solar,
                config,
                calibration,
            )
            if not scores:
                continue
            await self.storage.save_weather_scores(scores)
            await self.storage.mark_weather_run_evaluated(run.run_id)

    async def _maybe_create_shadow_epoch(
        self,
        site_uid: str,
        change_points,
        calibration: SiteCalibration | None,
    ) -> None:
        if self.shadow_storage is None:
            return
        significant = [item for item in change_points if item.model_epoch_recommended]
        if not significant:
            return
        latest = await self.shadow_storage.latest_epoch(site_uid)
        if latest is not None and latest.started_at >= datetime.now(UTC) - timedelta(hours=12):
            return
        signals = {f"{item.parameter}_probability": item.probability for item in significant}
        signals.update(
            {
                f"{item.parameter}_standardized_shift": item.standardized_shift
                for item in significant
            }
        )
        epoch = ModelEpoch(
            site_uid=site_uid,
            reason="multiple_change_points",
            calibration_version=(calibration.calibration_version if calibration else None),
            previous_calibration_version=(latest.calibration_version if latest else None),
            signals=signals,
        )
        await self.shadow_storage.save_epoch(epoch)
