# src/powersite_autonomy/fleet_service.py
from __future__ import annotations

import asyncio

from .fleet import (
    FederatedModelSummary,
    FleetObservation,
    HardwarePerformanceSummary,
    PolicyBenchmark,
    SiteCohort,
    SiteFingerprint,
    TransferablePrior,
    benchmark_policies,
    build_cohorts,
    build_federated_summary,
    derive_transferable_prior,
    summarize_hardware,
)
from .storage import Storage


class FleetIntelligenceService:
    """Local-first fleet aggregation over compact observations, never raw telemetry."""

    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    async def ingest(self, observations: list[FleetObservation]) -> int:
        await self.storage.save_fleet_observations(observations)
        return len(observations)

    async def cohorts(
        self,
        fingerprints: list[SiteFingerprint],
        *,
        minimum_similarity: float = 0.58,
    ) -> list[SiteCohort]:
        return await asyncio.to_thread(
            build_cohorts,
            fingerprints,
            minimum_similarity=minimum_similarity,
        )

    async def transferable_prior(
        self,
        target: SiteFingerprint,
        fingerprints: list[SiteFingerprint],
        *,
        key: str,
    ) -> TransferablePrior | None:
        observations = await self.storage.fleet_observations(key=key)
        return await asyncio.to_thread(
            derive_transferable_prior,
            target,
            fingerprints,
            observations,
            key=key,
        )

    async def hardware_performance(self) -> list[HardwarePerformanceSummary]:
        observations = await self.storage.fleet_observations(kind="hardware")
        return await asyncio.to_thread(summarize_hardware, observations)

    async def policy_benchmarks(self) -> list[PolicyBenchmark]:
        observations = await self.storage.fleet_observations(kind="policy")
        return await asyncio.to_thread(benchmark_policies, observations)

    async def compact_exchange(
        self,
        source_id: str,
        *,
        tags: dict[str, str] | None = None,
        secret: str | None = None,
        limit: int = 5000,
    ) -> FederatedModelSummary:
        observations = await self.storage.fleet_observations(limit=limit)
        return await asyncio.to_thread(
            build_federated_summary,
            source_id,
            observations,
            tags=tags,
            secret=secret,
        )
