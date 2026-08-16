# src/powersite_autonomy/fleet.py
from __future__ import annotations

import hashlib
import hmac
import json
import math
import statistics
from collections import defaultdict
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field


class SiteFingerprint(BaseModel):
    site_uid: str
    climate_zone: str = "unknown"
    battery_chemistry: str = "unknown"
    battery_capacity_wh: float = Field(gt=0)
    array_watts: float = Field(gt=0)
    controller_model: str = "unknown"
    base_load_w: float = Field(ge=0, default=0)

    @property
    def pv_storage_ratio(self) -> float:
        return self.array_watts / self.battery_capacity_wh


class FleetObservation(BaseModel):
    site_uid: str
    kind: Literal["hardware", "policy", "model"]
    key: str
    value: float
    unit: str = ""
    tags: dict[str, str] = Field(default_factory=dict)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CohortMember(BaseModel):
    site_uid: str
    similarity: float


class SiteCohort(BaseModel):
    cohort_id: str
    members: list[CohortMember]
    centroid: dict[str, float | str]


class TransferablePrior(BaseModel):
    target_site_uid: str
    key: str
    value: float
    evidence_sites: int
    effective_weight: float
    confidence: Literal["low", "medium", "high"]


class HardwarePerformanceSummary(BaseModel):
    hardware_key: str
    metric: str
    unit: str
    sample_count: int
    site_count: int
    p10: float
    p50: float
    p90: float
    mean: float


class PolicyBenchmark(BaseModel):
    policy: str
    sample_count: int
    site_count: int
    mean_utility: float
    p10_utility: float
    p50_utility: float
    p90_utility: float
    mean_regret: float | None = None


class FederatedModelSummary(BaseModel):
    schema_version: str = "fleet-summary-v1"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_id: str
    observation_count: int
    metrics: dict[str, dict[str, float]]
    tags: dict[str, str] = Field(default_factory=dict)
    signature: str | None = None


def _distance(a: SiteFingerprint, b: SiteFingerprint) -> float:
    numeric = (
        abs(math.log(a.battery_capacity_wh / b.battery_capacity_wh)),
        abs(math.log(a.array_watts / b.array_watts)),
        abs(math.log((a.base_load_w + 25.0) / (b.base_load_w + 25.0))),
        abs(math.log((a.pv_storage_ratio + 1e-6) / (b.pv_storage_ratio + 1e-6))),
    )
    categorical_penalty = 0.0
    categorical_penalty += 0.6 if a.climate_zone != b.climate_zone else 0.0
    categorical_penalty += 0.8 if a.battery_chemistry != b.battery_chemistry else 0.0
    categorical_penalty += 0.4 if a.controller_model != b.controller_model else 0.0
    return statistics.fmean(numeric) + categorical_penalty


def site_similarity(a: SiteFingerprint, b: SiteFingerprint) -> float:
    return 1.0 / (1.0 + _distance(a, b))


def build_cohorts(
    fingerprints: list[SiteFingerprint],
    *,
    minimum_similarity: float = 0.58,
) -> list[SiteCohort]:
    remaining = {item.site_uid: item for item in fingerprints}
    cohorts: list[SiteCohort] = []
    while remaining:
        seed_uid = sorted(remaining)[0]
        seed = remaining.pop(seed_uid)
        members = [CohortMember(site_uid=seed.site_uid, similarity=1.0)]
        accepted: list[SiteFingerprint] = [seed]
        for uid, candidate in list(remaining.items()):
            similarity = site_similarity(seed, candidate)
            if similarity >= minimum_similarity:
                members.append(CohortMember(site_uid=uid, similarity=similarity))
                accepted.append(candidate)
                del remaining[uid]
        cohort_key = "|".join(sorted(item.site_uid for item in accepted)).encode()
        cohorts.append(
            SiteCohort(
                cohort_id=f"cohort-{hashlib.sha256(cohort_key).hexdigest()[:12]}",
                members=sorted(members, key=lambda item: item.similarity, reverse=True),
                centroid={
                    "battery_capacity_wh": statistics.fmean(
                        item.battery_capacity_wh for item in accepted
                    ),
                    "array_watts": statistics.fmean(item.array_watts for item in accepted),
                    "base_load_w": statistics.fmean(item.base_load_w for item in accepted),
                    "climate_zone": seed.climate_zone,
                    "battery_chemistry": seed.battery_chemistry,
                    "controller_model": seed.controller_model,
                },
            )
        )
    return cohorts


def derive_transferable_prior(
    target: SiteFingerprint,
    fingerprints: list[SiteFingerprint],
    observations: list[FleetObservation],
    *,
    key: str,
) -> TransferablePrior | None:
    by_site = {item.site_uid: item for item in fingerprints}
    weighted: list[tuple[float, float]] = []
    for observation in observations:
        if observation.key != key or observation.site_uid == target.site_uid:
            continue
        peer = by_site.get(observation.site_uid)
        if peer is None:
            continue
        similarity = site_similarity(target, peer)
        if similarity < 0.35:
            continue
        weighted.append((observation.value, similarity**2))
    if not weighted:
        return None
    total_weight = sum(weight for _, weight in weighted)
    value = sum(value * weight for value, weight in weighted) / total_weight
    evidence_sites = len({obs.site_uid for obs in observations if obs.key == key})
    confidence: Literal["low", "medium", "high"]
    if evidence_sites >= 8 and total_weight >= 3.5:
        confidence = "high"
    elif evidence_sites >= 3 and total_weight >= 1.2:
        confidence = "medium"
    else:
        confidence = "low"
    return TransferablePrior(
        target_site_uid=target.site_uid,
        key=key,
        value=value,
        evidence_sites=evidence_sites,
        effective_weight=total_weight,
        confidence=confidence,
    )


def summarize_hardware(observations: list[FleetObservation]) -> list[HardwarePerformanceSummary]:
    grouped: dict[tuple[str, str, str], list[FleetObservation]] = defaultdict(list)
    for observation in observations:
        if observation.kind != "hardware":
            continue
        hardware_key = observation.tags.get("hardware", observation.key)
        grouped[(hardware_key, observation.key, observation.unit)].append(observation)

    summaries: list[HardwarePerformanceSummary] = []
    for (hardware_key, metric, unit), group in grouped.items():
        values = sorted(item.value for item in group)
        summaries.append(
            HardwarePerformanceSummary(
                hardware_key=hardware_key,
                metric=metric,
                unit=unit,
                sample_count=len(values),
                site_count=len({item.site_uid for item in group}),
                p10=_percentile(values, 0.10),
                p50=_percentile(values, 0.50),
                p90=_percentile(values, 0.90),
                mean=statistics.fmean(values),
            )
        )
    return sorted(summaries, key=lambda item: (item.hardware_key, item.metric))


def benchmark_policies(observations: list[FleetObservation]) -> list[PolicyBenchmark]:
    grouped: dict[str, list[FleetObservation]] = defaultdict(list)
    regrets: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        if observation.kind != "policy":
            continue
        policy = observation.tags.get("policy", observation.key)
        if observation.key == "decision_regret":
            regrets[policy].append(observation.value)
        elif observation.key == "policy_utility":
            grouped[policy].append(observation)

    results: list[PolicyBenchmark] = []
    for policy, group in grouped.items():
        values = sorted(item.value for item in group)
        policy_regrets = regrets.get(policy, [])
        results.append(
            PolicyBenchmark(
                policy=policy,
                sample_count=len(values),
                site_count=len({item.site_uid for item in group}),
                mean_utility=statistics.fmean(values),
                p10_utility=_percentile(values, 0.10),
                p50_utility=_percentile(values, 0.50),
                p90_utility=_percentile(values, 0.90),
                mean_regret=statistics.fmean(policy_regrets) if policy_regrets else None,
            )
        )
    return sorted(results, key=lambda item: (-item.mean_utility, item.policy))


def build_federated_summary(
    source_id: str,
    observations: list[FleetObservation],
    *,
    tags: dict[str, str] | None = None,
    secret: str | None = None,
) -> FederatedModelSummary:
    grouped: dict[str, list[float]] = defaultdict(list)
    for observation in observations:
        grouped[f"{observation.kind}:{observation.key}"].append(observation.value)
    metrics = {
        key: {
            "count": float(len(values)),
            "mean": statistics.fmean(values),
            "p50": statistics.median(values),
            "stddev": statistics.pstdev(values) if len(values) > 1 else 0.0,
        }
        for key, values in sorted(grouped.items())
    }
    summary = FederatedModelSummary(
        source_id=source_id,
        observation_count=len(observations),
        metrics=metrics,
        tags=tags or {},
    )
    if secret:
        payload = summary.model_dump(mode="json", exclude={"signature"})
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        summary.signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
    return summary


def _percentile(values: list[float], percentile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction
