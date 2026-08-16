# src/powersite_autonomy/evidence_service.py
from __future__ import annotations

import asyncio

from .evidence import EvidenceAnalysis, EvidenceAnalysisRequest, analyze_evidence


class EvidenceIntelligenceService:
    """Non-blocking orchestration for CPU-bound evidence analysis."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()

    async def analyze(self, request: EvidenceAnalysisRequest) -> EvidenceAnalysis:
        # The analysis is deterministic and CPU-bound. Keep it off the event loop so
        # large twin ensembles cannot stall forecast, telemetry, or API I/O.
        async with self._lock:
            return await asyncio.to_thread(analyze_evidence, request)
