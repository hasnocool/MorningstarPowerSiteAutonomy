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

    @router.post("/policy-lab/tick")
    async def policy_tick(site_uid: str):
        try:
            return await service.policy_lab.tick(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/policy-lab/snapshot")
    async def policy_snapshot(site_uid: str):
        try:
            return await service.policy_lab.snapshot(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/policy-lab/champion")
    async def policy_champion(site_uid: str):
        try:
            return await service.policy_lab.champion(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/policy-lab/candidates")
    async def policy_candidates(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.policy_lab.storage.recent_candidates(site_uid, limit)

    @router.get("/policy-lab/evaluations")
    async def policy_evaluations(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.policy_lab.storage.recent_evaluations(site_uid, limit)

    @router.get("/policy-lab/tournaments")
    async def policy_tournaments(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ):
        service.autonomy.site_config(site_uid)
        return await service.policy_lab.storage.recent_tournaments(site_uid, limit)

    @router.get("/policy-lab/frontier")
    async def policy_frontier(site_uid: str):
        try:
            return await service.policy_lab.frontier(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/policy-lab/regret")
    async def policy_regret(site_uid: str):
        service.autonomy.site_config(site_uid)
        value = await service.policy_lab.storage.latest_regret(site_uid)
        if value is not None:
            return value
        return (await service.policy_lab.tick(site_uid)).regret

    @router.get("/policy-lab/decision-sensitivity")
    async def decision_sensitivity(site_uid: str):
        try:
            return (await service.policy_lab.snapshot(site_uid)).decision_sensitivity
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/policy-lab/dynamic-reserve")
    async def dynamic_reserve(site_uid: str):
        try:
            return await service.policy_lab.dynamic_reserve(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/policy-lab/scorecard")
    async def policy_scorecard(site_uid: str):
        try:
            return await service.policy_lab.scorecard(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/policy-lab/intelligence")
    async def policy_intelligence(site_uid: str):
        try:
            return await service.policy_lab.intelligence(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
