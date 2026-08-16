from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from powersite_autonomy.forecast import ForecastInputs
from powersite_autonomy.models import HistoryPoint, SiteConfig, WeatherHour
from powersite_autonomy.policy_learning import (
    build_decision_sensitivity,
    build_policy_frontier,
    choose_policy_tournament,
    evaluate_policy_candidate,
    generate_policy_candidates,
    initial_candidate,
    recommend_dynamic_reserve,
)
from powersite_autonomy.policy_models import PolicyEvaluation, PolicySearchBounds
from powersite_autonomy.policy_storage import PolicyLabStorage
from powersite_autonomy.shadow_counterfactual import evaluate_shadow_plan
from powersite_autonomy.shadow_models import EnergyPolicy, ManagedLoad
from powersite_autonomy.shadow_planning import build_shadow_plan
from powersite_autonomy.upstream import SiteState


def _site() -> SiteConfig:
    return SiteConfig(
        array_watts=1000,
        battery_capacity_wh=4000,
        reserve_percent=25,
        latitude=48.4,
        longitude=-123.3,
        load_watts_fallback=120,
    )


def _plan():
    start = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(hours=12)
    weather = [
        WeatherHour(
            timestamp=start + timedelta(hours=index),
            shortwave_radiation_w_m2=650 if 7 <= index % 24 <= 18 else 0,
            cloud_cover_percent=30,
            temperature_c=18,
        )
        for index in range(24)
    ]
    inputs = ForecastInputs(
        site_uid="sys_default",
        config=_site(),
        state=SiteState(
            65,
            120,
            13.2,
            {"battery_soc": "measured", "load_power": "measured"},
        ),
        weather=weather,
    )
    return build_shadow_plan(
        inputs,
        EnergyPolicy(target_reserve_breach_probability=0.20),
        [
            ManagedLoad(
                load_id="batch",
                power_w=100,
                energy_required_wh=300,
                earliest_start_hour=2,
                deadline_hour=18,
                interruptible=True,
            )
        ],
        samples=60,
        model_epoch_id="epoch-policy-test",
    )


def _evaluation(plan):
    timeline = [point.timestamp for point in plan.baseline.points[:13]]
    history = {
        "solar_input_power_w": [
            HistoryPoint(timestamp=timestamp, value=350 if 7 <= index <= 11 else 0)
            for index, timestamp in enumerate(timeline)
        ],
        "system_load_power_w": [
            HistoryPoint(timestamp=timestamp, value=120) for timestamp in timeline
        ],
        "battery_soc_percent": [
            HistoryPoint(timestamp=timestamp, value=65 - index * 0.6)
            for index, timestamp in enumerate(timeline)
        ],
    }
    return evaluate_shadow_plan(plan, history, _site())


def test_candidates_are_bounded_and_dynamic_reserve_is_read_only() -> None:
    plan = _plan()
    champion = initial_candidate("sys_default", plan.policy)
    candidates = generate_policy_candidates(champion, PolicySearchBounds())
    assert len(candidates) >= 6
    assert candidates[0].status == "champion"
    assert all(
        item.policy.emergency_reserve_percent < item.policy.minimum_reserve_percent
        for item in candidates
    )
    assert all(10 <= item.policy.minimum_reserve_percent <= 60 for item in candidates)

    reserve = recommend_dynamic_reserve("sys_default", plan, champion.policy)
    assert reserve.read_only is True
    assert reserve.effective_reserve_percent >= champion.policy.emergency_reserve_percent + 2
    assert reserve.horizon_targets


def test_point_in_time_policy_replay_uses_persisted_plan_alternatives() -> None:
    plan = _plan()
    evaluation = _evaluation(plan)
    champion = initial_candidate("sys_default", plan.policy)
    challenger = generate_policy_candidates(champion, PolicySearchBounds())[1]
    result = evaluate_policy_candidate(
        challenger,
        [plan],
        [evaluation],
        fallback_policy=champion.policy,
    )
    assert result.evaluation_count == 1
    assert plan.plan_id in result.sample_scores
    assert result.mean_score is not None
    assert result.mean_score >= 0


def test_tournament_promotes_only_high_confidence_safe_improvement() -> None:
    champion = initial_candidate("sys_default", EnergyPolicy())
    challenger = generate_policy_candidates(champion, PolicySearchBounds())[1]
    plan_ids = [f"plan-{index}" for index in range(12)]
    champion_eval = PolicyEvaluation(
        site_uid="sys_default",
        policy_id=champion.policy_id,
        evaluation_count=12,
        mean_score=100.0,
        median_score=100.0,
        sample_scores={plan_id: 100.0 for plan_id in plan_ids},
    )
    challenger_eval = PolicyEvaluation(
        site_uid="sys_default",
        policy_id=challenger.policy_id,
        evaluation_count=12,
        mean_score=75.0,
        median_score=75.0,
        sample_scores={plan_id: 75.0 for plan_id in plan_ids},
    )
    decision = choose_policy_tournament(
        "sys_default",
        champion,
        [champion, challenger],
        [champion_eval, challenger_eval],
        minimum_replays=6,
        promotion_margin=0.08,
        bootstrap_samples=200,
    )
    assert decision.promoted is True
    assert decision.champion_after == challenger.policy_id
    assert decision.safety_gate_passed is True

    unsafe = challenger_eval.model_copy(update={"predicted_emergency_breaches": 1})
    blocked = choose_policy_tournament(
        "sys_default",
        champion,
        [champion, challenger],
        [champion_eval, unsafe],
        minimum_replays=6,
        promotion_margin=0.08,
        bootstrap_samples=200,
    )
    assert blocked.promoted is False
    assert blocked.safety_gate_passed is False


def test_policy_frontier_removes_dominated_candidates() -> None:
    champion = initial_candidate("sys_default", EnergyPolicy())
    challenger = generate_policy_candidates(champion, PolicySearchBounds())[1]
    best = PolicyEvaluation(
        site_uid="sys_default",
        policy_id=champion.policy_id,
        evaluation_count=10,
        mean_score=50,
        auxiliary_energy_wh=100,
        deferred_load_wh=100,
        battery_throughput_wh=100,
    )
    dominated = PolicyEvaluation(
        site_uid="sys_default",
        policy_id=challenger.policy_id,
        evaluation_count=10,
        mean_score=80,
        predicted_emergency_breaches=1,
        auxiliary_energy_wh=200,
        deferred_load_wh=200,
        battery_throughput_wh=200,
    )
    frontier = build_policy_frontier(
        "sys_default",
        [champion, challenger],
        [best, dominated],
    )
    assert [item.policy_id for item in frontier.points] == [champion.policy_id]


def test_decision_sensitivity_ranks_errors_by_decision_impact() -> None:
    plan = _plan()
    evaluation = _evaluation(plan)
    summary = build_decision_sensitivity("sys_default", [evaluation])
    assert summary.signals
    assert all(item.priority_score >= 0 for item in summary.signals)


@pytest.mark.asyncio
async def test_policy_registry_round_trip(tmp_path) -> None:
    storage = PolicyLabStorage(str(tmp_path / "autonomy.db"))
    champion = initial_candidate("sys_default", EnergyPolicy())
    await storage.set_champion(champion)
    loaded = await storage.champion("sys_default")
    assert loaded is not None
    assert loaded.policy_id == champion.policy_id

    evaluation = PolicyEvaluation(
        site_uid="sys_default",
        policy_id=champion.policy_id,
        evaluation_count=1,
        mean_score=10,
        sample_scores={"plan": 10},
    )
    await storage.save_candidate(champion)
    await storage.save_evaluation(evaluation)
    assert (await storage.recent_candidates("sys_default"))[0].policy_id == champion.policy_id
    assert (await storage.recent_evaluations("sys_default"))[0].mean_score == 10
