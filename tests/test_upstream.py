# tests/test_upstream.py
from powersite_autonomy.upstream import _find_metric


def test_find_metric_tolerates_nested_normalized_shapes() -> None:
    payload = {"metrics": {"battery_soc_percent": {"quality": "complete", "value": 73.5}}}
    assert _find_metric(payload, ("battery_soc_percent",)) == 73.5
