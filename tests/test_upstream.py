# tests/test_upstream.py
from datetime import UTC, datetime

import httpx

from powersite_autonomy.upstream import MorningstarClient, _find_metric


def test_find_metric_tolerates_nested_normalized_shapes() -> None:
    payload = {"metrics": {"battery_soc_percent": {"quality": "complete", "value": 73.5}}}
    assert _find_metric(payload, ("battery_soc_percent",)) == 73.5


async def test_history_uses_documented_range_parameters() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "points": [
                    {
                        "bucket_start": "2026-08-16T00:00:00+00:00",
                        "avg": 420.0,
                        "quality": "complete",
                    }
                ]
            },
        )

    client = MorningstarClient("http://morningstar.test")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="http://morningstar.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        points = await client.get_history(
            "sys_default",
            "solar_input_power_w",
            start=datetime(2026, 8, 1, tzinfo=UTC),
            end=datetime(2026, 8, 17, tzinfo=UTC),
        )
    finally:
        await client.aclose()

    assert len(points) == 1
    assert requests[0].url.params["from"] == "2026-08-01T00:00:00+00:00"
    assert requests[0].url.params["to"] == "2026-08-17T00:00:00+00:00"
    assert "start" not in requests[0].url.params
    assert "end" not in requests[0].url.params


async def test_history_bundle_skips_metrics_not_in_api_catalog() -> None:
    requested_history_metrics: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/systems/metrics/catalog":
            return httpx.Response(
                200,
                json=[
                    {"name": "solar_input_power_w"},
                    {"name": "system_load_current_a"},
                ],
            )
        if request.url.path == "/v1/systems/sys_default/history":
            requested_history_metrics.append(request.url.params["metric"])
            return httpx.Response(200, json={"points": []})
        return httpx.Response(404)

    client = MorningstarClient("http://morningstar.test")
    await client._client.aclose()
    client._client = httpx.AsyncClient(
        base_url="http://morningstar.test",
        transport=httpx.MockTransport(handler),
    )
    try:
        bundle = await client.get_history_bundle(
            "sys_default",
            ("solar_input_power_w", "system_load_power_w"),
        )
    finally:
        await client.aclose()

    assert requested_history_metrics == ["solar_input_power_w"]
    assert bundle["solar_input_power_w"] == []
    assert bundle["system_load_power_w"] == []
