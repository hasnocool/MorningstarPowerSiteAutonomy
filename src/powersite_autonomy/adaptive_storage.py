# src/powersite_autonomy/adaptive_storage.py
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel

from .adaptive_models import SeasonalCalibrationOverlay
from .adaptive_storage_base import AdaptiveStorage as _AdaptiveStorage


class AdaptiveStorage(_AdaptiveStorage):
    """Adaptive storage with active-overlay replacement and timezone-aware timestamps."""

    async def save_seasonal_overlay(self, value: SeasonalCalibrationOverlay) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._deactivate_sync, "seasonal_overlay", value.site_uid)
        await self._save_artifact(
            "seasonal_overlay",
            value.site_uid,
            value,
            replace=False,
            active=value.active,
        )

    async def _save_artifact(
        self,
        kind: str,
        site_uid: str,
        value: BaseModel,
        *,
        replace: bool,
        active: bool = False,
        artifact_id: str | None = None,
    ) -> None:
        identifier = artifact_id or str(uuid4())
        generated_at = getattr(value, "generated_at", datetime.now(UTC)).isoformat()
        async with self._write_lock:
            await asyncio.to_thread(
                self._save_artifact_sync,
                identifier,
                kind,
                site_uid,
                generated_at,
                active,
                value.model_dump_json(),
                replace,
            )
