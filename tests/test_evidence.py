# tests/test_evidence.py
from __future__ import annotations

import pytest

from powersite_autonomy.evidence import (
    DecisionAlternative,
    EvidenceAnalysisRequest,
    EvidenceKind,
    EvidenceObservation,
    EvidenceOpportunity,
    ParameterBelief,
    SensitivityCase,
    StabilityLevel,
    TwinCandidate,
    analyze_evidence,
    expected_information_gain,
    run_tournament,
    update_belief,
)
from powersite_autonomy.evidence_service import EvidenceIntelligenceService


def test_belief_update_reduces_uncertainty() -> None:
    prior = ParameterBelief(
        name="battery_usable_capacity_ah",
        mean=300.0,
        stddev=30.0,
        minimum=0.0,
        confidence=0.4,
        provenance=[EvidenceKind.CONFIGURED],
    )
    observation = EvidenceObservation(
        parameter=prior.name,
        value=270.0,
        stddev=10.0,
        quality=0.9,
        kind=EvidenceKind.MEASURED,
    )

    posterior = update_belief(prior, observation)

    assert 270.0 < posterior.mean < 300.0
    assert posterior.stddev < prior.stddev
    assert posterior.confidence > prior.confidence
    assert posterior.sample_count == 1
    assert EvidenceKind.MEASURED in posterior.provenance


def test_information_gain_prioritizes_precise_high_impact_evidence() -> None:
    belief = ParameterBelief(name="pv_efficiency", mean=0.9, stddev=0.12)
    opportunity = EvidenceOpportunity(
        opportunity_id="clear-sky-midday",
        parameter="pv_efficiency",
        observation_stddev=0.03,
        economic_impact=2.0,
    )

    result = expected_information_gain(belief, opportunity)

    assert result.expected_stddev < result.current_stddev
    assert result.expected_information_gain > 0
    assert result.priority_score > result.expected_information_gain


def test_challenger_requires_margin_and_minimum_history() -> None:
    result = run_tournament(
        [
            TwinCandidate(
                twin_id="champion",
                prediction_error=0.5,
                evaluation_count=30,
                is_champion=True,
            ),
            TwinCandidate(
                twin_id="challenger",
                prediction_error=0.05,
                evaluation_count=3,
            ),
        ]
    )

    assert result is not None
    assert result.champion_id == "champion"
    assert result.promoted is False
    assert "insufficient" in result.promotion_reason


def test_mature_challenger_can_be_promoted() -> None:
    result = run_tournament(
        [
            TwinCandidate(
                twin_id="champion",
                prediction_error=1.0,
                evaluation_count=30,
                is_champion=True,
            ),
            TwinCandidate(
                twin_id="challenger",
                prediction_error=0.01,
                evaluation_count=30,
            ),
        ]
    )

    assert result is not None
    assert result.champion_id == "challenger"
    assert result.promoted is True


def test_analysis_marks_sensitive_purchase_as_low_stability() -> None:
    analysis = analyze_evidence(
        EvidenceAnalysisRequest(
            beliefs=[
                ParameterBelief(
                    name="battery_capacity",
                    mean=280.0,
                    stddev=35.0,
                    confidence=0.45,
                )
            ],
            opportunities=[
                EvidenceOpportunity(
                    opportunity_id="overnight-discharge",
                    parameter="battery_capacity",
                    observation_stddev=8.0,
                    economic_impact=3.0,
                )
            ],
            alternatives=[
                DecisionAlternative(name="add-100ah", expected_value=500.0),
                DecisionAlternative(name="do-nothing", expected_value=470.0),
            ],
            sensitivity_cases=[
                SensitivityCase(
                    parameter="battery_capacity",
                    low_value=240.0,
                    high_value=310.0,
                    low_winner="add-100ah",
                    high_winner="do-nothing",
                    changes_decision=True,
                    sensitivity=0.95,
                )
            ],
            current_recommendation_cost=480.0,
        )
    )

    assert analysis.stability is not None
    assert analysis.stability.recommendation_stability is StabilityLevel.LOW
    assert "battery_capacity" in analysis.stability.unstable_parameters
    assert analysis.value_of_information[0].expected_value > 0
    assert "wait" in analysis.value_of_information[0].recommendation


@pytest.mark.asyncio
async def test_async_service_keeps_public_contract() -> None:
    service = EvidenceIntelligenceService()
    request = EvidenceAnalysisRequest(
        beliefs=[ParameterBelief(name="base_load_w", mean=100.0, stddev=20.0)]
    )

    analysis = await service.analyze(request)

    assert analysis.beliefs[0].name == "base_load_w"
