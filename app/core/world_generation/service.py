"""Оркестратор подготовки (§6.3, §6.4): захват, план, предложение, проверка и запись — фаза за фазой.

Фазы одной кампании идут по одной под ``Coordination.generation_lock``, не под замком хода: ход ждёт подготовки
(``settle``), держа свой замок, и это не тупик. ``run_due`` — для восстановителя: только активированные фазы
(``requested_at``), закрытые неисследованные контейнеры не трогаются.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.content.catalog import campaign_catalog
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.core.world_generation.policy import build_plan, check_reservation
from app.core.world_generation.profiles import ProfileError, load_profile
from app.core.world_generation.provider import DeterministicProvider
from app.core.world_generation.validation import validate
from app.core.world_tx import WorldConflict
from app.db.models import Campaign, WorldGenerationState, now
from app.gateway.events import envelope
from app.rules.dice import Dice

log = logging.getLogger(__name__)

MAX_STEPS = 6  # захватов на одну фазу за вызов: два конфликта и ожидание повтора укладываются


class Orchestrator:
    def __init__(self, coordination, bus=None, provider=None, dice_factory=Dice):
        self.coordination = coordination
        self.bus = bus
        self.provider = provider or DeterministicProvider()
        self.dice_factory = dice_factory

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
        """Довести фазу до ``ready``/``blocked``. Иначе вернуть, почему остановились."""
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

    async def _plan(self, maker, claim: storage.Claim):
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
        validate(plan, proposal)
        return plan, proposal

    async def _run(self, maker, claim: storage.Claim) -> str:
        try:
            plan, proposal = await self._plan(maker, claim)
            await storage.commit_result(maker, self.dice_factory, claim, plan, proposal)
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
