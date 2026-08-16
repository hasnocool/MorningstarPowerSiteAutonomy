# src/powersite_autonomy/weather.py
from __future__ import annotations

import asyncio
import math
from datetime import UTC, date, datetime

import httpx

from .models import SiteConfig, WeatherHour


class WeatherClient:
    def __init__(
        self,
        base_url: str,
        *,
        archive_base_url: str = "https://archive-api.open-meteo.com/v1/archive",
        timeout_seconds: float = 8.0,
    ) -> None:
        self._base_url = base_url
        self._archive_base_url = archive_base_url
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=12, max_keepalive_connections=6),
        )
        self._adaptive_profiles: dict[
            tuple[float, float], tuple[dict[str, dict[str, float]], float]
        ] = {}

    async def aclose(self) -> None:
        await self._client.aclose()

    def set_adaptive_profile(
        self,
        site: SiteConfig,
        *,
        weights_by_horizon: dict[str, dict[str, float]],
        spread_scale: float = 1.0,
    ) -> None:
        key = _site_key(site)
        bounded_scale = max(0.5, min(3.0, spread_scale))
        self._adaptive_profiles[key] = (weights_by_horizon, bounded_scale)

    async def forecast_members(
        self,
        site: SiteConfig,
        hours: int,
        *,
        models: tuple[str, ...] = (),
    ) -> dict[str, list[WeatherHour]]:
        if not models:
            points = await self._forecast_one(site, hours, model=None)
            return {"default": points} if points else {}
        responses = await asyncio.gather(
            *(self._forecast_one(site, hours, model=model) for model in models),
            return_exceptions=True,
        )
        return {
            model: response
            for model, response in zip(models, responses, strict=True)
            if isinstance(response, list) and response
        }

    async def forecast(
        self,
        site: SiteConfig,
        hours: int,
        *,
        models: tuple[str, ...] = (),
    ) -> list[WeatherHour]:
        members = await self.forecast_members(site, hours, models=models)
        if not members:
            return []
        if len(members) == 1:
            return next(iter(members.values()))[:hours]
        weights, spread_scale = self._adaptive_profiles.get(_site_key(site), ({}, 1.0))
        return _combine_ensemble(
            members,
            hours,
            weights_by_horizon=weights,
            spread_scale=spread_scale,
        )

    async def _forecast_one(
        self,
        site: SiteConfig,
        hours: int,
        *,
        model: str | None,
    ) -> list[WeatherHour]:
        params: dict[str, object] = {
            "latitude": site.latitude,
            "longitude": site.longitude,
            "hourly": "shortwave_radiation,cloud_cover,temperature_2m",
            "forecast_hours": hours,
            "timezone": "UTC",
        }
        if model:
            params["models"] = model
        response = await self._client.get(self._base_url, params=params)
        response.raise_for_status()
        return _parse_hourly(response.json(), hours)

    async def history(
        self,
        site: SiteConfig,
        start_date: date,
        end_date: date,
    ) -> list[WeatherHour]:
        response = await self._client.get(
            self._archive_base_url,
            params={
                "latitude": site.latitude,
                "longitude": site.longitude,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "hourly": "shortwave_radiation,cloud_cover,temperature_2m",
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        expected_hours = max(1, (end_date - start_date).days + 1) * 24
        return _parse_hourly(response.json(), expected_hours)


def _site_key(site: SiteConfig) -> tuple[float, float]:
    return round(site.latitude, 5), round(site.longitude, 5)


def _parse_hourly(payload: dict, hours: int) -> list[WeatherHour]:
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    radiation = hourly.get("shortwave_radiation", [])
    clouds = hourly.get("cloud_cover", [])
    temperatures = hourly.get("temperature_2m", [])
    result: list[WeatherHour] = []
    for index, raw_time in enumerate(times[:hours]):
        result.append(
            WeatherHour(
                timestamp=_utc_datetime(raw_time),
                shortwave_radiation_w_m2=max(0.0, _optional_float(radiation, index) or 0.0),
                cloud_cover_percent=_optional_float(clouds, index),
                temperature_c=_optional_float(temperatures, index),
            )
        )
    return result


def _horizon_bucket(index: int) -> str:
    if index < 12:
        return "0-12h"
    if index < 36:
        return "12-36h"
    if index < 72:
        return "36-72h"
    return "72h+"


def _normalized_weights(
    model_names: list[str],
    index: int,
    weights_by_horizon: dict[str, dict[str, float]],
) -> list[float]:
    configured = weights_by_horizon.get(_horizon_bucket(index), {})
    raw = [max(0.0, configured.get(model, 0.0)) for model in model_names]
    if sum(raw) <= 1e-9:
        return [1.0 / len(model_names)] * len(model_names)
    total = sum(raw)
    return [value / total for value in raw]


def _weighted_mean(values: list[float], weights: list[float]) -> float:
    return sum(value * weight for value, weight in zip(values, weights, strict=True))


def _weighted_stddev(values: list[float], weights: list[float], mean: float) -> float:
    variance = sum(
        weight * (value - mean) ** 2
        for value, weight in zip(values, weights, strict=True)
    )
    return math.sqrt(max(0.0, variance))


def _combine_ensemble(
    series: dict[str, list[WeatherHour]],
    hours: int,
    *,
    weights_by_horizon: dict[str, dict[str, float]] | None = None,
    spread_scale: float = 1.0,
) -> list[WeatherHour]:
    by_time: dict[datetime, dict[str, WeatherHour]] = {}
    for model, forecast in series.items():
        for point in forecast[:hours]:
            by_time.setdefault(point.timestamp, {})[model] = point

    combined: list[WeatherHour] = []
    profile = weights_by_horizon or {}
    for index, timestamp in enumerate(sorted(by_time)[:hours]):
        members = by_time[timestamp]
        names = sorted(members)
        weights = _normalized_weights(names, index, profile)
        radiation = [members[name].shortwave_radiation_w_m2 for name in names]
        radiation_mean = _weighted_mean(radiation, weights)
        clouds = [members[name].cloud_cover_percent for name in names]
        temperatures = [members[name].temperature_c for name in names]

        def optional_weighted(values: list[float | None]) -> float | None:
            present = [
                (value, weight)
                for value, weight in zip(values, weights, strict=True)
                if value is not None
            ]
            if not present:
                return None
            total = sum(weight for _, weight in present) or 1.0
            return sum(float(value) * weight for value, weight in present) / total

        combined.append(
            WeatherHour(
                timestamp=timestamp,
                shortwave_radiation_w_m2=radiation_mean,
                shortwave_radiation_spread_w_m2=(
                    _weighted_stddev(radiation, weights, radiation_mean)
                    * max(0.5, min(3.0, spread_scale))
                ),
                cloud_cover_percent=optional_weighted(clouds),
                temperature_c=optional_weighted(temperatures),
            )
        )
    return combined


def _optional_float(values: list, index: int) -> float | None:
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
