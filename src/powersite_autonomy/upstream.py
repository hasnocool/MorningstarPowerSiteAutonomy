# src/powersite_autonomy/upstream.py
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import HistoryPoint, SiteDescriptor


@dataclass(frozen=True, slots=True)
class SiteState:
    soc_percent: float | None
    load_power_w: float | None
    battery_voltage_v: float | None
    input_quality: dict[str, str]
    solar_power_w: float | None = None
    battery_current_a: float | None = None
    battery_temperature_c: float | None = None


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "resolved_value", "current", "reading", "mean", "avg"):
            result = _as_number(value.get(key))
            if result is not None:
                return result
    return None


def _find_metric(payload: Any, names: tuple[str, ...]) -> float | None:
    if isinstance(payload, dict):
        for name in names:
            if name in payload:
                result = _as_number(payload[name])
                if result is not None:
                    return result
        for value in payload.values():
            result = _find_metric(value, names)
            if result is not None:
                return result
    elif isinstance(payload, list):
        for value in payload:
            result = _find_metric(value, names)
            if result is not None:
                return result
    return None


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _extract_history_points(payload: Any) -> list[HistoryPoint]:
    points: list[HistoryPoint] = []
    seen: set[tuple[str, float]] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            timestamp = None
            for key in ("timestamp", "time", "bucket_start", "start", "observed_at"):
                timestamp = _parse_timestamp(value.get(key))
                if timestamp is not None:
                    break
            numeric = None
            for key in ("value", "resolved_value", "mean", "avg", "average"):
                numeric = _as_number(value.get(key))
                if numeric is not None:
                    break
            if timestamp is not None and numeric is not None:
                marker = (timestamp.isoformat(), numeric)
                if marker not in seen:
                    seen.add(marker)
                    quality = value.get("quality")
                    points.append(
                        HistoryPoint(
                            timestamp=timestamp,
                            value=numeric,
                            quality=str(quality) if quality is not None else None,
                        )
                    )
                return
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)
    points.sort(key=lambda point: point.timestamp)
    return points


class MorningstarClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 5.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def list_sites(self) -> list[SiteDescriptor]:
        response = await self._client.get("/v1/systems")
        response.raise_for_status()
        payload = response.json()
        items = (
            payload
            if isinstance(payload, list)
            else payload.get("systems", payload.get("items", []))
        )
        return [
            SiteDescriptor(
                site_uid=str(item.get("system_uid") or item.get("site_uid") or item.get("uid")),
                name=item.get("name"),
            )
            for item in items
            if isinstance(item, dict)
            and (item.get("system_uid") or item.get("site_uid") or item.get("uid"))
        ]

    async def get_site_state(self, site_uid: str) -> SiteState:
        latest, power_flow = await self._get_optional_pair(
            f"/v1/systems/{site_uid}/latest",
            f"/v1/systems/{site_uid}/power-flow",
        )
        payload = {"latest": latest, "power_flow": power_flow}

        soc = _find_metric(
            payload,
            ("battery_soc_percent", "state_of_charge_percent", "soc_percent"),
        )
        load = _find_metric(payload, ("system_load_power_w", "load_power_w", "dc_load_power_w"))
        voltage = _find_metric(payload, ("battery_voltage_v", "battery_voltage"))
        solar = _find_metric(
            payload,
            ("solar_input_power_w", "pv_power_w", "array_power_w", "charge_input_power_w"),
        )
        battery_current = _find_metric(
            payload,
            ("battery_net_current_a", "battery_current_a", "system_battery_current_a"),
        )
        battery_temperature = _find_metric(
            payload,
            ("battery_temperature_c", "battery_temp_c", "battery_temperature"),
        )
        if load is None:
            current = _find_metric(payload, ("system_load_current_a", "load_current_a"))
            load_voltage = _find_metric(payload, ("load_voltage_v", "load_voltage")) or voltage
            if current is not None and load_voltage is not None:
                load = max(0.0, current * load_voltage)

        return SiteState(
            soc_percent=soc,
            load_power_w=load,
            battery_voltage_v=voltage,
            solar_power_w=solar,
            battery_current_a=battery_current,
            battery_temperature_c=battery_temperature,
            input_quality={
                "battery_soc": "measured" if soc is not None else "fallback",
                "load_power": "measured_or_derived" if load is not None else "fallback",
                "solar_power": "measured" if solar is not None else "unavailable",
                "battery_temperature": (
                    "measured" if battery_temperature is not None else "fallback_or_unavailable"
                ),
            },
        )

    async def get_history(
        self,
        site_uid: str,
        metric: str,
        *,
        resolution: str = "1h",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[HistoryPoint]:
        params: dict[str, str] = {"metric": metric, "resolution": resolution}
        if start is not None:
            params["start"] = start.astimezone(UTC).isoformat()
        if end is not None:
            params["end"] = end.astimezone(UTC).isoformat()
        response = await self._client.get(f"/v1/systems/{site_uid}/history", params=params)
        if response.status_code in {400, 404, 422}:
            return []
        response.raise_for_status()
        return _extract_history_points(response.json())

    async def get_history_bundle(
        self,
        site_uid: str,
        metrics: tuple[str, ...],
        *,
        resolution: str = "1h",
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, list[HistoryPoint]]:
        results = await asyncio.gather(
            *(
                self.get_history(
                    site_uid,
                    metric,
                    resolution=resolution,
                    start=start,
                    end=end,
                )
                for metric in metrics
            )
        )
        return dict(zip(metrics, results, strict=True))

    async def get_component_graph(self, site_uid: str) -> dict:
        return await self._get_optional_json(f"/v1/systems/{site_uid}/component-graph")

    async def get_energy_ledger(self, site_uid: str) -> dict:
        return await self._get_optional_json(f"/v1/systems/{site_uid}/energy-ledger")

    async def _get_optional_pair(self, first: str, second: str) -> tuple[dict, dict]:
        a, b = await asyncio.gather(
            self._get_optional_json(first),
            self._get_optional_json(second),
        )
        return a, b

    async def _get_optional_json(self, path: str) -> dict:
        response = await self._client.get(path)
        if response.status_code == 404:
            return {}
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {"items": payload}
