# src/powersite_autonomy/adaptive_storage.py
from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from .adaptive_models import (
    AdaptiveForecastContext,
    AdaptiveModelCandidate,
    AdaptiveWorldSnapshot,
    BatteryDegradationSnapshot,
    ChangePointSignal,
    LoadEventCluster,
    ManagedLoadCompletionEvidence,
    ModelPromotionDecision,
    SeasonalCalibrationOverlay,
    UncertaintyCalibration,
    WeatherForecastRun,
    WeatherRunScore,
    WeatherSkillSummary,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS adaptive_weather_runs (
    run_id TEXT PRIMARY KEY,
    site_uid TEXT NOT NULL,
    issued_at TEXT NOT NULL,
    evaluated INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adaptive_weather_runs_site_time
    ON adaptive_weather_runs(site_uid, issued_at DESC);
CREATE TABLE IF NOT EXISTS adaptive_weather_scores (
    score_id TEXT PRIMARY KEY,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adaptive_weather_scores_site_time
    ON adaptive_weather_scores(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS adaptive_artifacts (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_adaptive_artifacts_kind_site_time
    ON adaptive_artifacts(kind, site_uid, generated_at DESC);
"""

T = TypeVar("T", bound=BaseModel)


class AdaptiveStorage:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript(_SCHEMA)

    async def save_weather_runs(self, runs: list[WeatherForecastRun]) -> None:
        if not runs:
            return
        async with self._write_lock:
            await asyncio.to_thread(self._save_weather_runs_sync, runs)

    def _save_weather_runs_sync(self, runs: list[WeatherForecastRun]) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO adaptive_weather_runs"
                "(run_id, site_uid, issued_at, evaluated, payload_json) VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        run.run_id,
                        run.site_uid,
                        run.issued_at.isoformat(),
                        int(run.evaluated),
                        run.model_dump_json(),
                    )
                    for run in runs
                ],
            )

    async def recent_weather_runs(
        self, site_uid: str, limit: int = 100
    ) -> list[WeatherForecastRun]:
        payloads = await asyncio.to_thread(
            self._weather_run_payloads_sync, site_uid, limit, None
        )
        return [WeatherForecastRun.model_validate_json(item) for item in payloads]

    async def unevaluated_weather_runs(
        self,
        site_uid: str,
        issued_before: datetime,
        limit: int = 100,
    ) -> list[WeatherForecastRun]:
        payloads = await asyncio.to_thread(
            self._weather_run_payloads_sync, site_uid, limit, issued_before
        )
        return [WeatherForecastRun.model_validate_json(item) for item in payloads]

    def _weather_run_payloads_sync(
        self,
        site_uid: str,
        limit: int,
        issued_before: datetime | None,
    ) -> list[str]:
        bounded = max(1, min(limit, 1000))
        sql = "SELECT payload_json FROM adaptive_weather_runs WHERE site_uid = ?"
        params: list[object] = [site_uid]
        if issued_before is not None:
            sql += " AND evaluated = 0 AND issued_at <= ?"
            params.append(issued_before.isoformat())
        sql += " ORDER BY issued_at DESC LIMIT ?"
        params.append(bounded)
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [row[0] for row in rows]

    async def mark_weather_run_evaluated(self, run_id: str) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._mark_weather_run_evaluated_sync, run_id)

    def _mark_weather_run_evaluated_sync(self, run_id: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "UPDATE adaptive_weather_runs SET evaluated = 1 WHERE run_id = ?", (run_id,)
            )

    async def save_weather_scores(self, scores: list[WeatherRunScore]) -> None:
        if not scores:
            return
        async with self._write_lock:
            await asyncio.to_thread(self._save_weather_scores_sync, scores)

    def _save_weather_scores_sync(self, scores: list[WeatherRunScore]) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.executemany(
                "INSERT OR REPLACE INTO adaptive_weather_scores"
                "(score_id, site_uid, generated_at, payload_json) VALUES (?, ?, ?, ?)",
                [
                    (
                        score.score_id,
                        score.site_uid,
                        score.generated_at.isoformat(),
                        score.model_dump_json(),
                    )
                    for score in scores
                ],
            )

    async def recent_weather_scores(
        self, site_uid: str, limit: int = 500
    ) -> list[WeatherRunScore]:
        bounded = max(1, min(limit, 5000))
        rows = await asyncio.to_thread(
            self._query_payloads_sync,
            "adaptive_weather_scores",
            site_uid,
            bounded,
        )
        return [WeatherRunScore.model_validate_json(item) for item in rows]

    async def save_weather_skill(self, value: WeatherSkillSummary) -> None:
        await self._save_artifact("weather_skill", value.site_uid, value, replace=False)

    async def latest_weather_skill(self, site_uid: str) -> WeatherSkillSummary | None:
        return await self._latest("weather_skill", site_uid, WeatherSkillSummary)

    async def save_seasonal_overlay(self, value: SeasonalCalibrationOverlay) -> None:
        if value.active:
            await asyncio.to_thread(self._deactivate_sync, "seasonal_overlay", value.site_uid)
        await self._save_artifact(
            "seasonal_overlay", value.site_uid, value, replace=False, active=value.active
        )

    async def latest_seasonal_overlay(
        self, site_uid: str, *, active_only: bool = False
    ) -> SeasonalCalibrationOverlay | None:
        payloads = await self._artifact_payloads(
            "seasonal_overlay", site_uid, 1, active_only=active_only
        )
        return SeasonalCalibrationOverlay.model_validate_json(payloads[0]) if payloads else None

    async def replace_load_events(self, site_uid: str, values: list[LoadEventCluster]) -> None:
        await self._replace_kind("load_event", site_uid, values)

    async def load_events(self, site_uid: str, limit: int = 100) -> list[LoadEventCluster]:
        return await self._recent("load_event", site_uid, LoadEventCluster, limit)

    async def save_managed_load_evidence(
        self, values: list[ManagedLoadCompletionEvidence]
    ) -> None:
        for value in values:
            await self._save_artifact(
                "managed_load_evidence",
                value.site_uid,
                value,
                replace=True,
                artifact_id=value.evidence_id,
            )

    async def managed_load_evidence(
        self, site_uid: str, limit: int = 100
    ) -> list[ManagedLoadCompletionEvidence]:
        return await self._recent(
            "managed_load_evidence", site_uid, ManagedLoadCompletionEvidence, limit
        )

    async def save_battery(self, value: BatteryDegradationSnapshot) -> None:
        await self._save_artifact("battery", value.site_uid, value, replace=False)

    async def latest_battery(self, site_uid: str) -> BatteryDegradationSnapshot | None:
        return await self._latest("battery", site_uid, BatteryDegradationSnapshot)

    async def recent_battery(
        self, site_uid: str, limit: int = 2
    ) -> list[BatteryDegradationSnapshot]:
        return await self._recent("battery", site_uid, BatteryDegradationSnapshot, limit)

    async def save_uncertainty(self, value: UncertaintyCalibration) -> None:
        await self._save_artifact("uncertainty", value.site_uid, value, replace=False)

    async def latest_uncertainty(self, site_uid: str) -> UncertaintyCalibration | None:
        return await self._latest("uncertainty", site_uid, UncertaintyCalibration)

    async def save_change_points(self, values: list[ChangePointSignal]) -> None:
        for value in values:
            await self._save_artifact(
                "change_point",
                value.site_uid,
                value,
                replace=True,
                artifact_id=value.signal_id,
            )

    async def recent_change_points(
        self, site_uid: str, limit: int = 100
    ) -> list[ChangePointSignal]:
        return await self._recent("change_point", site_uid, ChangePointSignal, limit)

    async def save_candidates(
        self,
        site_uid: str,
        generated_at: datetime,
        candidates: list[AdaptiveModelCandidate],
    ) -> None:
        for item in candidates:
            artifact_id = f"candidate:{generated_at.isoformat()}:{item.candidate_id}"
            await self._save_artifact(
                "model_candidate", site_uid, item, replace=True, artifact_id=artifact_id
            )

    async def recent_candidates(
        self, site_uid: str, limit: int = 50
    ) -> list[AdaptiveModelCandidate]:
        return await self._recent("model_candidate", site_uid, AdaptiveModelCandidate, limit)

    async def save_promotion(self, value: ModelPromotionDecision) -> None:
        await self._save_artifact(
            "promotion", value.site_uid, value, replace=True, artifact_id=value.decision_id
        )

    async def recent_promotions(
        self, site_uid: str, limit: int = 50
    ) -> list[ModelPromotionDecision]:
        return await self._recent("promotion", site_uid, ModelPromotionDecision, limit)

    async def champion_model(self, site_uid: str) -> str:
        promotions = await self.recent_promotions(site_uid, 1)
        return promotions[0].champion_after if promotions else "baseline-v2"

    async def save_snapshot(self, value: AdaptiveWorldSnapshot) -> None:
        await self._save_artifact("snapshot", value.site_uid, value, replace=False)

    async def latest_snapshot(self, site_uid: str) -> AdaptiveWorldSnapshot | None:
        return await self._latest("snapshot", site_uid, AdaptiveWorldSnapshot)

    async def forecast_context(self, site_uid: str) -> AdaptiveForecastContext:
        skill, overlay, uncertainty = await asyncio.gather(
            self.latest_weather_skill(site_uid),
            self.latest_seasonal_overlay(site_uid, active_only=True),
            self.latest_uncertainty(site_uid),
        )
        return AdaptiveForecastContext(
            weather_weights_by_horizon=skill.weights_by_horizon if skill else {},
            seasonal_overlay=overlay,
            solar_uncertainty_scale=uncertainty.scale_for("solar") if uncertainty else 1.0,
            load_uncertainty_scale=uncertainty.scale_for("load") if uncertainty else 1.0,
            soc_uncertainty_scale=uncertainty.scale_for("soc") if uncertainty else 1.0,
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
        generated = getattr(value, "generated_at", datetime.now()).isoformat()
        async with self._write_lock:
            await asyncio.to_thread(
                self._save_artifact_sync,
                identifier,
                kind,
                site_uid,
                generated,
                active,
                value.model_dump_json(),
                replace,
            )

    def _save_artifact_sync(
        self,
        identifier: str,
        kind: str,
        site_uid: str,
        generated_at: str,
        active: bool,
        payload: str,
        replace: bool,
    ) -> None:
        verb = "INSERT OR REPLACE" if replace else "INSERT"
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                f"{verb} INTO adaptive_artifacts"
                "(artifact_id, kind, site_uid, generated_at, active, payload_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (identifier, kind, site_uid, generated_at, int(active), payload),
            )

    async def _replace_kind(self, kind: str, site_uid: str, values: list[BaseModel]) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._delete_kind_sync, kind, site_uid)
        for value in values:
            await self._save_artifact(kind, site_uid, value, replace=False)

    def _delete_kind_sync(self, kind: str, site_uid: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "DELETE FROM adaptive_artifacts WHERE kind = ? AND site_uid = ?",
                (kind, site_uid),
            )

    def _deactivate_sync(self, kind: str, site_uid: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "UPDATE adaptive_artifacts SET active = 0 WHERE kind = ? AND site_uid = ?",
                (kind, site_uid),
            )

    async def _latest(self, kind: str, site_uid: str, model: type[T]) -> T | None:
        values = await self._recent(kind, site_uid, model, 1)
        return values[0] if values else None

    async def _recent(
        self, kind: str, site_uid: str, model: type[T], limit: int
    ) -> list[T]:
        payloads = await self._artifact_payloads(kind, site_uid, limit)
        return [model.model_validate_json(item) for item in payloads]

    async def _artifact_payloads(
        self,
        kind: str,
        site_uid: str,
        limit: int,
        *,
        active_only: bool = False,
    ) -> list[str]:
        return await asyncio.to_thread(
            self._artifact_payloads_sync, kind, site_uid, limit, active_only
        )

    def _artifact_payloads_sync(
        self, kind: str, site_uid: str, limit: int, active_only: bool
    ) -> list[str]:
        bounded = max(1, min(limit, 5000))
        sql = (
            "SELECT payload_json FROM adaptive_artifacts "
            "WHERE kind = ? AND site_uid = ?"
        )
        params: list[object] = [kind, site_uid]
        if active_only:
            sql += " AND active = 1"
        sql += " ORDER BY generated_at DESC LIMIT ?"
        params.append(bounded)
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(sql, params).fetchall()
        return [row[0] for row in rows]

    def _query_payloads_sync(self, table: str, site_uid: str, limit: int) -> list[str]:
        if table != "adaptive_weather_scores":
            raise ValueError("unsupported adaptive query table")
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM adaptive_weather_scores WHERE site_uid = ? "
                "ORDER BY generated_at DESC LIMIT ?",
                (site_uid, limit),
            ).fetchall()
        return [row[0] for row in rows]
