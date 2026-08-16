# src/powersite_autonomy/app.py
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from typing import Annotated

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import __version__
from .config import Settings, load_settings
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
    evidence_service = EvidenceIntelligenceService()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await asyncio.gather(storage.initialize(), shadow_storage.initialize())
        app.state.service = service
        app.state.shadow_service = shadow_service
        app.state.evidence_service = evidence_service
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
            "shadow-autopilot, and evidence-intelligence service."
        ),
        lifespan=lifespan,
    )
    app.include_router(build_shadow_router(shadow_service))
    app.include_router(build_evidence_router(evidence_service))

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        return HTMLResponse(_dashboard_html())

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


def _dashboard_html() -> str:
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>PowerSite Autonomy</title>
<style>
body { font-family: system-ui, sans-serif; background: #101418; color: #e8eef3; }
body { margin: 0; padding: 2rem; }
main { max-width: 1100px; margin: auto; }
.card { background: #182028; border: 1px solid #2b3945; border-radius: 14px; }
.card { padding: 1rem 1.2rem; margin: 1rem 0; }
button { padding: .65rem 1rem; border-radius: 8px; border: 0; cursor: pointer; }
button { margin-right: .4rem; margin-bottom: .4rem; }
pre { white-space: pre-wrap; overflow: auto; }
.muted { color: #9eb0be; }
input { padding: .55rem; background: #0e1419; color: #fff; }
input { border: 1px solid #40505d; border-radius: 6px; }
</style>
</head>
<body>
<main>
<h1>Morningstar PowerSite Autonomy</h1>
<p class="muted">Calibrated forecasting, optimization, and read-only Shadow Autopilot.</p>
<div class="card">
<label>Site UID <input id="site" value="sys_default"></label>
<button onclick="loadPath('forecast?hours=72')">Forecast</button>
<button onclick="loadPath('digital-twin')">Digital twin</button>
<button onclick="loadPath('action-plan?hours=72')">Action plan</button>
<button onclick="loadPath('autopilot/plan?hours=72')">Shadow plan</button>
<button onclick="loadPath('autopilot/scorecard')">Autopilot scorecard</button>
<button onclick="loadPath('autopilot/actions?limit=50')">Shadow ledger</button>
<button onclick="loadPath('autopilot/epochs')">Model epochs</button>
</div>
<div class="card"><pre id="output">Select a configured site and request a view.</pre></div>
<script>
async function loadPath(path) {
  const site = encodeURIComponent(document.getElementById('site').value);
  const output = document.getElementById('output');
  output.textContent = 'Loading…';
  try {
    const response = await fetch('/v1/sites/' + site + '/' + path);
    const data = await response.json();
    output.textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    output.textContent = String(error);
  }
}
</script>
</main>
</body>
</html>"""
