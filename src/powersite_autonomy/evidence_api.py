# src/powersite_autonomy/evidence_api.py
from __future__ import annotations

from fastapi import APIRouter

from .evidence import EvidenceAnalysis, EvidenceAnalysisRequest
from .evidence_service import EvidenceIntelligenceService


def build_evidence_router(service: EvidenceIntelligenceService) -> APIRouter:
    router = APIRouter(prefix="/v1/evidence", tags=["evidence-intelligence"])

    @router.post("/analyze", response_model=EvidenceAnalysis)
    async def analyze(request: EvidenceAnalysisRequest) -> EvidenceAnalysis:
        return await service.analyze(request)

    return router
