# src/powersite_autonomy/shadow_service.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from .config import Settings
from .models import SiteCalibration
from .service import AutonomyService
from .shadow_counterfactual import evaluate_shadow_plan
from .shadow_feedback import apply_model_feedback, build_scorecard, detect_change_point
from .shadow_models import (
    AutopilotScorecard,
    AutopilotTickResult,
    CounterfactualEvaluation,
    EnergyPolicy,
    ManagedLoad,
    ModelEpoch,
    ShadowAutopilotPlan,
)
from .shadow_planning import build_shadow_plan
from .shadow_storage import ShadowStorage

SHADOW_HISTORY_METRICS = (
    "solar_input_power_w",
    "charge_output_power_w",
    "system_load_power_w",
    "dc_load_power_w",
    "load_power_w",
    "battery_soc_percent",
)


class ShadowAutopilotService:
    def __init__(
        self,
        settings: Settings,
        autonomy: AutonomyService,
        storage: ShadowStorage,
    ) -> None:
        self.settings = settings
        self.autonomy = autonomy
        self.storage = storage

    def policy(self, site_uid: str) -> EnergyPolicy:
        site = self.autonomy.site_config(site_uid)
        configured = self.settings.shadow_policies.get(site_uid)
        if configured is not None:
            return configured
        emergency = max(0.0, min(15.0, site.reserve_percent - 5.0))
        return EnergyPolicy(
            minimum_reserve_percent=site.reserve_percent,
            emergency_reserve_percent=emergency,
            target_morning_soc_percent=max(40.0, site.reserve_percent),
        )

    def managed_loads(self, site_uid: str) -> list[ManagedLoad]:
        self.autonomy.site_config(site_uid)
        return list(self.settings.shadow_loads.get(site_uid, []))

    async def plan(
        self,
        site_uid: str,
        hours: int | None = None,
        *,
        persist: bool = True,
    ) -> ShadowAutopilotPlan:
        horizon = max(1, min(hours or self.settings.shadow_horizon_hours, 168))
        epoch, _ = await self._ensure_epoch(site_uid)
        inputs = await self.autonomy._forecast_inputs(site_uid, horizon)
        samples = max(60, min(self.settings.monte_carlo_samples, 180))
        plan = await asyncio.to_thread(
            build_shadow_plan,
            inputs,
            self.policy(site_uid),
            self.managed_loads(site_uid),
            samples=samples,
            model_epoch_id=epoch.epoch_id,
        )
        if persist:
            await self.storage.save_plan(plan)
        return plan

    async def tick(self, site_uid: str) -> AutopilotTickResult:
        plan = await self.plan(site_uid, persist=True)
        cutoff = datetime.now(UTC) - timedelta(hours=self.settings.shadow_evaluation_delay_hours)
        pending = await self.storage.pending_plans(site_uid, cutoff, limit=4)
        evaluations_created = 0
        adjustments_applied = 0
        for pending_plan in pending:
            evaluation, applied = await self._evaluate_plan(
                pending_plan,
                apply_feedback=True,
                persist=True,
            )
            if evaluation is not None:
                evaluations_created += 1
                adjustments_applied += int(applied)
        _, epoch_created = await self._ensure_epoch(site_uid)
        return AutopilotTickResult(
            site_uid=site_uid,
            plan=plan,
            evaluations_created=evaluations_created,
            feedback_adjustments_applied=adjustments_applied,
            model_epoch_created=epoch_created,
        )

    async def replay(self, site_uid: str, plan_id: str) -> CounterfactualEvaluation:
        self.autonomy.site_config(site_uid)
        plan = await self.storage.get_plan(plan_id)
        if plan is None or plan.site_uid != site_uid:
            raise KeyError(f"shadow plan {plan_id!r} not found for site {site_uid!r}")
        existing = await self.storage.evaluation_for_plan(plan_id)
        if existing is not None:
            return existing
        evaluation, _ = await self._evaluate_plan(plan, apply_feedback=False, persist=True)
        if evaluation is None:
            raise RuntimeError("not enough elapsed telemetry exists to replay this shadow plan")
        return evaluation

    async def scorecard(self, site_uid: str, limit: int = 200) -> AutopilotScorecard:
        self.autonomy.site_config(site_uid)
        evaluations = await self.storage.recent_evaluations(site_uid, limit)
        return await asyncio.to_thread(build_scorecard, site_uid, evaluations)

    async def _evaluate_plan(
        self,
        plan: ShadowAutopilotPlan,
        *,
        apply_feedback: bool,
        persist: bool,
    ) -> tuple[CounterfactualEvaluation | None, bool]:
        now = datetime.now(UTC)
        end = min(now, plan.generated_at + timedelta(hours=plan.horizon_hours))
        if end <= plan.generated_at + timedelta(hours=1):
            return None, False
        history = await self.autonomy.morningstar.get_history_bundle(
            plan.site_uid,
            SHADOW_HISTORY_METRICS,
            resolution="1h",
            start=plan.generated_at,
            end=end,
        )
        config = self.autonomy.site_config(plan.site_uid)
        evaluation = await asyncio.to_thread(evaluate_shadow_plan, plan, history, config)
        feedback = evaluation.feedback
        applied = False
        if apply_feedback and plan.policy.feedback_enabled:
            calibration = await self.autonomy.storage.latest_calibration(plan.site_uid)
            if calibration is not None and await self._feedback_cooldown_elapsed(plan.site_uid):
                updated = await asyncio.to_thread(
                    apply_model_feedback,
                    calibration,
                    feedback,
                    max_adjustment_fraction=(
                        self.settings.shadow_feedback_max_adjustment_fraction
                    ),
                )
                if updated is not None:
                    await self.autonomy.storage.save_calibration(updated)
                    feedback = feedback.model_copy(update={"applied_to_calibration": True})
                    evaluation = evaluation.model_copy(update={"feedback": feedback})
                    applied = True
        if persist:
            await self.storage.save_evaluation(evaluation)
            await self.storage.save_feedback(feedback)
        return evaluation, applied

    async def _feedback_cooldown_elapsed(self, site_uid: str) -> bool:
        recent = await self.storage.recent_feedback(site_uid, limit=20)
        cutoff = datetime.now(UTC) - timedelta(hours=self.settings.shadow_feedback_cooldown_hours)
        return not any(
            item.applied_to_calibration and item.generated_at >= cutoff for item in recent
        )

    async def _ensure_epoch(self, site_uid: str) -> tuple[ModelEpoch, ModelEpoch | None]:
        latest_epoch = await self.storage.latest_epoch(site_uid)
        calibration_dicts = await self.autonomy.storage.recent_calibrations(site_uid, limit=2)
        calibrations = [SiteCalibration.model_validate(item) for item in calibration_dicts]
        latest_calibration = calibrations[0] if calibrations else None
        if latest_epoch is None:
            epoch = ModelEpoch(
                site_uid=site_uid,
                reason="initial_shadow_autopilot_epoch",
                calibration_version=(
                    latest_calibration.calibration_version
                    if latest_calibration is not None
                    else None
                ),
            )
            await self.storage.save_epoch(epoch)
            return epoch, epoch

        if len(calibrations) >= 2:
            current, previous = calibrations[0], calibrations[1]
            if latest_epoch.calibration_version != current.calibration_version:
                detected = await asyncio.to_thread(
                    detect_change_point,
                    site_uid,
                    previous,
                    current,
                )
                if detected is not None:
                    await self.storage.save_epoch(detected)
                    return detected, detected
        return latest_epoch, None
