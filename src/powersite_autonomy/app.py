from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from . import __version__
from .config import Settings, load_settings
from .models import ScenarioRequest
from .service import AutonomyService
from .storage import Storage
from .upstream import MorningstarClient
from .weather import WeatherClient


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or load_settings()
    morningstar = MorningstarClient(resolved.morningstar_base_url)
    weather = WeatherClient(resolved.weather_base_url)
    storage = Storage(resolved.database_path)
    service = AutonomyService(resolved, morningstar, weather, storage)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await storage.initialize()
        app.state.service = service
        monitor = asyncio.create_task(_forecast_loop(service), name="autonomy-forecast-loop")
        try:
            yield
        finally:
            monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await monitor
            await morningstar.aclose()
            await weather.aclose()

    app = FastAPI(
        title="Morningstar PowerSite Autonomy",
        version=__version__,
        description="Read-only predictive energy and battery-autonomy service.",
        lifespan=lifespan,
    )

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
        return {"status": "ok", "version": __version__, "morningstar_api": upstream}

    @app.get("/v1/sites")
    async def sites():
        try:
            upstream_sites = await service.morningstar.list_sites()
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"Morningstar API unavailable: {exc}"
            ) from exc
        configured = set(service.settings.sites)
        return [
            {**site.model_dump(), "autonomy_configured": site.site_uid in configured}
            for site in upstream_sites
        ]

    @app.get("/v1/sites/{site_uid}/forecast")
    async def forecast(site_uid: str, hours: int = Query(72, ge=1, le=168)):
        try:
            return await service.forecast(site_uid, hours)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"upstream forecast input unavailable: {exc}"
            ) from exc

    @app.get("/v1/sites/{site_uid}/forecasts")
    async def forecast_history(site_uid: str, limit: int = Query(20, ge=1, le=200)):
        return await storage.recent_forecasts(site_uid, limit)

    @app.post("/v1/sites/{site_uid}/scenarios")
    async def scenarios(site_uid: str, request: ScenarioRequest):
        try:
            return await service.scenario(site_uid, request)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"upstream forecast input unavailable: {exc}"
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
main { max-width: 1000px; margin: auto; }
.card { background: #182028; border: 1px solid #2b3945; border-radius: 14px; }
.card { padding: 1rem 1.2rem; margin: 1rem 0; }
button { padding: .65rem 1rem; border-radius: 8px; border: 0; cursor: pointer; }
pre { white-space: pre-wrap; overflow: auto; }
.muted { color: #9eb0be; }
input { padding: .55rem; background: #0e1419; color: #fff; }
input { border: 1px solid #40505d; border-radius: 6px; }
</style>
</head>
<body>
<main>
<h1>Morningstar PowerSite Autonomy</h1>
<p class="muted">Predictive energy reserve and scenario console.</p>
<div class="card">
<label>Site UID <input id="site" value="sys_default"></label>
<button onclick="loadForecast()">Forecast 72h</button>
</div>
<div class="card"><pre id="output">Select a configured site and request a forecast.</pre></div>
<script>
async function loadForecast() {
  const site = encodeURIComponent(document.getElementById('site').value);
  const output = document.getElementById('output');
  output.textContent = 'Loading…';
  try {
    const response = await fetch('/v1/sites/' + site + '/forecast?hours=72');
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
