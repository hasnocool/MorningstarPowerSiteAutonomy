# src/powersite_autonomy/shadow_api.py
from __future__ import annotations

from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query

from .shadow_service import ShadowAutopilotService


def build_shadow_router(service: ShadowAutopilotService) -> APIRouter:
    router = APIRouter(prefix="/v1/sites/{site_uid}/autopilot", tags=["shadow-autopilot"])

    @router.get("/policy")
    def policy(site_uid: str):
        try:
            return {
                "policy": service.policy(site_uid),
                "managed_loads": service.managed_loads(site_uid),
                "read_only": True,
                "executable": False,
            }
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/plan")
    async def plan(
        site_uid: str,
        hours: Annotated[int | None, Query(ge=1, le=168)] = None,
    ):
        try:
            return await service.plan(site_uid, hours, persist=True)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"shadow planning input unavailable: {exc}",
            ) from exc

    @router.post("/tick")
    async def tick(site_uid: str):
        try:
            return await service.tick(site_uid)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"shadow autopilot input unavailable: {exc}",
            ) from exc

    @router.get("/plans")
    async def plans(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_plans(site_uid, limit)

    @router.get("/actions")
    async def actions(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_actions(site_uid, limit)

    @router.get("/evaluations")
    async def evaluations(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_evaluations(site_uid, limit)

    @router.get("/feedback")
    async def feedback(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_feedback(site_uid, limit)

    @router.get("/scorecard")
    async def scorecard(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ):
        try:
            return await service.scorecard(site_uid, limit)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/epochs")
    async def epochs(
        site_uid: str,
        limit: Annotated[int, Query(ge=1, le=200)] = 20,
    ):
        service.autonomy.site_config(site_uid)
        return await service.storage.recent_epochs(site_uid, limit)

    @router.post("/replay/{plan_id}")
    async def replay(site_uid: str, plan_id: str):
        try:
            return await service.replay(site_uid, plan_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail=f"counterfactual history unavailable: {exc}",
            ) from exc

    return router
