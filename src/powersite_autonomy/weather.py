# src/powersite_autonomy/weather.py
from __future__ import annotations

import asyncio
import statistics
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

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forecast(
        self,
        site: SiteConfig,
        hours: int,
        *,
        models: tuple[str, ...] = (),
    ) -> list[WeatherHour]:
        if not models:
            return await self._forecast_one(site, hours, model=None)

        responses = await asyncio.gather(
            *(self._forecast_one(site, hours, model=model) for model in models),
            return_exceptions=True,
        )
        successful = [item for item in responses if isinstance(item, list) and item]
        if not successful:
            error = next((item for item in responses if isinstance(item, Exception)), None)
            if error is not None:
                raise error
            return []
        return _combine_ensemble(successful, hours)

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


def _combine_ensemble(series: list[list[WeatherHour]], hours: int) -> list[WeatherHour]:
    by_time: dict[datetime, list[WeatherHour]] = {}
    for forecast in series:
        for point in forecast[:hours]:
            by_time.setdefault(point.timestamp, []).append(point)

    combined: list[WeatherHour] = []
    for timestamp in sorted(by_time)[:hours]:
        members = by_time[timestamp]
        radiation = [member.shortwave_radiation_w_m2 for member in members]
        clouds = [
            member.cloud_cover_percent
            for member in members
            if member.cloud_cover_percent is not None
        ]
        temperatures = [
            member.temperature_c for member in members if member.temperature_c is not None
        ]
        combined.append(
            WeatherHour(
                timestamp=timestamp,
                shortwave_radiation_w_m2=statistics.fmean(radiation),
                shortwave_radiation_spread_w_m2=(
                    statistics.pstdev(radiation) if len(radiation) >= 2 else 0.0
                ),
                cloud_cover_percent=statistics.fmean(clouds) if clouds else None,
                temperature_c=statistics.fmean(temperatures) if temperatures else None,
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
