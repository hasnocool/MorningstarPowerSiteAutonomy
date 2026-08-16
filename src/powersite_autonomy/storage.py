from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .models import ForecastSummary, ScenarioResult

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

    async def recent_forecasts(self, site_uid: str, limit: int = 20) -> list[dict]:
        rows = await asyncio.to_thread(self._recent_forecasts_sync, site_uid, limit)
        return [json.loads(row[0]) for row in rows]

    def _recent_forecasts_sync(self, site_uid: str, limit: int) -> list[tuple[str]]:
        with sqlite3.connect(self._path) as connection:
            return connection.execute(
                "SELECT payload_json FROM forecasts WHERE site_uid = ? "
                "ORDER BY generated_at DESC LIMIT ?",
                (site_uid, max(1, min(limit, 200))),
            ).fetchall()
