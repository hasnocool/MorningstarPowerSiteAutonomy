# src/powersite_autonomy/policy_storage.py
from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from .policy_models import (
    PolicyCandidate,
    PolicyEvaluation,
    PolicyFrontier,
    PolicyLabScorecard,
    PolicyLabSnapshot,
    PolicyTournamentDecision,
    RegretDecomposition,
)

T = TypeVar("T", bound=BaseModel)

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS policy_lab_artifacts (
    artifact_id TEXT PRIMARY KEY,
    site_uid TEXT NOT NULL,
    kind TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_policy_lab_artifacts_site_kind_time
    ON policy_lab_artifacts(site_uid, kind, generated_at DESC);
CREATE TABLE IF NOT EXISTS policy_lab_champions (
    site_uid TEXT PRIMARY KEY,
    policy_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


class PolicyLabStorage:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._write_lock = asyncio.Lock()
        self._initialized = False
        self._initialize_lock = asyncio.Lock()

    async def initialize(self) -> None:
        if self._initialized:
            return
        async with self._initialize_lock:
            if self._initialized:
                return
            await asyncio.to_thread(self._initialize_sync)
            self._initialized = True

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript(_SCHEMA)

    async def _save(
        self,
        *,
        artifact_id: str,
        site_uid: str,
        kind: str,
        generated_at: datetime,
        payload_json: str,
    ) -> None:
        await self.initialize()
        async with self._write_lock:
            await asyncio.to_thread(
                self._save_sync,
                artifact_id,
                site_uid,
                kind,
                generated_at,
                payload_json,
            )

    def _save_sync(
        self,
        artifact_id: str,
        site_uid: str,
        kind: str,
        generated_at: datetime,
        payload_json: str,
    ) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO policy_lab_artifacts("
                "artifact_id, site_uid, kind, generated_at, payload_json"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    artifact_id,
                    site_uid,
                    kind,
                    generated_at.astimezone(UTC).isoformat(),
                    payload_json,
                ),
            )

    async def _recent(
        self,
        site_uid: str,
        kind: str,
        model: type[T],
        limit: int,
    ) -> list[T]:
        await self.initialize()
        payloads = await asyncio.to_thread(
            self._recent_sync,
            site_uid,
            kind,
            max(1, min(limit, 1000)),
        )
        return [model.model_validate_json(payload) for payload in payloads]

    def _recent_sync(self, site_uid: str, kind: str, limit: int) -> list[str]:
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT payload_json FROM policy_lab_artifacts "
                "WHERE site_uid = ? AND kind = ? "
                "ORDER BY generated_at DESC LIMIT ?",
                (site_uid, kind, limit),
            ).fetchall()
        return [row[0] for row in rows]

    async def save_candidate(self, candidate: PolicyCandidate) -> None:
        await self._save(
            artifact_id=f"candidate:{candidate.policy_id}:{candidate.generated_at.isoformat()}",
            site_uid=candidate.site_uid,
            kind="candidate",
            generated_at=candidate.generated_at,
            payload_json=candidate.model_dump_json(),
        )

    async def recent_candidates(
        self,
        site_uid: str,
        limit: int = 100,
    ) -> list[PolicyCandidate]:
        return await self._recent(site_uid, "candidate", PolicyCandidate, limit)

    async def save_evaluation(self, evaluation: PolicyEvaluation) -> None:
        await self._save(
            artifact_id=evaluation.evaluation_id,
            site_uid=evaluation.site_uid,
            kind="evaluation",
            generated_at=evaluation.generated_at,
            payload_json=evaluation.model_dump_json(),
        )

    async def recent_evaluations(
        self,
        site_uid: str,
        limit: int = 100,
    ) -> list[PolicyEvaluation]:
        return await self._recent(site_uid, "evaluation", PolicyEvaluation, limit)

    async def save_tournament(self, decision: PolicyTournamentDecision) -> None:
        await self._save(
            artifact_id=decision.decision_id,
            site_uid=decision.site_uid,
            kind="tournament",
            generated_at=decision.generated_at,
            payload_json=decision.model_dump_json(),
        )

    async def recent_tournaments(
        self,
        site_uid: str,
        limit: int = 50,
    ) -> list[PolicyTournamentDecision]:
        return await self._recent(
            site_uid,
            "tournament",
            PolicyTournamentDecision,
            limit,
        )

    async def save_frontier(self, frontier: PolicyFrontier) -> None:
        await self._save(
            artifact_id=f"frontier:{frontier.generated_at.isoformat()}",
            site_uid=frontier.site_uid,
            kind="frontier",
            generated_at=frontier.generated_at,
            payload_json=frontier.model_dump_json(),
        )

    async def latest_frontier(self, site_uid: str) -> PolicyFrontier | None:
        values = await self._recent(site_uid, "frontier", PolicyFrontier, 1)
        return values[0] if values else None

    async def save_regret(self, regret: RegretDecomposition) -> None:
        await self._save(
            artifact_id=f"regret:{regret.generated_at.isoformat()}",
            site_uid=regret.site_uid,
            kind="regret",
            generated_at=regret.generated_at,
            payload_json=regret.model_dump_json(),
        )

    async def latest_regret(self, site_uid: str) -> RegretDecomposition | None:
        values = await self._recent(site_uid, "regret", RegretDecomposition, 1)
        return values[0] if values else None

    async def save_scorecard(self, scorecard: PolicyLabScorecard) -> None:
        await self._save(
            artifact_id=f"scorecard:{scorecard.generated_at.isoformat()}",
            site_uid=scorecard.site_uid,
            kind="scorecard",
            generated_at=scorecard.generated_at,
            payload_json=scorecard.model_dump_json(),
        )

    async def latest_scorecard(self, site_uid: str) -> PolicyLabScorecard | None:
        values = await self._recent(site_uid, "scorecard", PolicyLabScorecard, 1)
        return values[0] if values else None

    async def save_snapshot(self, snapshot: PolicyLabSnapshot) -> None:
        await self._save(
            artifact_id=f"snapshot:{snapshot.generated_at.isoformat()}",
            site_uid=snapshot.site_uid,
            kind="snapshot",
            generated_at=snapshot.generated_at,
            payload_json=snapshot.model_dump_json(),
        )

    async def latest_snapshot(self, site_uid: str) -> PolicyLabSnapshot | None:
        values = await self._recent(site_uid, "snapshot", PolicyLabSnapshot, 1)
        return values[0] if values else None

    async def set_champion(self, candidate: PolicyCandidate) -> None:
        await self.initialize()
        async with self._write_lock:
            await asyncio.to_thread(self._set_champion_sync, candidate)

    def _set_champion_sync(self, candidate: PolicyCandidate) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO policy_lab_champions("
                "site_uid, policy_id, updated_at, payload_json"
                ") VALUES (?, ?, ?, ?)",
                (
                    candidate.site_uid,
                    candidate.policy_id,
                    datetime.now(UTC).isoformat(),
                    candidate.model_dump_json(),
                ),
            )

    async def champion(self, site_uid: str) -> PolicyCandidate | None:
        await self.initialize()
        payload = await asyncio.to_thread(self._champion_sync, site_uid)
        return PolicyCandidate.model_validate_json(payload) if payload else None

    def _champion_sync(self, site_uid: str) -> str | None:
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM policy_lab_champions WHERE site_uid = ?",
                (site_uid,),
            ).fetchone()
        return row[0] if row else None
