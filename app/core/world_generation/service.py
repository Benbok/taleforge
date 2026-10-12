"""Оркестратор подготовки (§6.3, §6.4): захват, план, предложение, проверка и запись — фаза за фазой.

Фазы одной кампании идут по одной под ``Coordination.generation_lock``, не под замком хода: ход ждёт подготовки
(``settle``), держа свой замок, и это не тупик. ``run_due`` — для восстановителя: только активированные фазы
(``requested_at``), закрытые неисследованные контейнеры не трогаются.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.content.catalog import campaign_catalog
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked, Plan, Proposal
from app.core.world_generation.policy import build_plan, check_reservation
from app.core.world_generation.profiles import ProfileError, load_profile
from app.core.world_generation.provider import DeterministicProvider
from app.core.world_generation.validation import validate
from app.core.world_tx import WorldConflict
from app.db.models import Campaign, Entity, LlmCall, WorldGenerationState, now
from app.gateway.events import envelope
from app.rules.dice import Dice

log = logging.getLogger(__name__)

LLM_LIMIT = 2  # вызовов модели за всю жизнь фазы: один и одна корректирующая попытка (§6.3)
MAX_STEPS = 6  # захватов на одну фазу за вызов: два конфликта и ожидание повтора укладываются


class Orchestrator:
    def __init__(self, coordination, bus=None, provider=None, dice_factory=Dice, llm=None, layout_provider=None):
        self.coordination = coordination
        self.llm = llm  # техническая модель (app/agents/world_generator.py); без неё — только детерминированно
        self.bus = bus
        self.provider = provider or DeterministicProvider()
        self.dice_factory = dice_factory
        from app.core.layout.provider import DeterministicLayoutProvider

        self.layout_provider = layout_provider or DeterministicLayoutProvider()

    async def settle(self, maker, campaign_id: str, refs: list[str]) -> None:
        """Ход ждёт терминального статуса своих подготовок (не дольше двух конфликтов каждой)."""
        for ref in sorted(set(refs)):
            await self.prepare(maker, campaign_id, ref)

    async def run_due(self, maker) -> None:
        async with maker() as s:
            q = select(WorldGenerationState).where(
                WorldGenerationState.status.in_(("unprepared", "preparing")),
                WorldGenerationState.requested_at.is_not(None),
            )
            t = now()
            todo = [(r.campaign_id, r.id) for r in await s.scalars(q) if storage.due(r, t)]
        for cid, ref in todo:
            try:
                await self.prepare(maker, cid, ref)
            except Exception:  # noqa: BLE001 — одна фаза не останавливает остальные
                log.exception("подготовка %s не удалась", ref)

    async def prepare(self, maker, campaign_id: str, ref: str) -> str:
        """Довести фазу до ``ready``/``blocked``. Иначе вернуть, почему остановились. Обстановка участка комплекса
        сначала ждёт его геометрию: размещать её не на чем."""
        for dep in await _dependencies(maker, campaign_id, ref):
            if await self.prepare(maker, campaign_id, dep) not in ("ready", "blocked"):
                return "pending"
        async with self.coordination.generation_lock(campaign_id):
            for _ in range(MAX_STEPS):
                got = await storage.claim(maker, campaign_id, ref)
                if got in ("later", "busy"):
                    await asyncio.sleep(storage.RETRY_AFTER.total_seconds())
                    continue
                if isinstance(got, str):
                    return got
                status = await self._run(maker, got)
                if status != "unprepared":
                    return status
            return "pending"

    async def _plan(self, maker, claim: storage.Claim) -> Draft:
        """План и детерминированное предложение из резерва; снимок места для модели, если она включена."""
        async with maker() as s:
            campaign = await s.get(Campaign, claim.campaign_id)
            row = await s.get(WorldGenerationState, claim.ref)
            catalog = await campaign_catalog(s, campaign)
            reservation = dict(row.reservation or {})
            check_reservation(reservation, campaign)
            try:
                profile = load_profile(catalog, reservation.get("profile_ref"))
            except ProfileError as e:
                raise Blocked("unsupported_source", str(e)) from e
            plan = build_plan(reservation, profile, row.target_entity_id)
            proposal = self.provider.propose(plan, catalog)
            draft = Draft(plan, proposal, catalog)
            if self.llm is not None and (campaign.settings or {}).get("scene_generation_llm") and plan.slots:
                draft.place = await _place(s, campaign.id, row.target_entity_id, profile)
                draft.model = await _model_of(s, campaign)
        validate(plan, proposal)
        return draft

    async def _propose(self, maker, claim: storage.Claim, draft: Draft) -> tuple[Proposal, str, storage.Claim]:
        """Предложение модели в пределах лимита вызовов фазы; иначе детерминированный fallback."""
        from app.agents import world_generator

        if draft.model is None:
            return draft.proposal, "normal", claim
        model, api_base, seat_id = draft.model
        msgs: list = []
        calls: list[LlmCall] = []
        reason = "llm_failed"
        try:
            while True:
                held = await storage.reserve_llm_call(maker, claim, LLM_LIMIT)
                if held is None:
                    reason = reason if calls else "llm_limit"  # лимит после отклонённого ответа — причина в ответе
                    break
                claim = held
                got, attempt, retry = await world_generator.ask(
                    self.llm, draft.plan, draft.place, draft.catalog, model=model, api_base=api_base, msgs=msgs
                )
                calls.append(
                    LlmCall(
                        campaign_id=claim.campaign_id,
                        seat_id=seat_id,
                        turn_id=None,
                        purpose=world_generator.PURPOSE,
                        model=attempt.model,
                        tokens_in=attempt.tokens_in,
                        tokens_out=attempt.tokens_out,
                        cost=attempt.cost,
                        latency_ms=attempt.latency_ms,
                        error=attempt.error,
                    )
                )
                if got is not None:
                    return got, "normal", claim
                if retry is None:
                    break  # сбой модели, а не ошибка ответа: корректировать нечего
                reason = "invalid_proposal"
        finally:
            if calls:
                async with maker() as s:
                    s.add_all(calls)
                    await s.commit()
        log.info("подготовка %s: fallback (%s)", claim.ref, reason)
        draft.plan.notes.append(f"fallback:{reason}")
        return draft.proposal, "fallback", claim

    async def _run(self, maker, claim: storage.Claim) -> str:
        from app.core.layout import executor

        try:
            phase = await storage.phase_of(maker, claim.ref)
            if phase in executor.PHASES:
                await executor.run(maker, self.dice_factory, claim, phase, self.layout_provider)
            else:
                draft = await self._plan(maker, claim)
                proposal, quality, claim = await self._propose(maker, claim, draft)
                await storage.commit_result(maker, self.dice_factory, claim, draft.plan, proposal, quality=quality)
        except Blocked as e:
            await storage.block(maker, claim, e.reason, e.detail)
            return "blocked"
        except WorldConflict:
            return await storage.release_conflict(maker, claim)
        except storage.LeaseLost:
            return "lost"
        except Exception as e:  # noqa: BLE001 — неожиданный сбой: диагностируемо, ведущий может повторить
            log.exception("подготовка %s упала", claim.ref)
            await storage.block(maker, claim, "internal_error", f"{type(e).__name__}: {e}")
            return "blocked"
        if self.bus is not None:
            await self.bus.publish(claim.campaign_id, envelope("map.changed", claim.campaign_id, {}), None)
        return "ready"


@dataclass
class Draft:
    plan: Plan
    proposal: Proposal
    catalog: Any
    place: dict[str, Any] = field(default_factory=dict)
    model: tuple[str, str | None, str | None] | None = None  # (модель, api_base, место для учёта)


async def _place(s, campaign_id: str, target_id: str, profile) -> dict[str, Any]:
    """Минимальный снимок для модели (§4.2): место, контейнер, тон и что уже стоит; без тайного каркаса."""
    target = await s.get(Entity, target_id)
    place = target if target.kind == "location" else await s.get(Entity, target.location_id)
    present = await s.scalars(
        select(Entity.name).where(
            Entity.campaign_id == campaign_id, Entity.location_id == place.id, Entity.kind == "object"
        )
    )
    return {
        "name": place.name,
        "description": place.description or "",
        "container": target.name if target.kind != "location" else None,
        "themes": list(profile.themes),
        "present": sorted(set(present))[:20],
    }


async def _model_of(s, campaign) -> tuple[str, str | None, str | None] | None:
    from app.agents.character import _model
    from app.agents.llm import parser_model_for
    from app.core.campaigns import Conflict

    try:
        _, _, api_base, _, seat_id = await _model(s, campaign, None)
    except Conflict:
        return None
    return parser_model_for(), api_base, seat_id


async def _dependencies(maker, campaign_id: str, ref: str) -> list[str]:
    """Неготовые фазы, без которых эту не выполнить: обстановке участка комплекса нужна его геометрия."""
    async with maker() as s:
        row = await s.get(WorldGenerationState, ref)
        if row is None or row.campaign_id != campaign_id or row.phase != "location_initial":
            return []
        dep = await storage.find(s, campaign_id, row.target_entity_id, "location_geometry")
        if dep is None or dep.status in ("ready", "blocked"):
            return []
        if await storage.activate_cas(s, dep):
            await s.commit()
        return [dep.id]
