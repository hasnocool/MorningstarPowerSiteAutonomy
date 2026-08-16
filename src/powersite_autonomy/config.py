# src/powersite_autonomy/config.py
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import SiteConfig
from .shadow_models import EnergyPolicy, ManagedLoad


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
    shadow_autopilot_enabled: bool = True
    shadow_interval_seconds: float = 900.0
    shadow_horizon_hours: int = 72
    shadow_evaluation_delay_hours: float = 6.0
    shadow_feedback_cooldown_hours: float = 12.0
    shadow_feedback_max_adjustment_fraction: float = 0.05
    shadow_policies: dict[str, EnergyPolicy] = field(default_factory=dict)
    shadow_loads: dict[str, list[ManagedLoad]] = field(default_factory=dict)
    adaptive_world_enabled: bool = True
    adaptive_interval_seconds: float = 21600.0
    adaptive_history_days: int = 120
    adaptive_weather_horizon_hours: int = 72
    adaptive_weather_evaluation_delay_hours: float = 84.0
    adaptive_minimum_samples: int = 48
    adaptive_minimum_samples_per_cell: int = 4
    adaptive_promotion_margin: float = 0.08


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


def _policy_for_site(site: SiteConfig, value: Any) -> EnergyPolicy:
    raw = dict(value) if isinstance(value, dict) else {}
    raw.setdefault("minimum_reserve_percent", site.reserve_percent)
    default_emergency = max(0.0, min(15.0, site.reserve_percent - 5.0))
    raw.setdefault("emergency_reserve_percent", default_emergency)
    raw.setdefault("target_morning_soc_percent", max(40.0, site.reserve_percent))
    return EnergyPolicy.model_validate(raw)


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
    shadow = raw.get("shadow_autopilot", {})
    adaptive = raw.get("adaptive_world", {})
    raw_sites = raw.get("sites", {})

    sites = {uid: SiteConfig.model_validate(value) for uid, value in raw_sites.items()}
    shadow_policies = {
        uid: _policy_for_site(sites[uid], value.get("shadow_policy", {}))
        for uid, value in raw_sites.items()
    }
    shadow_loads = {
        uid: [ManagedLoad.model_validate(item) for item in value.get("shadow_loads", [])]
        for uid, value in raw_sites.items()
    }
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
        shadow_autopilot_enabled=_as_bool(
            os.getenv("AUTONOMY_SHADOW_ENABLED", shadow.get("enabled", True)),
            True,
        ),
        shadow_interval_seconds=float(
            os.getenv("AUTONOMY_SHADOW_INTERVAL", shadow.get("interval_seconds", 900))
        ),
        shadow_horizon_hours=max(
            1,
            min(
                168,
                int(os.getenv("AUTONOMY_SHADOW_HORIZON", shadow.get("horizon_hours", 72))),
            ),
        ),
        shadow_evaluation_delay_hours=max(
            1.0,
            float(
                os.getenv(
                    "AUTONOMY_SHADOW_EVALUATION_DELAY",
                    shadow.get("evaluation_delay_hours", 6),
                )
            ),
        ),
        shadow_feedback_cooldown_hours=max(
            1.0,
            float(
                os.getenv(
                    "AUTONOMY_SHADOW_FEEDBACK_COOLDOWN",
                    shadow.get("feedback_cooldown_hours", 12),
                )
            ),
        ),
        shadow_feedback_max_adjustment_fraction=max(
            0.001,
            min(
                0.10,
                float(
                    os.getenv(
                        "AUTONOMY_SHADOW_FEEDBACK_MAX_ADJUSTMENT",
                        shadow.get("feedback_max_adjustment_fraction", 0.05),
                    )
                ),
            ),
        ),
        shadow_policies=shadow_policies,
        shadow_loads=shadow_loads,
        adaptive_world_enabled=_as_bool(
            os.getenv("AUTONOMY_ADAPTIVE_ENABLED", adaptive.get("enabled", True)),
            True,
        ),
        adaptive_interval_seconds=max(
            900.0,
            float(
                os.getenv(
                    "AUTONOMY_ADAPTIVE_INTERVAL",
                    adaptive.get("interval_seconds", 21600),
                )
            ),
        ),
        adaptive_history_days=max(
            14,
            min(
                365,
                int(
                    os.getenv(
                        "AUTONOMY_ADAPTIVE_HISTORY_DAYS",
                        adaptive.get("history_days", 120),
                    )
                ),
            ),
        ),
        adaptive_weather_horizon_hours=max(
            1,
            min(
                168,
                int(
                    os.getenv(
                        "AUTONOMY_ADAPTIVE_WEATHER_HORIZON",
                        adaptive.get("weather_horizon_hours", 72),
                    )
                ),
            ),
        ),
        adaptive_weather_evaluation_delay_hours=max(
            24.0,
            float(
                os.getenv(
                    "AUTONOMY_ADAPTIVE_WEATHER_EVALUATION_DELAY",
                    adaptive.get("weather_evaluation_delay_hours", 84),
                )
            ),
        ),
        adaptive_minimum_samples=max(
            6,
            int(
                os.getenv(
                    "AUTONOMY_ADAPTIVE_MINIMUM_SAMPLES",
                    adaptive.get("minimum_samples", 48),
                )
            ),
        ),
        adaptive_minimum_samples_per_cell=max(
            2,
            int(
                os.getenv(
                    "AUTONOMY_ADAPTIVE_MINIMUM_CELL_SAMPLES",
                    adaptive.get("minimum_samples_per_cell", 4),
                )
            ),
        ),
        adaptive_promotion_margin=max(
            0.01,
            min(
                0.50,
                float(
                    os.getenv(
                        "AUTONOMY_ADAPTIVE_PROMOTION_MARGIN",
                        adaptive.get("promotion_margin", 0.08),
                    )
                ),
            ),
        ),
        sites=sites,
    )
