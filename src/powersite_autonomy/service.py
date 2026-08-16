# src/powersite_autonomy/service.py
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

from .battery import build_battery_twin
from .calibration import build_calibration
from .config import Settings
from .forecast import ForecastInputs, build_forecast
from .models import (
    AuxiliaryPlanRequest,
    FlexibleLoadRequest,
    ForecastScoreSummary,
    OptimizationRequest,
    ReserveRiskFeed,
    SentinelFeedback,
    ScenarioRequest,
    ScenarioResult,
    SiteConfig,
    SiteDigitalTwin,
)
from .planning import (
    build_action_plan,
    optimize_site,
    plan_auxiliary_energy,
    scaled_site_config,
    schedule_flexible_load,
)
from .scoring import score_forecasts
from .sentinel import SentinelClient
from .storage import Storage
from .upstream import MorningstarClient
from .weather import WeatherClient

HISTORY_METRICS = (
    "solar_input_power_w",
    "system_load_power_w",
    "dc_load_power_w",
    "load_power_w",
    "system_load_current_a",
    "load_voltage_v",
    "battery_soc_percent",
    "battery_voltage_v",
    "battery_net_power_w",
    "battery_net_current_a",
    "battery_temperature_c",
)


class AutonomyService:
    def __init__(
        self,
        settings: Settings,
        morningstar: MorningstarClient,
        weather: WeatherClient,
        storage: Storage,
        sentinel: SentinelClient | None = None,
    ) -> None:
        self.settings = settings
        self.morningstar = morningstar
        self.weather = weather
        self.storage = storage
        self.sentinel = sentinel

    def site_config(self, site_uid: str) -> SiteConfig:
        try:
            return self.settings.sites[site_uid]
        except KeyError as exc:
            raise KeyError(f"site {site_uid!r} has no autonomy configuration") from exc

    async def forecast(self, site_uid: str, hours: int = 72, *, persist: bool = True):
        config = self.site_config(site_uid)
        calibration = await self.storage.latest_calibration(site_uid)
        state, weather, sentinel = await self._load_inputs(site_uid, config, hours)
        result = await asyncio.to_thread(
            build_forecast,
            ForecastInputs(
                site_uid=site_uid,
                config=config,
                state=state,
                weather=weather,
                calibration=calibration,
                sentinel_feedback=sentinel,
            ),
            samples=self.settings.monte_carlo_samples,
        )
        if persist:
            await self.storage.save_forecast(result)
        return result

    async def scenario(self, site_uid: str, request: ScenarioRequest) -> ScenarioResult:
        base_config = self.site_config(site_uid)
        scenario_config = base_config
        if request.array_watts is not None or request.battery_capacity_wh is not None:
            scenario_config = scaled_site_config(
                base_config,
                request.array_watts
                if request.array_watts is not None
                else sum(array.rated_watts for array in base_config.resolved_pv_arrays()),
                request.battery_capacity_wh
                if request.battery_capacity_wh is not None
                else base_config.battery_capacity_wh,
            )
        if request.reserve_percent is not None:
            scenario_config = scenario_config.model_copy(
                update={"reserve_percent": request.reserve_percent}
            )
        calibration = await self.storage.latest_calibration(site_uid)
        state, weather, sentinel = await self._load_inputs(
            site_uid,
            base_config,
            request.horizon_hours,
        )
        baseline_inputs = ForecastInputs(
            site_uid=site_uid,
            config=base_config,
            state=state,
            weather=weather,
            calibration=calibration,
            sentinel_feedback=sentinel,
        )
        scenario_inputs = ForecastInputs(
            site_uid=site_uid,
            config=scenario_config,
            state=state,
            weather=weather,
            calibration=calibration,
            sentinel_feedback=sentinel,
            additional_loads=tuple(request.additional_loads),
            additional_sources=tuple(request.additional_sources),
        )
        baseline, scenario = await asyncio.gather(
            asyncio.to_thread(
                build_forecast,
                baseline_inputs,
                samples=self.settings.monte_carlo_samples,
                seed=42,
            ),
            asyncio.to_thread(
                build_forecast,
                scenario_inputs,
                samples=self.settings.monte_carlo_samples,
                seed=42,
            ),
        )
        additional_energy = sum(
            item.power_w * item.duration_hours for item in request.additional_loads
        )
        additional_source_energy = sum(
            item.power_w * item.duration_hours for item in request.additional_sources
        )
        risk = scenario.reserve_breach_probability
        recommendation = (
            "low_risk" if risk < 0.20 else "elevated_risk" if risk < 0.60 else "high_risk"
        )
        result = ScenarioResult(
            site_uid=site_uid,
            generated_at=datetime.now(UTC),
            baseline=baseline,
            scenario=scenario,
            additional_energy_wh=additional_energy,
            additional_source_energy_wh=additional_source_energy,
            risk_delta=scenario.reserve_breach_probability - baseline.reserve_breach_probability,
            recommendation=recommendation,
        )
        await self.storage.save_scenario(result)
        return result

    async def refresh_calibration(self, site_uid: str, history_days: int | None = None):
        config = self.site_config(site_uid)
        days = max(3, min(history_days or self.settings.calibration_history_days, 365))
        end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=days)
        history_task = self.morningstar.get_history_bundle(
            site_uid,
            HISTORY_METRICS,
            resolution="1h",
            start=start,
            end=end,
        )
        weather_task = self.weather.history(config, start.date(), end.date())
        history, weather_history = await asyncio.gather(history_task, weather_task)
        calibration = await asyncio.to_thread(
            build_calibration,
            site_uid=site_uid,
            config=config,
            history=history,
            weather_history=weather_history,
            history_days=days,
        )
        await self.storage.save_calibration(calibration)
        return calibration

    async def schedule_load(self, site_uid: str, request: FlexibleLoadRequest):
        inputs = await self._forecast_inputs(site_uid, request.horizon_hours)
        return await asyncio.to_thread(
            schedule_flexible_load,
            inputs,
            request,
            samples=max(60, min(self.settings.monte_carlo_samples, 180)),
        )

    async def optimize(self, site_uid: str, request: OptimizationRequest):
        inputs = await self._forecast_inputs(site_uid, request.horizon_hours)
        return await asyncio.to_thread(
            optimize_site,
            inputs,
            request,
            samples=max(60, min(self.settings.monte_carlo_samples, 160)),
        )

    async def auxiliary_plan(self, site_uid: str, request: AuxiliaryPlanRequest):
        inputs = await self._forecast_inputs(site_uid, request.horizon_hours)
        return await asyncio.to_thread(
            plan_auxiliary_energy,
            inputs,
            request,
            samples=max(60, min(self.settings.monte_carlo_samples, 180)),
        )

    async def digital_twin(self, site_uid: str) -> SiteDigitalTwin:
        config = self.site_config(site_uid)
        calibration_task = self.storage.latest_calibration(site_uid)
        state_task = self.morningstar.get_site_state(site_uid)
        graph_task = self.morningstar.get_component_graph(site_uid)
        ledger_task = self.morningstar.get_energy_ledger(site_uid)
        calibration, state, graph, ledger = await asyncio.gather(
            calibration_task,
            state_task,
            graph_task,
            ledger_task,
        )
        battery = build_battery_twin(config, state, calibration)
        return SiteDigitalTwin(
            site_uid=site_uid,
            generated_at=datetime.now(UTC),
            battery=battery,
            pv_arrays=config.resolved_pv_arrays(),
            component_graph=graph,
            energy_ledger=ledger,
            calibration=calibration,
            input_quality=dict(state.input_quality),
        )

    async def score(self, site_uid: str, limit: int = 20) -> ForecastScoreSummary:
        forecasts = await self.storage.recent_forecast_models(site_uid, limit)
        now = datetime.now(UTC)
        history = await self.morningstar.get_history_bundle(
            site_uid,
            HISTORY_METRICS,
            resolution="1h",
            start=now - timedelta(days=30),
            end=now,
        )
        score = await asyncio.to_thread(
            score_forecasts,
            site_uid=site_uid,
            forecasts=forecasts,
            history=history,
        )
        await self.storage.save_forecast_score(score)
        return score

    async def action_plan(self, site_uid: str, hours: int = 72):
        forecast = await self.forecast(site_uid, hours, persist=False)
        return build_action_plan(forecast)

    async def risk_feed(self, site_uid: str, hours: int = 72) -> ReserveRiskFeed:
        forecast = await self.forecast(site_uid, hours, persist=False)
        payload = {
            "site_uid": forecast.site_uid,
            "generated_at": forecast.generated_at.isoformat(),
            "horizon_hours": forecast.horizon_hours,
            "reserve_breach_probability": forecast.reserve_breach_probability,
            "first_reserve_breach_at": (
                forecast.first_reserve_breach_at.isoformat()
                if forecast.first_reserve_breach_at is not None
                else None
            ),
            "minimum_soc_p10_percent": forecast.minimum_soc_p10_percent,
            "minimum_soc_p50_percent": forecast.minimum_soc_p50_percent,
            "confidence": forecast.confidence,
            "forecast_model_version": forecast.model_version,
            "calibration_version": forecast.calibration_version,
        }
        signature = None
        if self.settings.risk_feed_secret:
            canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            signature = hmac.new(
                self.settings.risk_feed_secret.encode(),
                canonical,
                hashlib.sha256,
            ).hexdigest()
        return ReserveRiskFeed(
            **payload,
            signature=signature,
        )

    async def _forecast_inputs(self, site_uid: str, hours: int) -> ForecastInputs:
        config = self.site_config(site_uid)
        calibration = await self.storage.latest_calibration(site_uid)
        state, weather, sentinel = await self._load_inputs(site_uid, config, hours)
        return ForecastInputs(
            site_uid=site_uid,
            config=config,
            state=state,
            weather=weather,
            calibration=calibration,
            sentinel_feedback=sentinel,
        )

    async def _load_inputs(self, site_uid: str, config: SiteConfig, hours: int):
        state_task = self.morningstar.get_site_state(site_uid)
        weather_task = self.weather.forecast(
            config,
            hours,
            models=self.settings.weather_models,
        )
        if self.sentinel is not None:
            sentinel_task = self.sentinel.get_feedback(site_uid)
        else:
            sentinel_task = asyncio.sleep(0, result=SentinelFeedback(reachable=False))
        state, weather, sentinel = await asyncio.gather(
            state_task,
            weather_task,
            sentinel_task,
        )
        if len(weather) < hours:
            raise RuntimeError(
                f"weather provider returned only {len(weather)} of {hours} requested hours"
            )
        return state, weather, sentinel
