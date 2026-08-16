from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from .models import SiteDescriptor


@dataclass(frozen=True, slots=True)
class SiteState:
    soc_percent: float | None
    load_power_w: float | None
    battery_voltage_v: float | None
    input_quality: dict[str, str]


def _as_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, dict):
        for key in ("value", "resolved_value", "current", "reading"):
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
            payload, ("battery_soc_percent", "state_of_charge_percent", "soc_percent")
        )
        load = _find_metric(payload, ("system_load_power_w", "load_power_w", "dc_load_power_w"))
        voltage = _find_metric(payload, ("battery_voltage_v", "battery_voltage"))
        if load is None:
            current = _find_metric(payload, ("system_load_current_a", "load_current_a"))
            load_voltage = _find_metric(payload, ("load_voltage_v", "load_voltage")) or voltage
            if current is not None and load_voltage is not None:
                load = max(0.0, current * load_voltage)

        return SiteState(
            soc_percent=soc,
            load_power_w=load,
            battery_voltage_v=voltage,
            input_quality={
                "battery_soc": "measured" if soc is not None else "fallback",
                "load_power": "measured_or_derived" if load is not None else "fallback",
            },
        )

    async def _get_optional_pair(self, first: str, second: str) -> tuple[dict, dict]:
        import asyncio

        async def fetch(path: str) -> dict:
            response = await self._client.get(path)
            if response.status_code == 404:
                return {}
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else {"items": payload}

        a, b = await asyncio.gather(fetch(first), fetch(second))
        return a, b
