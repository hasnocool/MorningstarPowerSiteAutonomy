# src/powersite_autonomy/sentinel.py
from __future__ import annotations

from typing import Any

import httpx

from .models import SentinelFeedback


def _flatten_strings(value: Any) -> list[str]:
    result: list[str] = []
    if isinstance(value, str):
        result.append(value.lower())
    elif isinstance(value, dict):
        for key, nested in value.items():
            result.append(str(key).lower())
            result.extend(_flatten_strings(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(_flatten_strings(nested))
    return result


def _find_mapping(value: Any, keys: tuple[str, ...]) -> dict | None:
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if isinstance(candidate, dict):
                return candidate
        for nested in value.values():
            found = _find_mapping(nested, keys)
            if found is not None:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_mapping(nested, keys)
            if found is not None:
                return found
    return None


class SentinelClient:
    def __init__(self, base_url: str, *, timeout_seconds: float = 4.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=httpx.Timeout(timeout_seconds),
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_feedback(self, site_uid: str) -> SentinelFeedback:
        try:
            response = await self._client.get(f"/v1/sites/{site_uid}/assessment")
            if response.status_code == 404:
                return SentinelFeedback(reachable=True)
            response.raise_for_status()
        except httpx.HTTPError:
            return SentinelFeedback(
                reachable=False,
                forecast_uncertainty_multiplier=1.15,
                evidence_codes=["sentinel_unreachable"],
            )

        payload = response.json()
        explicit = _find_mapping(payload, ("autonomy", "forecast_inputs", "forecast_feedback"))
        feedback = SentinelFeedback()
        if explicit is not None:
            if isinstance(explicit.get("telemetry_reliable"), bool):
                feedback.telemetry_reliable = explicit["telemetry_reliable"]
            if isinstance(explicit.get("soc_reliable"), bool):
                feedback.soc_reliable = explicit["soc_reliable"]
            if isinstance(explicit.get("forecast_uncertainty_multiplier"), (int, float)):
                feedback.forecast_uncertainty_multiplier = max(
                    1.0,
                    min(4.0, float(explicit["forecast_uncertainty_multiplier"])),
                )
            if isinstance(explicit.get("pv_derate_factor"), (int, float)):
                feedback.pv_derate_factor = max(
                    0.0,
                    min(1.0, float(explicit["pv_derate_factor"])),
                )

        text = " ".join(_flatten_strings(payload))
        evidence: list[str] = []
        if "stale_site_telemetry" in text or "stale site telemetry" in text:
            feedback.telemetry_reliable = False
            feedback.forecast_uncertainty_multiplier = max(
                feedback.forecast_uncertainty_multiplier,
                1.50,
            )
            evidence.append("stale_site_telemetry")
        if "offline_controller" in text or "offline controller" in text:
            feedback.telemetry_reliable = False
            feedback.forecast_uncertainty_multiplier = max(
                feedback.forecast_uncertainty_multiplier,
                1.35,
            )
            evidence.append("offline_controller")
        if ("conflict" in text and "soc" in text) or "battery_soc_conflict" in text:
            feedback.soc_reliable = False
            feedback.forecast_uncertainty_multiplier = max(
                feedback.forecast_uncertainty_multiplier,
                1.35,
            )
            evidence.append("battery_soc_conflict")
        feedback.evidence_codes = sorted(set([*feedback.evidence_codes, *evidence]))
        return feedback
