# src/powersite_autonomy/storage.py
from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .fleet import FleetObservation
from .models import ForecastScoreSummary, ForecastSummary, ScenarioResult, SiteCalibration

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    horizon_hours INTEGER NOT NULL,
    reserve_breach_probability REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forecasts_site_time ON forecasts(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS scenarios (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS calibrations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    calibration_version TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calibrations_site_time
    ON calibrations(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS forecast_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_forecast_scores_site_time
    ON forecast_scores(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS fleet_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    site_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_fleet_observations_kind_key
    ON fleet_observations(kind, key, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_fleet_observations_site_time
    ON fleet_observations(site_uid, observed_at DESC);
"""


class Storage:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript(_SCHEMA)

    async def save_forecast(self, forecast: ForecastSummary) -> None:
        payload = forecast.model_dump_json()
        async with self._write_lock:
            await asyncio.to_thread(self._save_forecast_sync, forecast, payload)

    def _save_forecast_sync(self, forecast: ForecastSummary, payload: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT INTO forecasts(site_uid, generated_at, horizon_hours, "
                "reserve_breach_probability, payload_json) VALUES (?, ?, ?, ?, ?)",
                (
                    forecast.site_uid,
                    forecast.generated_at.isoformat(),
                    forecast.horizon_hours,
                    forecast.reserve_breach_probability,
                    payload,
                ),
            )

    async def save_scenario(self, result: ScenarioResult) -> None:
        payload = result.model_dump_json()
        async with self._write_lock:
            await asyncio.to_thread(self._save_scenario_sync, result, payload)

    def _save_scenario_sync(self, result: ScenarioResult, payload: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT INTO scenarios(site_uid, generated_at, payload_json) VALUES (?, ?, ?)",
                (result.site_uid, result.generated_at.isoformat(), payload),
            )

    async def save_calibration(self, calibration: SiteCalibration) -> None:
        payload = calibration.model_dump_json()
        async with self._write_lock:
            await asyncio.to_thread(self._save_calibration_sync, calibration, payload)

    def _save_calibration_sync(self, calibration: SiteCalibration, payload: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT INTO calibrations(site_uid, generated_at, calibration_version, "
                "payload_json) VALUES (?, ?, ?, ?)",
                (
                    calibration.site_uid,
                    calibration.generated_at.isoformat(),
                    calibration.calibration_version,
                    payload,
                ),
            )

    async def latest_calibration(self, site_uid: str) -> SiteCalibration | None:
        row = await asyncio.to_thread(self._latest_payload_sync, "calibrations", site_uid)
        return SiteCalibration.model_validate_json(row) if row is not None else None

    async def recent_calibrations(self, site_uid: str, limit: int = 20) -> list[dict]:
        rows = await asyncio.to_thread(
            self._recent_payloads_sync,
            "calibrations",
            site_uid,
            limit,
        )
        return [json.loads(row) for row in rows]

    async def save_forecast_score(self, score: ForecastScoreSummary) -> None:
        payload = score.model_dump_json()
        async with self._write_lock:
            await asyncio.to_thread(self._save_score_sync, score, payload)

    def _save_score_sync(self, score: ForecastScoreSummary, payload: str) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT INTO forecast_scores(site_uid, generated_at, payload_json) VALUES (?, ?, ?)",
                (score.site_uid, score.generated_at.isoformat(), payload),
            )

    async def save_fleet_observations(self, observations: list[FleetObservation]) -> None:
        if not observations:
            return
        async with self._write_lock:
            await asyncio.to_thread(self._save_fleet_observations_sync, observations)

    def _save_fleet_observations_sync(self, observations: list[FleetObservation]) -> None:
        rows = [
            (
                observation.site_uid,
                observation.kind,
                observation.key,
                observation.observed_at.isoformat(),
                observation.model_dump_json(),
            )
            for observation in observations
        ]
        with sqlite3.connect(self._path) as connection:
            connection.executemany(
                "INSERT INTO fleet_observations(site_uid, kind, key, observed_at, payload_json) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    async def fleet_observations(
        self,
        *,
        kind: str | None = None,
        key: str | None = None,
        limit: int = 1000,
    ) -> list[FleetObservation]:
        rows = await asyncio.to_thread(self._fleet_observations_sync, kind, key, limit)
        return [FleetObservation.model_validate_json(row) for row in rows]

    def _fleet_observations_sync(
        self,
        kind: str | None,
        key: str | None,
        limit: int,
    ) -> list[str]:
        bounded = max(1, min(limit, 10000))
        clauses: list[str] = []
        params: list[object] = []
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)
        if key is not None:
            clauses.append("key = ?")
            params.append(key)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(bounded)
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM fleet_observations {where} "
                "ORDER BY observed_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [row[0] for row in rows]

    async def recent_forecasts(self, site_uid: str, limit: int = 20) -> list[dict]:
        rows = await asyncio.to_thread(
            self._recent_payloads_sync,
            "forecasts",
            site_uid,
            limit,
        )
        return [json.loads(row) for row in rows]

    async def recent_forecast_models(
        self,
        site_uid: str,
        limit: int = 20,
    ) -> list[ForecastSummary]:
        payloads = await self.recent_forecasts(site_uid, limit)
        return [ForecastSummary.model_validate(payload) for payload in payloads]

    def _latest_payload_sync(self, table: str, site_uid: str) -> str | None:
        if table not in {"calibrations", "forecasts", "forecast_scores"}:
            raise ValueError("unsupported table")
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                f"SELECT payload_json FROM {table} WHERE site_uid = ? "
                "ORDER BY generated_at DESC LIMIT 1",
                (site_uid,),
            ).fetchone()
        return row[0] if row else None

    def _recent_payloads_sync(self, table: str, site_uid: str, limit: int) -> list[str]:
        if table not in {"calibrations", "forecasts", "forecast_scores"}:
            raise ValueError("unsupported table")
        bounded = max(1, min(limit, 200))
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} WHERE site_uid = ? "
                "ORDER BY generated_at DESC LIMIT ?",
                (site_uid, bounded),
            ).fetchall()
        return [row[0] for row in rows]
