# src/powersite_autonomy/adaptive_api.py
from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query

from .adaptive_service import AdaptiveWorldService


def build_adaptive_router(service: AdaptiveWorldService) -> APIRouter:
    router = APIRouter(prefix="/v1/sites/{site_uid}/adaptive", tags=["adaptive-world"])

    @router.get("/snapshot")
    async def snapshot(site_uid: str):
        try:
            return await service.snapshot(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"adaptive input unavailable: {exc}"
            ) from exc

    @router.post("/refresh")
    async def refresh(
        site_uid: str,
        days: Annotated[int | None, Query(ge=14, le=365)] = None,
    ):
        try:
            return await service.refresh(site_uid, days)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"adaptive input unavailable: {exc}"
            ) from exc

    @router.post("/weather/capture")
    async def capture_weather(
        site_uid: str,
        hours: Annotated[int | None, Query(ge=1, le=168)] = None,
    ):
        try:
            return await service.capture_weather_run(site_uid, hours)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502, detail=f"weather input unavailable: {exc}"
            ) from exc

    @router.get("/weather/runs")
    async def weather_runs(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_weather_runs(site_uid, limit)

    @router.get("/weather/skill")
    async def weather_skill(site_uid: str):
        service.autonomy.site_config(site_uid)
        return await service.storage.latest_weather_skill(site_uid)

    @router.get("/seasonal-model")
    async def seasonal_model(site_uid: str):
        service.autonomy.site_config(site_uid)
        return await service.storage.latest_seasonal_overlay(site_uid)

    @router.get("/load-events")
    async def load_events(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.load_events(site_uid, limit)

    @router.get("/managed-load-evidence")
    async def managed_load_evidence(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.managed_load_evidence(site_uid, limit)

    @router.get("/battery-health")
    async def battery_health(site_uid: str):
        service.autonomy.site_config(site_uid)
        return await service.storage.latest_battery(site_uid)

    @router.get("/uncertainty")
    async def uncertainty(site_uid: str):
        service.autonomy.site_config(site_uid)
        return await service.storage.latest_uncertainty(site_uid)

    @router.get("/change-points")
    async def change_points(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_change_points(site_uid, limit)

    @router.get("/models")
    async def models(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        service.autonomy.site_config(site_uid)
        return {
            "champion": await service.storage.champion_model(site_uid),
            "candidates": await service.storage.recent_candidates(site_uid, limit),
        }

    @router.get("/promotions")
    async def promotions(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_promotions(site_uid, limit)

    @router.get("/scorecard")
    async def scorecard(site_uid: str):
        try:
            return await service.scorecard(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
