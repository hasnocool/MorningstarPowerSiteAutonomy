# tests/test_fleet.py
from __future__ import annotations

from powersite_autonomy.fleet import (
    FleetObservation,
    SiteFingerprint,
    benchmark_policies,
    build_cohorts,
    build_federated_summary,
    derive_transferable_prior,
    summarize_hardware,
)


def _fingerprints() -> list[SiteFingerprint]:
    return [
        SiteFingerprint(
            site_uid="a",
            climate_zone="marine",
            battery_chemistry="lifepo4",
            battery_capacity_wh=4000,
            array_watts=1200,
            controller_model="ts-mppt-60",
            base_load_w=100,
        ),
        SiteFingerprint(
            site_uid="b",
            climate_zone="marine",
            battery_chemistry="lifepo4",
            battery_capacity_wh=4200,
            array_watts=1300,
            controller_model="ts-mppt-60",
            base_load_w=110,
        ),
        SiteFingerprint(
            site_uid="c",
            climate_zone="desert",
            battery_chemistry="lead-acid",
            battery_capacity_wh=9000,
            array_watts=3000,
            controller_model="other",
            base_load_w=500,
        ),
    ]


def test_cohorts_group_similar_sites() -> None:
    cohorts = build_cohorts(_fingerprints())
    member_sets = [{member.site_uid for member in cohort.members} for cohort in cohorts]
    assert {"a", "b"} in member_sets
    assert {"c"} in member_sets


def test_transferable_prior_weights_nearby_sites() -> None:
    observations = [
        FleetObservation(site_uid="b", kind="model", key="pv_scale", value=0.91),
        FleetObservation(site_uid="c", kind="model", key="pv_scale", value=0.55),
    ]
    prior = derive_transferable_prior(
        _fingerprints()[0],
        _fingerprints(),
        observations,
        key="pv_scale",
    )
    assert prior is not None
    assert prior.value > 0.75
    assert prior.evidence_sites == 2


def test_hardware_and_policy_aggregation() -> None:
    observations = [
        FleetObservation(
            site_uid="a",
            kind="hardware",
            key="conversion_efficiency",
            value=0.95,
            unit="ratio",
            tags={"hardware": "ts-mppt-60"},
        ),
        FleetObservation(
            site_uid="b",
            kind="hardware",
            key="conversion_efficiency",
            value=0.97,
            unit="ratio",
            tags={"hardware": "ts-mppt-60"},
        ),
        FleetObservation(
            site_uid="a",
            kind="policy",
            key="policy_utility",
            value=0.8,
            tags={"policy": "balanced"},
        ),
        FleetObservation(
            site_uid="b",
            kind="policy",
            key="policy_utility",
            value=0.9,
            tags={"policy": "balanced"},
        ),
        FleetObservation(
            site_uid="a",
            kind="policy",
            key="decision_regret",
            value=0.05,
            tags={"policy": "balanced"},
        ),
    ]
    hardware = summarize_hardware(observations)
    policies = benchmark_policies(observations)
    assert hardware[0].p50 == 0.96
    assert policies[0].mean_utility == 0.85
    assert policies[0].mean_regret == 0.05


def test_federated_exchange_is_compact_and_signable() -> None:
    summary = build_federated_summary(
        "site-a",
        [FleetObservation(site_uid="a", kind="model", key="pv_scale", value=0.9)],
        secret="secret",
    )
    assert summary.observation_count == 1
    assert summary.signature is not None
    assert "model:pv_scale" in summary.metrics
