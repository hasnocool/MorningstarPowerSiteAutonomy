# src/powersite_autonomy/policy_service.py
from __future__ import annotations

import asyncio

from .adaptive_storage import AdaptiveStorage
from .config import Settings
from .policy_learning import (
    best_regime_candidates,
    build_decision_sensitivity,
    build_intelligence_score,
    build_policy_frontier,
    build_policy_scorecard,
    choose_policy_tournament,
    decompose_regret,
    evaluate_policy_candidate,
    generate_policy_candidates,
    initial_candidate,
    recommend_dynamic_reserve,
)
from .policy_models import (
    AutonomyIntelligenceScore,
    DynamicReserveRecommendation,
    PolicyCandidate,
    PolicyFrontier,
    PolicyLabScorecard,
    PolicyLabSnapshot,
    PolicySearchBounds,
)
from .policy_storage import PolicyLabStorage
from .service import AutonomyService
from .shadow_models import EnergyPolicy
from .shadow_storage import ShadowStorage


class PolicyLabService:
    def __init__(
        self,
        settings: Settings,
        autonomy: AutonomyService,
        shadow_storage: ShadowStorage,
        adaptive_storage: AdaptiveStorage,
        storage: PolicyLabStorage,
    ) -> None:
        self.settings = settings
        self.autonomy = autonomy
        self.shadow_storage = shadow_storage
        self.adaptive_storage = adaptive_storage
        self.storage = storage
        self._operator_policies = dict(settings.shadow_policies)

    def _operator_policy(self, site_uid: str) -> EnergyPolicy:
        site = self.autonomy.site_config(site_uid)
        configured = self._operator_policies.get(site_uid)
        if configured is not None:
            return configured
        emergency = max(0.0, min(15.0, site.reserve_percent - 5.0))
        return EnergyPolicy(
            minimum_reserve_percent=site.reserve_percent,
            emergency_reserve_percent=emergency,
            target_morning_soc_percent=max(40.0, site.reserve_percent),
        )

    def _bounds(self) -> PolicySearchBounds:
        return PolicySearchBounds(
            minimum_reserve_min_percent=getattr(
                self.settings,
                "policy_lab_reserve_min_percent",
                10.0,
            ),
            minimum_reserve_max_percent=getattr(
                self.settings,
                "policy_lab_reserve_max_percent",
                60.0,
            ),
            morning_soc_min_percent=getattr(
                self.settings,
                "policy_lab_morning_soc_min_percent",
                25.0,
            ),
            morning_soc_max_percent=getattr(
                self.settings,
                "policy_lab_morning_soc_max_percent",
                80.0,
            ),
        )

    async def restore_champion(self, site_uid: str) -> PolicyCandidate:
        self.autonomy.site_config(site_uid)
        await self.shadow_storage.initialize()
        champion = await self.storage.champion(site_uid)
        if champion is None:
            champion = initial_candidate(site_uid, self._operator_policy(site_uid))
            await asyncio.gather(
                self.storage.save_candidate(champion),
                self.storage.set_champion(champion),
            )
        self.settings.shadow_policies[site_uid] = champion.policy
        return champion

    async def tick(self, site_uid: str) -> PolicyLabSnapshot:
        self.autonomy.site_config(site_uid)
        champion = await self.restore_champion(site_uid)
        history_limit = max(
            20,
            min(getattr(self.settings, "policy_lab_history_limit", 500), 2000),
        )
        plans_task = self.shadow_storage.recent_plans(site_uid, history_limit)
        evaluations_task = self.shadow_storage.recent_evaluations(site_uid, history_limit)
        adaptive_task = self.adaptive_storage.latest_snapshot(site_uid)
        prior_tournaments_task = self.storage.recent_tournaments(site_uid, 500)
        plans, shadow_evaluations, adaptive, prior_tournaments = await asyncio.gather(
            plans_task,
            evaluations_task,
            adaptive_task,
            prior_tournaments_task,
        )

        candidates = await asyncio.to_thread(
            generate_policy_candidates,
            champion,
            self._bounds(),
            max_candidates=max(
                2,
                min(getattr(self.settings, "policy_lab_max_candidates", 12), 48),
            ),
        )
        candidate_evaluations = await asyncio.gather(
            *(
                asyncio.to_thread(
                    evaluate_policy_candidate,
                    candidate,
                    plans,
                    shadow_evaluations,
                    fallback_policy=champion.policy,
                )
                for candidate in candidates
            )
        )
        tournament = await asyncio.to_thread(
            choose_policy_tournament,
            site_uid,
            champion,
            candidates,
            candidate_evaluations,
            minimum_replays=max(
                6,
                getattr(self.settings, "policy_lab_minimum_replays", 24),
            ),
            promotion_margin=max(
                0.01,
                min(getattr(self.settings, "policy_lab_promotion_margin", 0.08), 0.50),
            ),
            bootstrap_samples=max(
                100,
                min(getattr(self.settings, "policy_lab_bootstrap_samples", 400), 5000),
            ),
        )

        if tournament.promoted:
            winner = next(
                item for item in candidates if item.policy_id == tournament.champion_after
            )
            old_champion = champion.model_copy(update={"status": "rejected"})
            champion = winner.model_copy(update={"status": "champion", "origin": "promoted"})
            candidates = [
                champion if item.policy_id == champion.policy_id else item
                for item in candidates
            ]
            self.settings.shadow_policies[site_uid] = champion.policy
            await asyncio.gather(
                self.storage.save_candidate(old_champion),
                self.storage.save_candidate(champion),
                self.storage.set_champion(champion),
            )

        frontier = await asyncio.to_thread(
            build_policy_frontier,
            site_uid,
            candidates,
            candidate_evaluations,
        )
        regret = await asyncio.to_thread(decompose_regret, site_uid, shadow_evaluations)
        decision_sensitivity = await asyncio.to_thread(
            build_decision_sensitivity,
            site_uid,
            shadow_evaluations,
        )
        champion_evaluation = next(
            (
                item
                for item in candidate_evaluations
                if item.policy_id == champion.policy_id
            ),
            None,
        )
        intelligence = await asyncio.to_thread(
            build_intelligence_score,
            site_uid,
            adaptive,
            champion_evaluation,
            shadow_evaluations,
        )
        regime_champions = await asyncio.to_thread(
            best_regime_candidates,
            candidates,
            candidate_evaluations,
        )
        promotion_count = sum(item.promoted for item in prior_tournaments) + int(
            tournament.promoted
        )
        scorecard = await asyncio.to_thread(
            build_policy_scorecard,
            site_uid,
            champion,
            candidate_evaluations,
            tournament,
            frontier,
            promotion_count,
            regime_champions,
        )
        snapshot = PolicyLabSnapshot(
            site_uid=site_uid,
            champion=champion,
            candidates=candidates,
            evaluations=candidate_evaluations,
            tournament=tournament,
            frontier=frontier,
            regret=regret,
            decision_sensitivity=decision_sensitivity,
            intelligence=intelligence,
            scorecard=scorecard,
        )

        await asyncio.gather(
            *(self.storage.save_candidate(item) for item in candidates),
            *(self.storage.save_evaluation(item) for item in candidate_evaluations),
            self.storage.save_tournament(tournament),
            self.storage.save_frontier(frontier),
            self.storage.save_regret(regret),
            self.storage.save_scorecard(scorecard),
            self.storage.save_snapshot(snapshot),
        )
        return snapshot

    async def snapshot(self, site_uid: str) -> PolicyLabSnapshot:
        self.autonomy.site_config(site_uid)
        value = await self.storage.latest_snapshot(site_uid)
        if value is not None:
            return value
        return await self.tick(site_uid)

    async def champion(self, site_uid: str) -> PolicyCandidate:
        return await self.restore_champion(site_uid)

    async def scorecard(self, site_uid: str) -> PolicyLabScorecard:
        self.autonomy.site_config(site_uid)
        value = await self.storage.latest_scorecard(site_uid)
        if value is not None:
            return value
        return (await self.tick(site_uid)).scorecard

    async def frontier(self, site_uid: str) -> PolicyFrontier:
        self.autonomy.site_config(site_uid)
        value = await self.storage.latest_frontier(site_uid)
        if value is not None:
            return value
        return (await self.tick(site_uid)).frontier

    async def intelligence(self, site_uid: str) -> AutonomyIntelligenceScore:
        return (await self.snapshot(site_uid)).intelligence

    async def dynamic_reserve(self, site_uid: str) -> DynamicReserveRecommendation:
        champion = await self.restore_champion(site_uid)
        plans, adaptive = await asyncio.gather(
            self.shadow_storage.recent_plans(site_uid, 1),
            self.adaptive_storage.latest_snapshot(site_uid),
        )
        if not plans:
            raise RuntimeError("no persisted Shadow Autopilot plan is available yet")
        battery = adaptive.battery if adaptive is not None else None
        change_probability = (
            max((item.probability for item in adaptive.change_points), default=0.0)
            if adaptive is not None
            else 0.0
        )
        return await asyncio.to_thread(
            recommend_dynamic_reserve,
            site_uid,
            plans[0],
            champion.policy,
            battery=battery,
            recent_change_probability=change_probability,
            upper_bound=getattr(
                self.settings,
                "policy_lab_dynamic_reserve_max_percent",
                60.0,
            ),
        )
