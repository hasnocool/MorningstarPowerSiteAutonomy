from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import __version__
from .adaptive_api import build_adaptive_router
from .adaptive_service import AdaptiveWorldService
from .adaptive_storage import AdaptiveStorage
from .config import Settings, load_settings
from .dashboard import dashboard_html
from .evidence_api import build_evidence_router
from .evidence_service import EvidenceIntelligenceService
from .models import (
    AuxiliaryPlanRequest,
    FlexibleLoadRequest,
    OptimizationRequest,
    ScenarioRequest,
)
from .sentinel import SentinelClient
from .service import AutonomyService
from .shadow_api import build_shadow_router
from .shadow_service import ShadowAutopilotService
from .shadow_storage import ShadowStorage
from .storage import Storage
from .upstream import MorningstarClient
from .weather import WeatherClient


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    morningstar = MorningstarClient(resolved.morningstar_base_url)
    weather = WeatherClient(
        resolved.weather_base_url,
        archive_base_url=resolved.weather_archive_base_url,
    )
    sentinel = SentinelClient(resolved.sentinel_base_url) if resolved.sentinel_base_url else None
    storage = Storage(resolved.database_path)
    service = AutonomyService(resolved, morningstar, weather, storage, sentinel)
    shadow_storage = ShadowStorage(resolved.database_path)
    shadow_service = ShadowAutopilotService(resolved, service, shadow_storage)
    adaptive_storage = AdaptiveStorage(resolved.database_path)
    adaptive_service = AdaptiveWorldService(
        resolved,
        service,
        adaptive_storage,
        shadow_storage,
    )
    evidence_service = EvidenceIntelligenceService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.gather(
            storage.initialize(),
            shadow_storage.initialize(),
            adaptive_storage.initialize(),
        )
        app.state.service = service
        app.state.shadow_service = shadow_service
        app.state.adaptive_service = adaptive_service
        app.state.evidence_service = evidence_service
        if resolved.adaptive_world_enabled:
            await asyncio.gather(
                *(adaptive_service.restore_runtime_profile(uid) for uid in resolved.sites),
                return_exceptions=True,
            )
        tasks = [asyncio.create_task(_forecast_loop(service), name="autonomy-forecast-loop")]
        if resolved.auto_calibration_enabled:
            tasks.append(
                asyncio.create_task(_calibration_loop(service), name="autonomy-calibration-loop")
            )
        if resolved.shadow_autopilot_enabled:
            tasks.append(
                asyncio.create_task(
                    _shadow_autopilot_loop(shadow_service),
                    name="autonomy-shadow-autopilot-loop",
                )
            )
        if resolved.adaptive_world_enabled:
            tasks.append(
                asyncio.create_task(
                    _adaptive_world_loop(adaptive_service),
                    name="autonomy-adaptive-world-loop",
                )
            )
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            await morningstar.aclose()
            await weather.aclose()
            if sentinel is not None:
                await sentinel.aclose()

    app = FastAPI(
        title="Morningstar PowerSite Autonomy",
        version=__version__,
        description=(
            "Read-only calibrated energy forecasting, digital-twin, scheduling, planning, "
            "shadow-autopilot, adaptive-world, and evidence-intelligence service."
        ),
        lifespan=lifespan,
    )
    app.include_router(build_shadow_router(shadow_service))
    app.include_router(build_adaptive_router(adaptive_service))
    app.include_router(build_evidence_router(evidence_service))

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(dashboard_html())

    @app.get("/health")
    async def health() -> dict:
        try:
            await service.morningstar.list_sites()
            upstream = "reachable"
        except (httpx.HTTPError, ValueError):
            upstream = "unreachable"
        return {
            "status": "ok",
            "version": __version__,
            "morningstar_api": upstream,
            "sentinel_configured": service.sentinel is not None,
            "auto_calibration": resolved.auto_calibration_enabled,
            "shadow_autopilot": resolved.shadow_autopilot_enabled,
            "shadow_autopilot_executable": False,
            "adaptive_world": resolved.adaptive_world_enabled,
            "adaptive_world_executable": False,
            "evidence_intelligence": True,
            "evidence_intelligence_executable": False,
        }

    @app.get("/v1/sites")
    async def sites():
        try:
            upstream_sites = await service.morningstar.list_sites()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"Morningstar API unavailable: {exc}",
            ) from exc
        configured = set(service.settings.sites)
        return [
            {**site.model_dump(), "autonomy_configured": site.site_uid in configured}
            for site in upstream_sites
        ]

    @app.get("/v1/sites/{site_uid}/forecast")
    async def forecast(
        site_uid: str,
        hours: Annotated[int, Query(ge=1, le=168)] = 72,
    ):
        try:
            return await service.forecast(site_uid, hours)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"upstream forecast input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/forecasts")
    async def forecast_history(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        return await storage.recent_forecasts(site_uid, limit)

    @app.post("/v1/sites/{site_uid}/scenarios")
    async def scenarios(site_uid: str, request: ScenarioRequest):
        try:
            return await service.scenario(site_uid, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"upstream forecast input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/calibration")
    async def calibration(site_uid: str):
        service.site_config(site_uid)
        result = await storage.latest_calibration(site_uid)
        if result is None:
            raise HTTPException(status_code=404, detail="site has not been calibrated yet")
        return result

    @app.get("/v1/sites/{site_uid}/calibrations")
    async def calibration_history(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        service.site_config(site_uid)
        return await storage.recent_calibrations(site_uid, limit)

    @app.post("/v1/sites/{site_uid}/calibration/refresh")
    async def calibration_refresh(
        site_uid: str,
        days: Annotated[int | None, Query(ge=3, le=365)] = None,
    ):
        try:
            return await service.refresh_calibration(site_uid, days)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"calibration input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/forecast-score")
    async def forecast_score(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
    ):
        try:
            return await service.score(site_uid, limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"history input unavailable: {exc}",
            ) from exc

    @app.post("/v1/sites/{site_uid}/schedule")
    async def schedule(site_uid: str, request: FlexibleLoadRequest):
        try:
            return await service.schedule_load(site_uid, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"planning input unavailable: {exc}",
            ) from exc

    @app.post("/v1/sites/{site_uid}/optimize")
    async def optimize(site_uid: str, request: OptimizationRequest):
        try:
            return await service.optimize(site_uid, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"optimization input unavailable: {exc}",
            ) from exc

    @app.post("/v1/sites/{site_uid}/auxiliary-plan")
    async def auxiliary_plan(site_uid: str, request: AuxiliaryPlanRequest):
        try:
            return await service.auxiliary_plan(site_uid, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"planning input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/digital-twin")
    async def digital_twin(site_uid: str):
        try:
            return await service.digital_twin(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"digital-twin input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/risk-feed")
    async def risk_feed(
        site_uid: str,
        hours: Annotated[int, Query(ge=1, le=168)] = 72,
    ):
        try:
            return await service.risk_feed(site_uid, hours)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"risk-feed input unavailable: {exc}",
            ) from exc

    @app.get("/v1/sites/{site_uid}/action-plan")
    async def action_plan(
        site_uid: str,
        hours: Annotated[int, Query(ge=1, le=168)] = 72,
    ):
        try:
            return await service.action_plan(site_uid, hours)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"planning input unavailable: {exc}",
            ) from exc

    return app


async def _forecast_loop(service: AutonomyService) -> None:
    interval = max(60.0, service.settings.forecast_interval_seconds)
    while True:
        for site_uid in service.settings.sites:
            try:
                await service.forecast(site_uid, 72)
            except (httpx.HTTPError, RuntimeError, ValueError):
                pass
        await asyncio.sleep(interval)


async def _calibration_loop(service: AutonomyService) -> None:
    interval = max(900.0, service.settings.calibration_interval_seconds)
    while True:
        for site_uid in service.settings.sites:
            try:
                await service.refresh_calibration(site_uid)
            except (httpx.HTTPError, RuntimeError, ValueError):
                pass
        await asyncio.sleep(interval)


async def _shadow_autopilot_loop(service: ShadowAutopilotService) -> None:
    interval = max(300.0, service.settings.shadow_interval_seconds)
    while True:
        for site_uid in service.settings.sites:
            try:
                await service.tick(site_uid)
            except (httpx.HTTPError, RuntimeError, ValueError):
                pass
        await asyncio.sleep(interval)


async def _adaptive_world_loop(service: AdaptiveWorldService) -> None:
    interval = max(900.0, service.settings.adaptive_interval_seconds)
    while True:
        for site_uid in service.settings.sites:
            try:
                await service.tick(site_uid)
            except (httpx.HTTPError, RuntimeError, ValueError):
                pass
        await asyncio.sleep(interval)
