# src/powersite_autonomy/config.py
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SiteConfig


@dataclass(frozen=True, slots=True)
class Settings:
    morningstar_base_url: str
    database_path: str
    host: str
    port: int
    forecast_interval_seconds: float
    calibration_interval_seconds: float
    calibration_history_days: int
    auto_calibration_enabled: bool
    weather_base_url: str
    weather_archive_base_url: str
    weather_models: tuple[str, ...]
    sentinel_base_url: str | None
    risk_feed_secret: str | None
    monte_carlo_samples: int
    sites: dict[str, SiteConfig]


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _models(value: Any) -> tuple[str, ...]:
    env_value = os.getenv("AUTONOMY_WEATHER_MODELS")
    if env_value is not None:
        value = env_value
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return ()


def load_settings(path: str | Path = "config.toml") -> Settings:
    config_path = Path(path)
    raw: dict = {}
    if config_path.exists():
        with config_path.open("rb") as handle:
            raw = tomllib.load(handle)

    morningstar = raw.get("morningstar", {})
    server = raw.get("server", {})
    autonomy = raw.get("autonomy", {})
    weather = raw.get("weather", {})
    sentinel = raw.get("sentinel", {})
    raw_sites = raw.get("sites", {})

    sites = {uid: SiteConfig.model_validate(value) for uid, value in raw_sites.items()}
    sentinel_url = os.getenv("AUTONOMY_SENTINEL_URL", sentinel.get("base_url", "")).strip()
    return Settings(
        morningstar_base_url=os.getenv(
            "AUTONOMY_MORNINGSTAR_URL",
            morningstar.get("base_url", "http://127.0.0.1:8080"),
        ).rstrip("/"),
        database_path=os.getenv(
            "AUTONOMY_DATABASE_PATH",
            autonomy.get("database_path", "./data/autonomy.db"),
        ),
        host=os.getenv("AUTONOMY_HOST", server.get("host", "127.0.0.1")),
        port=int(os.getenv("AUTONOMY_PORT", server.get("port", 8091))),
        forecast_interval_seconds=float(
            os.getenv(
                "AUTONOMY_FORECAST_INTERVAL",
                autonomy.get("forecast_interval_seconds", 900),
            )
        ),
        calibration_interval_seconds=float(
            os.getenv(
                "AUTONOMY_CALIBRATION_INTERVAL",
                autonomy.get("calibration_interval_seconds", 21600),
            )
        ),
        calibration_history_days=int(
            os.getenv(
                "AUTONOMY_CALIBRATION_HISTORY_DAYS",
                autonomy.get("calibration_history_days", 30),
            )
        ),
        auto_calibration_enabled=_as_bool(
            os.getenv(
                "AUTONOMY_AUTO_CALIBRATION",
                autonomy.get("auto_calibration_enabled", True),
            ),
            True,
        ),
        weather_base_url=weather.get("base_url", "https://api.open-meteo.com/v1/forecast"),
        weather_archive_base_url=weather.get(
            "archive_base_url",
            "https://archive-api.open-meteo.com/v1/archive",
        ),
        weather_models=_models(weather.get("models", [])),
        sentinel_base_url=sentinel_url or None,
        risk_feed_secret=os.getenv("AUTONOMY_RISK_FEED_SECRET") or None,
        monte_carlo_samples=int(autonomy.get("monte_carlo_samples", 300)),
        sites=sites,
    )
