from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .models import SiteConfig


@dataclass(frozen=True, slots=True)
class Settings:
    morningstar_base_url: str
    database_path: str
    host: str
    port: int
    forecast_interval_seconds: float
    weather_base_url: str
    monte_carlo_samples: int
    sites: dict[str, SiteConfig]


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
    raw_sites = raw.get("sites", {})

    sites = {uid: SiteConfig.model_validate(value) for uid, value in raw_sites.items()}
    return Settings(
        morningstar_base_url=os.getenv(
            "AUTONOMY_MORNINGSTAR_URL", morningstar.get("base_url", "http://127.0.0.1:8080")
        ).rstrip("/"),
        database_path=os.getenv(
            "AUTONOMY_DATABASE_PATH", autonomy.get("database_path", "./data/autonomy.db")
        ),
        host=os.getenv("AUTONOMY_HOST", server.get("host", "127.0.0.1")),
        port=int(os.getenv("AUTONOMY_PORT", server.get("port", 8091))),
        forecast_interval_seconds=float(
            os.getenv(
                "AUTONOMY_FORECAST_INTERVAL",
                autonomy.get("forecast_interval_seconds", 900),
            )
        ),
        weather_base_url=weather.get("base_url", "https://api.open-meteo.com/v1/forecast"),
        monte_carlo_samples=int(autonomy.get("monte_carlo_samples", 300)),
        sites=sites,
    )
