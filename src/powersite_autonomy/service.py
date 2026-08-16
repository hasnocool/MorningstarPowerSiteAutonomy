from __future__ import annotations

from datetime import UTC, datetime

from .config import Settings
from .forecast import ForecastInputs, build_forecast
from .models import ScenarioRequest, ScenarioResult, SiteConfig
from .storage import Storage
from .upstream import MorningstarClient
from .weather import WeatherClient


class AutonomyService:
    def __init__(
        self,
        settings: Settings,
        morningstar: MorningstarClient,
        weather: WeatherClient,
        storage: Storage,
    ) -> None:
        self.settings = settings
        self.morningstar = morningstar
        self.weather = weather
        self.storage = storage

    def site_config(self, site_uid: str) -> SiteConfig:
        try:
            return self.settings.sites[site_uid]
        except KeyError as exc:
            raise KeyError(f"site {site_uid!r} has no autonomy configuration") from exc

    async def forecast(self, site_uid: str, hours: int = 72, *, persist: bool = True):
        config = self.site_config(site_uid)
        state, weather = await self._load_inputs(site_uid, config, hours)
        result = build_forecast(
            ForecastInputs(site_uid=site_uid, config=config, state=state, weather=weather),
            samples=self.settings.monte_carlo_samples,
        )
        if persist:
            await self.storage.save_forecast(result)
        return result

    async def scenario(self, site_uid: str, request: ScenarioRequest) -> ScenarioResult:
        base_config = self.site_config(site_uid)
        scenario_config = base_config.model_copy(
            update={
                **({"array_watts": request.array_watts} if request.array_watts is not None else {}),
                **(
                    {"battery_capacity_wh": request.battery_capacity_wh}
                    if request.battery_capacity_wh is not None
                    else {}
                ),
                **(
                    {"reserve_percent": request.reserve_percent}
                    if request.reserve_percent is not None
                    else {}
                ),
            }
        )
        state, weather = await self._load_inputs(site_uid, base_config, request.horizon_hours)
        baseline = build_forecast(
            ForecastInputs(site_uid=site_uid, config=base_config, state=state, weather=weather),
            samples=self.settings.monte_carlo_samples,
            seed=42,
        )
        scenario = build_forecast(
            ForecastInputs(
                site_uid=site_uid,
                config=scenario_config,
                state=state,
                weather=weather,
                additional_loads=tuple(request.additional_loads),
            ),
            samples=self.settings.monte_carlo_samples,
            seed=42,
        )
        additional_energy = sum(
            item.power_w * item.duration_hours for item in request.additional_loads
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
            risk_delta=scenario.reserve_breach_probability - baseline.reserve_breach_probability,
            recommendation=recommendation,
        )
        await self.storage.save_scenario(result)
        return result

    async def _load_inputs(self, site_uid: str, config: SiteConfig, hours: int):
        import asyncio

        state, weather = await asyncio.gather(
            self.morningstar.get_site_state(site_uid),
            self.weather.forecast(config, hours),
        )
        if len(weather) < hours:
            raise RuntimeError(
                f"weather provider returned only {len(weather)} of {hours} requested hours"
            )
        return state, weather
