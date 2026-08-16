# src/powersite_autonomy/economic_service.py
from __future__ import annotations

import asyncio

from .economics import (
    HardwareUpgrade,
    SiteEconomics,
    UpgradeEvaluation,
    rank_upgrades,
)
from .fleet_service import FleetIntelligenceService


class EconomicHardwareService:
    """Ranks upgrade options using fleet evidence without blocking the event loop."""

    def __init__(self, fleet: FleetIntelligenceService) -> None:
        self.fleet = fleet

    async def rank(
        self,
        site: SiteEconomics,
        upgrades: list[HardwareUpgrade],
    ) -> list[UpgradeEvaluation]:
        hardware = await self.fleet.hardware_performance()
        return await asyncio.to_thread(rank_upgrades, site, upgrades, hardware)
