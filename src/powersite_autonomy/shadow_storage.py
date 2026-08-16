# src/powersite_autonomy/shadow_storage.py
from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .shadow_models import (
    CounterfactualEvaluation,
    ModelEpoch,
    ModelFeedback,
    ShadowAutopilotPlan,
)

_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS shadow_plans (
    plan_id TEXT PRIMARY KEY,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    horizon_hours INTEGER NOT NULL,
    objective_score REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_plans_site_time
    ON shadow_plans(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS shadow_actions (
    action_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    site_uid TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_actions_site_time
    ON shadow_actions(site_uid, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_shadow_actions_plan
    ON shadow_actions(plan_id);
CREATE TABLE IF NOT EXISTS shadow_evaluations (
    evaluation_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL UNIQUE,
    site_uid TEXT NOT NULL,
    evaluated_at TEXT NOT NULL,
    decision_regret REAL NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_site_time
    ON shadow_evaluations(site_uid, evaluated_at DESC);
CREATE TABLE IF NOT EXISTS shadow_feedback (
    feedback_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    site_uid TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    applied_to_calibration INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_shadow_feedback_site_time
    ON shadow_feedback(site_uid, generated_at DESC);
CREATE TABLE IF NOT EXISTS model_epochs (
    epoch_id TEXT PRIMARY KEY,
    site_uid TEXT NOT NULL,
    started_at TEXT NOT NULL,
    calibration_version TEXT,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_epochs_site_time
    ON model_epochs(site_uid, started_at DESC);
"""


class ShadowStorage:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._write_lock = asyncio.Lock()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._initialize_sync)

    def _initialize_sync(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._path) as connection:
            connection.executescript(_SCHEMA)

    async def save_plan(self, plan: ShadowAutopilotPlan) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_plan_sync, plan)

    def _save_plan_sync(self, plan: ShadowAutopilotPlan) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO shadow_plans("
                "plan_id, site_uid, generated_at, horizon_hours, objective_score, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    plan.plan_id,
                    plan.site_uid,
                    plan.generated_at.isoformat(),
                    plan.horizon_hours,
                    plan.objective_score,
                    plan.model_dump_json(),
                ),
            )
            for action in plan.actions:
                connection.execute(
                    "INSERT OR REPLACE INTO shadow_actions("
                    "action_id, plan_id, site_uid, created_at, expires_at, status, payload_json"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        action.action_id,
                        plan.plan_id,
                        plan.site_uid,
                        action.created_at.isoformat(),
                        action.expires_at.isoformat(),
                        "proposed",
                        action.model_dump_json(),
                    ),
                )

    async def get_plan(self, plan_id: str) -> ShadowAutopilotPlan | None:
        payload = await asyncio.to_thread(self._plan_payload_sync, plan_id)
        return ShadowAutopilotPlan.model_validate_json(payload) if payload is not None else None

    def _plan_payload_sync(self, plan_id: str) -> str | None:
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM shadow_plans WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        return row[0] if row else None

    async def recent_plans(self, site_uid: str, limit: int = 20) -> list[ShadowAutopilotPlan]:
        payloads = await asyncio.to_thread(
            self._recent_payloads_sync,
            "shadow_plans",
            "generated_at",
            site_uid,
            limit,
        )
        return [ShadowAutopilotPlan.model_validate_json(payload) for payload in payloads]

    async def pending_plans(
        self,
        site_uid: str,
        cutoff: datetime,
        limit: int = 4,
    ) -> list[ShadowAutopilotPlan]:
        payloads = await asyncio.to_thread(
            self._pending_plan_payloads_sync, site_uid, cutoff, limit
        )
        return [ShadowAutopilotPlan.model_validate_json(payload) for payload in payloads]

    def _pending_plan_payloads_sync(
        self,
        site_uid: str,
        cutoff: datetime,
        limit: int,
    ) -> list[str]:
        bounded = max(1, min(limit, 20))
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT p.payload_json FROM shadow_plans AS p "
                "LEFT JOIN shadow_evaluations AS e ON e.plan_id = p.plan_id "
                "WHERE p.site_uid = ? AND p.generated_at <= ? AND e.plan_id IS NULL "
                "ORDER BY p.generated_at ASC LIMIT ?",
                (site_uid, cutoff.isoformat(), bounded),
            ).fetchall()
        return [row[0] for row in rows]

    async def recent_actions(self, site_uid: str, limit: int = 100) -> list[dict]:
        rows = await asyncio.to_thread(self._recent_action_payloads_sync, site_uid, limit)
        return rows

    def _recent_action_payloads_sync(self, site_uid: str, limit: int) -> list[dict]:
        bounded = max(1, min(limit, 500))
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                "SELECT status, payload_json FROM shadow_actions WHERE site_uid = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (site_uid, bounded),
            ).fetchall()
        return [{"status": row[0], **json.loads(row[1])} for row in rows]

    async def save_evaluation(self, evaluation: CounterfactualEvaluation) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_evaluation_sync, evaluation)

    def _save_evaluation_sync(self, evaluation: CounterfactualEvaluation) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO shadow_evaluations("
                "evaluation_id, plan_id, site_uid, evaluated_at, decision_regret, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    evaluation.evaluation_id,
                    evaluation.plan_id,
                    evaluation.site_uid,
                    evaluation.evaluated_at.isoformat(),
                    evaluation.decision_regret,
                    evaluation.model_dump_json(),
                ),
            )
            connection.execute(
                "UPDATE shadow_actions SET status = 'evaluated' WHERE plan_id = ?",
                (evaluation.plan_id,),
            )

    async def evaluation_for_plan(self, plan_id: str) -> CounterfactualEvaluation | None:
        payload = await asyncio.to_thread(self._evaluation_payload_sync, plan_id)
        if payload is None:
            return None
        return CounterfactualEvaluation.model_validate_json(payload)

    def _evaluation_payload_sync(self, plan_id: str) -> str | None:
        with sqlite3.connect(self._path) as connection:
            row = connection.execute(
                "SELECT payload_json FROM shadow_evaluations WHERE plan_id = ?",
                (plan_id,),
            ).fetchone()
        return row[0] if row else None

    async def recent_evaluations(
        self,
        site_uid: str,
        limit: int = 100,
    ) -> list[CounterfactualEvaluation]:
        payloads = await asyncio.to_thread(
            self._recent_payloads_sync,
            "shadow_evaluations",
            "evaluated_at",
            site_uid,
            limit,
        )
        return [CounterfactualEvaluation.model_validate_json(payload) for payload in payloads]

    async def save_feedback(self, feedback: ModelFeedback) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_feedback_sync, feedback)

    def _save_feedback_sync(self, feedback: ModelFeedback) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO shadow_feedback("
                "feedback_id, plan_id, site_uid, generated_at, applied_to_calibration, payload_json"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                (
                    feedback.feedback_id,
                    feedback.plan_id,
                    feedback.site_uid,
                    feedback.generated_at.isoformat(),
                    int(feedback.applied_to_calibration),
                    feedback.model_dump_json(),
                ),
            )

    async def recent_feedback(self, site_uid: str, limit: int = 20) -> list[ModelFeedback]:
        payloads = await asyncio.to_thread(
            self._recent_payloads_sync,
            "shadow_feedback",
            "generated_at",
            site_uid,
            limit,
        )
        return [ModelFeedback.model_validate_json(payload) for payload in payloads]

    async def save_epoch(self, epoch: ModelEpoch) -> None:
        async with self._write_lock:
            await asyncio.to_thread(self._save_epoch_sync, epoch)

    def _save_epoch_sync(self, epoch: ModelEpoch) -> None:
        with sqlite3.connect(self._path) as connection:
            connection.execute(
                "INSERT OR REPLACE INTO model_epochs("
                "epoch_id, site_uid, started_at, calibration_version, payload_json"
                ") VALUES (?, ?, ?, ?, ?)",
                (
                    epoch.epoch_id,
                    epoch.site_uid,
                    epoch.started_at.isoformat(),
                    epoch.calibration_version,
                    epoch.model_dump_json(),
                ),
            )

    async def latest_epoch(self, site_uid: str) -> ModelEpoch | None:
        payloads = await asyncio.to_thread(
            self._recent_payloads_sync,
            "model_epochs",
            "started_at",
            site_uid,
            1,
        )
        return ModelEpoch.model_validate_json(payloads[0]) if payloads else None

    async def recent_epochs(self, site_uid: str, limit: int = 20) -> list[ModelEpoch]:
        payloads = await asyncio.to_thread(
            self._recent_payloads_sync,
            "model_epochs",
            "started_at",
            site_uid,
            limit,
        )
        return [ModelEpoch.model_validate_json(payload) for payload in payloads]

    def _recent_payloads_sync(
        self,
        table: str,
        time_column: str,
        site_uid: str,
        limit: int,
    ) -> list[str]:
        allowed = {
            ("shadow_plans", "generated_at"),
            ("shadow_evaluations", "evaluated_at"),
            ("shadow_feedback", "generated_at"),
            ("model_epochs", "started_at"),
        }
        if (table, time_column) not in allowed:
            raise ValueError("unsupported shadow ledger query")
        bounded = max(1, min(limit, 500))
        with sqlite3.connect(self._path) as connection:
            rows = connection.execute(
                f"SELECT payload_json FROM {table} WHERE site_uid = ? "
                f"ORDER BY {time_column} DESC LIMIT ?",
                (site_uid, bounded),
            ).fetchall()
        return [row[0] for row in rows]
