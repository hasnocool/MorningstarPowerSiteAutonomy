# src/powersite_autonomy/evidence.py
from __future__ import annotations

import math
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

_EPSILON = 1e-9


class StabilityLevel(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class EvidenceKind(StrEnum):
    MEASURED = "measured"
    DERIVED = "derived"
    CONFIGURED = "configured"
    LEARNED = "learned"
    FLEET_PRIOR = "fleet_prior"
    FORECAST = "forecast"


class ParameterBelief(BaseModel):
    name: str
    mean: float
    stddev: float = Field(gt=0)
    minimum: float | None = None
    maximum: float | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    sample_count: int = Field(default=0, ge=0)
    provenance: list[EvidenceKind] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_bounds(self) -> ParameterBelief:
        if self.minimum is not None and self.maximum is not None:
            if self.minimum > self.maximum:
                raise ValueError("minimum must not exceed maximum")
        return self

    def bounded_mean(self, value: float) -> float:
        if self.minimum is not None:
            value = max(self.minimum, value)
        if self.maximum is not None:
            value = min(self.maximum, value)
        return value

    @property
    def p10(self) -> float:
        return self.bounded_mean(self.mean - 1.2815515655 * self.stddev)

    @property
    def p50(self) -> float:
        return self.bounded_mean(self.mean)

    @property
    def p90(self) -> float:
        return self.bounded_mean(self.mean + 1.2815515655 * self.stddev)


class EvidenceObservation(BaseModel):
    parameter: str
    value: float
    stddev: float = Field(gt=0)
    kind: EvidenceKind = EvidenceKind.MEASURED
    quality: float = Field(default=1.0, gt=0, le=1)
    source: str | None = None


class Hypothesis(BaseModel):
    hypothesis_id: str
    description: str
    probability: float = Field(ge=0, le=1)
    affected_parameters: list[str] = Field(default_factory=list)
    supporting_evidence: list[str] = Field(default_factory=list)
    contradicting_evidence: list[str] = Field(default_factory=list)


class TwinCandidate(BaseModel):
    twin_id: str
    parameters: dict[str, float] = Field(default_factory=dict)
    prior_weight: float = Field(default=1.0, gt=0)
    prediction_error: float = Field(default=0.0, ge=0)
    evaluation_count: int = Field(default=0, ge=0)
    is_champion: bool = False


class TwinScore(BaseModel):
    twin_id: str
    posterior_weight: float = Field(ge=0, le=1)
    prediction_error: float = Field(ge=0)
    evaluation_count: int = Field(ge=0)
    is_champion: bool


class TournamentResult(BaseModel):
    scores: list[TwinScore]
    champion_id: str
    promoted: bool
    promotion_reason: str


class EvidenceOpportunity(BaseModel):
    opportunity_id: str
    parameter: str
    observation_stddev: float = Field(gt=0)
    economic_impact: float = Field(default=0, ge=0)
    description: str = ""


class InformationGainResult(BaseModel):
    opportunity_id: str
    parameter: str
    expected_information_gain: float = Field(ge=0)
    current_stddev: float = Field(gt=0)
    expected_stddev: float = Field(gt=0)
    priority_score: float = Field(ge=0)
    description: str


class DecisionAlternative(BaseModel):
    name: str
    expected_value: float
    model_score: float = 0.0


class SensitivityCase(BaseModel):
    parameter: str
    low_value: float
    high_value: float
    low_winner: str
    high_winner: str
    changes_decision: bool
    sensitivity: float = Field(ge=0, le=1)


class RecommendationStability(BaseModel):
    recommended: str
    runner_up: str | None
    decision_confidence: float = Field(ge=0, le=1)
    model_confidence: float = Field(ge=0, le=1)
    recommendation_stability: StabilityLevel
    value_margin: float
    unstable_parameters: list[str] = Field(default_factory=list)


class ValueOfInformation(BaseModel):
    opportunity_id: str
    expected_value: float
    recommendation: str


class EvidenceAnalysisRequest(BaseModel):
    beliefs: list[ParameterBelief]
    observations: list[EvidenceObservation] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    twins: list[TwinCandidate] = Field(default_factory=list)
    opportunities: list[EvidenceOpportunity] = Field(default_factory=list)
    alternatives: list[DecisionAlternative] = Field(default_factory=list)
    sensitivity_cases: list[SensitivityCase] = Field(default_factory=list)
    current_recommendation_cost: float = Field(default=0, ge=0)


class EvidenceAnalysis(BaseModel):
    beliefs: list[ParameterBelief]
    hypotheses: list[Hypothesis]
    tournament: TournamentResult | None
    information_gain: list[InformationGainResult]
    stability: RecommendationStability | None
    value_of_information: list[ValueOfInformation]


def update_belief(
    belief: ParameterBelief,
    observation: EvidenceObservation,
) -> ParameterBelief:
    if belief.name != observation.parameter:
        raise ValueError("observation parameter does not match belief")

    prior_variance = belief.stddev**2
    observation_variance = (observation.stddev / observation.quality) ** 2
    prior_precision = 1.0 / prior_variance
    observation_precision = 1.0 / observation_variance
    posterior_variance = 1.0 / (prior_precision + observation_precision)
    posterior_mean = posterior_variance * (
        prior_precision * belief.mean + observation_precision * observation.value
    )
    posterior_stddev = math.sqrt(posterior_variance)
    information_fraction = 1.0 - min(1.0, posterior_stddev / belief.stddev)
    confidence = min(
        0.999,
        belief.confidence + (1.0 - belief.confidence) * information_fraction,
    )
    provenance = list(dict.fromkeys([*belief.provenance, observation.kind]))
    return belief.model_copy(
        update={
            "mean": belief.bounded_mean(posterior_mean),
            "stddev": posterior_stddev,
            "confidence": confidence,
            "sample_count": belief.sample_count + 1,
            "provenance": provenance,
        }
    )


def expected_information_gain(
    belief: ParameterBelief,
    opportunity: EvidenceOpportunity,
) -> InformationGainResult:
    prior_variance = belief.stddev**2
    observation_variance = opportunity.observation_stddev**2
    posterior_variance = 1.0 / (
        1.0 / prior_variance + 1.0 / observation_variance
    )
    posterior_stddev = math.sqrt(posterior_variance)
    information_gain = max(0.0, math.log(belief.stddev / posterior_stddev))
    priority = information_gain * (1.0 + opportunity.economic_impact)
    return InformationGainResult(
        opportunity_id=opportunity.opportunity_id,
        parameter=opportunity.parameter,
        expected_information_gain=information_gain,
        current_stddev=belief.stddev,
        expected_stddev=posterior_stddev,
        priority_score=priority,
        description=opportunity.description,
    )


def run_tournament(
    twins: list[TwinCandidate],
    *,
    promotion_margin: float = 0.08,
    min_evaluations: int = 5,
) -> TournamentResult | None:
    if not twins:
        return None

    champion = next((candidate for candidate in twins if candidate.is_champion), twins[0])
    raw_weights = [
        candidate.prior_weight * math.exp(-max(0.0, candidate.prediction_error))
        for candidate in twins
    ]
    total = max(_EPSILON, sum(raw_weights))
    scores = [
        TwinScore(
            twin_id=candidate.twin_id,
            posterior_weight=weight / total,
            prediction_error=candidate.prediction_error,
            evaluation_count=candidate.evaluation_count,
            is_champion=candidate.twin_id == champion.twin_id,
        )
        for candidate, weight in zip(twins, raw_weights, strict=True)
    ]
    ranked = sorted(scores, key=lambda score: score.posterior_weight, reverse=True)
    best = ranked[0]
    champion_score = next(score for score in scores if score.twin_id == champion.twin_id)
    margin = best.posterior_weight - champion_score.posterior_weight
    enough_evidence = best.evaluation_count >= min_evaluations
    promoted = best.twin_id != champion.twin_id and enough_evidence and margin >= promotion_margin
    champion_id = best.twin_id if promoted else champion.twin_id
    if promoted:
        reason = (
            f"challenger posterior advantage {margin:.3f} exceeded "
            f"promotion margin {promotion_margin:.3f}"
        )
    elif best.twin_id == champion.twin_id:
        reason = "current champion remains the highest-weight twin"
    elif not enough_evidence:
        reason = "challenger has insufficient evaluation history"
    else:
        reason = "challenger advantage is below the promotion margin"
    return TournamentResult(
        scores=scores,
        champion_id=champion_id,
        promoted=promoted,
        promotion_reason=reason,
    )


def recommendation_stability(
    alternatives: list[DecisionAlternative],
    beliefs: list[ParameterBelief],
    sensitivity_cases: list[SensitivityCase],
) -> RecommendationStability | None:
    if not alternatives:
        return None

    ranked = sorted(alternatives, key=lambda item: item.expected_value, reverse=True)
    winner = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    margin = winner.expected_value - (runner_up.expected_value if runner_up else 0.0)
    value_scale = max(
        abs(winner.expected_value),
        abs(runner_up.expected_value) if runner_up else 0.0,
        1.0,
    )
    margin_confidence = max(0.0, min(1.0, 0.5 + 0.5 * margin / value_scale))
    model_confidence = (
        sum(belief.confidence for belief in beliefs) / len(beliefs) if beliefs else 0.5
    )
    unstable = sorted(
        case.parameter
        for case in sensitivity_cases
        if case.changes_decision or case.sensitivity >= 0.6
    )
    sensitivity_penalty = min(0.6, len(unstable) * 0.15)
    decision_confidence = max(
        0.0,
        min(1.0, 0.6 * margin_confidence + 0.4 * model_confidence - sensitivity_penalty),
    )
    if decision_confidence >= 0.8 and not unstable:
        level = StabilityLevel.HIGH
    elif decision_confidence >= 0.55:
        level = StabilityLevel.MEDIUM
    else:
        level = StabilityLevel.LOW
    return RecommendationStability(
        recommended=winner.name,
        runner_up=runner_up.name if runner_up else None,
        decision_confidence=decision_confidence,
        model_confidence=model_confidence,
        recommendation_stability=level,
        value_margin=margin,
        unstable_parameters=unstable,
    )


def value_of_information(
    information_gain: list[InformationGainResult],
    stability: RecommendationStability | None,
    recommendation_cost: float,
) -> list[ValueOfInformation]:
    if stability is None:
        return []

    uncertainty = 1.0 - stability.decision_confidence
    results: list[ValueOfInformation] = []
    for candidate in information_gain:
        normalized_gain = 1.0 - math.exp(-candidate.expected_information_gain)
        expected_value = recommendation_cost * uncertainty * normalized_gain
        if expected_value <= max(1.0, recommendation_cost * 0.01):
            recommendation = "proceed; additional evidence has low expected decision value"
        elif stability.recommendation_stability is StabilityLevel.LOW:
            recommendation = "wait for this evidence before committing to the recommendation"
        else:
            recommendation = "collect opportunistically; it could materially improve confidence"
        results.append(
            ValueOfInformation(
                opportunity_id=candidate.opportunity_id,
                expected_value=expected_value,
                recommendation=recommendation,
            )
        )
    return sorted(results, key=lambda item: item.expected_value, reverse=True)


def analyze_evidence(request: EvidenceAnalysisRequest) -> EvidenceAnalysis:
    beliefs = {belief.name: belief for belief in request.beliefs}
    for observation in request.observations:
        belief = beliefs.get(observation.parameter)
        if belief is not None:
            beliefs[observation.parameter] = update_belief(belief, observation)

    updated_beliefs = list(beliefs.values())
    gains = [
        expected_information_gain(beliefs[opportunity.parameter], opportunity)
        for opportunity in request.opportunities
        if opportunity.parameter in beliefs
    ]
    gains.sort(key=lambda result: result.priority_score, reverse=True)
    stability = recommendation_stability(
        request.alternatives,
        updated_beliefs,
        request.sensitivity_cases,
    )
    return EvidenceAnalysis(
        beliefs=updated_beliefs,
        hypotheses=sorted(
            request.hypotheses,
            key=lambda hypothesis: hypothesis.probability,
            reverse=True,
        ),
        tournament=run_tournament(request.twins),
        information_gain=gains,
        stability=stability,
        value_of_information=value_of_information(
            gains,
            stability,
            request.current_recommendation_cost,
        ),
    )
