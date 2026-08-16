# tests/test_shadow_autopilot.py
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from powersite_autonomy.forecast import ForecastInputs
from powersite_autonomy.models import HistoryPoint, SiteCalibration, SiteConfig, WeatherHour
from powersite_autonomy.shadow_counterfactual import evaluate_shadow_plan
from powersite_autonomy.shadow_feedback import apply_model_feedback, detect_change_point
from powersite_autonomy.shadow_models import EnergyPolicy, ManagedLoad, ModelFeedback
from powersite_autonomy.shadow_planning import build_shadow_plan
from powersite_autonomy.shadow_storage import ShadowStorage
from powersite_autonomy.upstream import SiteState


def _site() -> SiteConfig:
    return SiteConfig(
        array_watts=1000,
        battery_capacity_wh=4000,
        reserve_percent=25,
        latitude=48.4,
        longitude=-123.3,
        load_watts_fallback=100,
    )


def _inputs(hours: int = 24) -> ForecastInputs:
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=12)
    weather = [
        WeatherHour(
            timestamp=start + timedelta(hours=index),
            shortwave_radiation_w_m2=700 if 7 <= index % 24 <= 18 else 0,
            cloud_cover_percent=20,
            temperature_c=20,
        )
        for index in range(hours)
    ]
    return ForecastInputs(
        site_uid="sys_default",
        config=_site(),
        state=SiteState(
            65,
            100,
            13.2,
            {"battery_soc": "measured", "load_power": "measured"},
        ),
        weather=weather,
    )


def _plan():
    return build_shadow_plan(
        _inputs(),
        EnergyPolicy(target_reserve_breach_probability=0.20),
        [
            ManagedLoad(
                load_id="batch",
                power_w=100,
                energy_required_wh=200,
                earliest_start_hour=2,
                deadline_hour=18,
                interruptible=True,
            )
        ],
        samples=60,
        model_epoch_id="epoch-test",
    )


def test_shadow_plan_is_multi_objective_and_never_executable() -> None:
    plan = _plan()
    assert plan.read_only is True
    assert plan.executable is False
    assert len(plan.alternatives) == 3
    assert {item.name for item in plan.alternatives} == {
        "conservative",
        "balanced",
        "maximum_utilization",
    }
    assert all(action.executable is False for action in plan.actions)
    assert all(action.requires_operator_approval for action in plan.actions)


def test_counterfactual_replay_scores_shadow_against_hindsight() -> None:
    plan = _plan()
    timeline = [point.timestamp for point in plan.baseline.points[:13]]
    history = {
        "solar_input_power_w": [
            HistoryPoint(timestamp=timestamp, value=350 if 8 <= index <= 11 else 0)
            for index, timestamp in enumerate(timeline)
        ],
        "system_load_power_w": [
            HistoryPoint(timestamp=timestamp, value=100)
            for timestamp in timeline
        ],
        "battery_soc_percent": [
            HistoryPoint(timestamp=timestamp, value=65 - index * 0.5)
            for index, timestamp in enumerate(timeline)
        ],
    }
    result = evaluate_shadow_plan(plan, history, _site())
    assert result.observed_hours >= 12
    assert result.decision_regret >= 0
    assert result.regret_percent >= 0
    assert result.feedback.sample_count >= 12


def test_feedback_is_bounded_and_change_points_create_new_epoch() -> None:
    calibration = SiteCalibration(
        site_uid="sys_default",
        generated_at=datetime.now(UTC),
        history_days=30,
        hourly_load_profile_w=[100.0] * 24,
        hourly_load_sigma_w=[10.0] * 24,
        weekday_load_multiplier=[1.0] * 7,
        pv_scale_factor=1.0,
        pv_scale_by_hour=[1.0] * 24,
    )
    feedback = ModelFeedback(
        site_uid="sys_default",
        plan_id="plan",
        sample_count=24,
        confidence=1.0,
        recommended_pv_scale_multiplier=1.4,
        recommended_load_scale_multiplier=1.3,
    )
    adjusted = apply_model_feedback(calibration, feedback, max_adjustment_fraction=0.05)
    assert adjusted is not None
    assert adjusted.pv_scale_factor == pytest.approx(1.05)
    assert adjusted.hourly_load_profile_w[0] == pytest.approx(105.0)

    changed = calibration.model_copy(update={"pv_scale_factor": 1.30})
    epoch = detect_change_point("sys_default", calibration, changed)
    assert epoch is not None
    assert epoch.reason == "pv_change_point"


@pytest.mark.asyncio
async def test_shadow_ledger_moves_actions_to_evaluated(tmp_path) -> None:
    storage = ShadowStorage(str(tmp_path / "autonomy.db"))
    await storage.initialize()
    plan = _plan()
    await storage.save_plan(plan)
    pending = await storage.pending_plans(
        "sys_default",
        datetime.now(UTC) + timedelta(hours=1),
    )
    assert [item.plan_id for item in pending] == [plan.plan_id]

    timeline = [point.timestamp for point in plan.baseline.points[:13]]
    history = {
        "solar_input_power_w": [
            HistoryPoint(timestamp=timestamp, value=300) for timestamp in timeline
        ],
        "system_load_power_w": [
            HistoryPoint(timestamp=timestamp, value=100) for timestamp in timeline
        ],
        "battery_soc_percent": [
            HistoryPoint(timestamp=timestamp, value=60) for timestamp in timeline
        ],
    }
    evaluation = evaluate_shadow_plan(plan, history, _site())
    await storage.save_evaluation(evaluation)
    actions = await storage.recent_actions("sys_default")
    assert actions
    assert all(item["status"] == "evaluated" for item in actions)
    assert await storage.pending_plans(
        "sys_default",
        datetime.now(UTC) + timedelta(hours=1),
    ) == []
