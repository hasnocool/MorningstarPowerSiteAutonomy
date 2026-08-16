from __future__ import annotations

from datetime import UTC, datetime

import httpx

from .models import SiteConfig, WeatherHour


class WeatherClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 8.0) -> None:
        self._base_url = base_url
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forecast(self, site: SiteConfig, hours: int) -> list[WeatherHour]:
        response = await self._client.get(
            self._base_url,
            params={
                "latitude": site.latitude,
                "longitude": site.longitude,
                "hourly": "shortwave_radiation,cloud_cover,temperature_2m",
                "forecast_hours": hours,
                "timezone": "UTC",
            },
        )
        response.raise_for_status()
        payload = response.json().get("hourly", {})
        times = payload.get("time", [])
        radiation = payload.get("shortwave_radiation", [])
        clouds = payload.get("cloud_cover", [])
        temperatures = payload.get("temperature_2m", [])
        result: list[WeatherHour] = []
        for index, raw_time in enumerate(times[:hours]):
            result.append(
                WeatherHour(
                    timestamp=_utc_datetime(raw_time),
                    shortwave_radiation_w_m2=max(0.0, float(radiation[index] or 0.0)),
                    cloud_cover_percent=_optional_float(clouds, index),
                    temperature_c=_optional_float(temperatures, index),
                )
            )
        return result


def _optional_float(values: list, index: int) -> float | None:
    if index >= len(values) or values[index] is None:
        return None
    return float(values[index])


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
