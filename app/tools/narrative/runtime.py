"""Runtime implementation of NarrativeApplier port (Task 14)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    LeaseLost,
    NarrativePolicy,
    WorkClaim,
)
from app.db.models import Campaign, NarrativeWork, as_utc
from app.rules.dice import Dice
from app.tools.narrative.executor import apply_in_context
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)


class RuntimeNarrativeApplier:
    """Infrastructure adapter applying proposals in a database transaction with world lock."""

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        bus: Any,
        coordination: Any,
        *,
        policy_provider: Callable[[str], NarrativePolicy],
        dice_factory: Callable[[], Dice] = Dice,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._bus = bus
        self._coordination = coordination
        self._policy_provider = policy_provider
        self._dice_factory = dice_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def apply(
        self,
        proposal: AdaptationProposal,
        *,
        claim: WorkClaim | None = None,
    ) -> AdaptationResult:
        cid = proposal.source.campaign_id
        policy = self._policy_provider(cid)

        turn_lock = None
        if self._coordination is not None and hasattr(self._coordination, "turn_lock"):
            turn_lock = self._coordination.turn_lock(cid)

        if turn_lock is not None:
            async with turn_lock:
                return await self._apply_transaction(cid, proposal, policy, claim=claim)
        return await self._apply_transaction(cid, proposal, policy, claim=claim)

    async def _apply_transaction(
        self,
        cid: str,
        proposal: AdaptationProposal,
        policy: NarrativePolicy,
        *,
        claim: WorkClaim | None = None,
    ) -> AdaptationResult:
        async with self._session_maker() as session:
            campaign = await session.get(Campaign, cid)
            if campaign is None:
                return AdaptationResult(status="failed", reason_code="campaign_not_found")

            # Replan=false, конец кампании или strict: черновик ждёт, мир не меняется, источник не сгорает
            if await director_blocker(session, campaign, check_budget=False) is not None:
                return AdaptationResult(status="deferred", reason_code="adaptation_paused")

            mode = (campaign.settings or {}).get("narrative_mode")
            if mode:
                policy = policy.model_copy(update={"mode": mode})

            # Verify server-owned claim and lease validity before writing (R12)
            if claim is not None:
                if (
                    claim.campaign_id != cid
                    or claim.proposal_id != proposal.proposal_id
                    or claim.source.campaign_id != cid
                    or claim.source.source_id != claim.work_id
                ):
                    raise LeaseLost("Work/source/proposal mismatch")

                now_utc = as_utc(self._clock())
                work = await session.scalar(
                    select(NarrativeWork).where(
                        NarrativeWork.id == claim.work_id,
                        NarrativeWork.lease_token == claim.lease_token,
                    )
                )
                if work is None or work.lease_until is None or as_utc(work.lease_until) <= now_utc:
                    raise LeaseLost(f"Lease lost or expired for job {claim.work_id}")

            dice = self._dice_factory()
            ctx = await open_context(session, campaign, dice, turn_id=None, seat_id=None)
            result = await apply_in_context(ctx, proposal, policy=policy)
            await flush_outbox(session, ctx)
            await session.commit()

            # Publish changes after commit (R14)
            if self._bus is not None and result.status in ("applied", "no_change"):
                await publish_changes(self._bus, ctx, [])

            return result


async def director_blocker(session: AsyncSession, campaign: Campaign, *, check_budget: bool = True) -> str | None:
    """Почему режиссёр сейчас не работает для кампании; None — может. Проверяется до сети и до записи мира."""
    from sqlalchemy import func

    from app.db.models import LlmCall
    from app.db.narrative import ensure_state

    settings = campaign.settings or {}
    if campaign.status not in ("active", "paused"):  # лобби ещё не играет, завершённая — уже не меняется
        return "campaign_not_running"
    if settings.get("replan") is False:
        return "replan_off"
    if (await ensure_state(session, campaign.id)).mode != "adaptive":
        return "strict_mode"
    limit = settings.get("spend_limit_usd")
    if check_budget and limit is not None:
        spent = await session.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == campaign.id))
        if float(spent or 0.0) >= float(limit):
            return "spend_limit"
    return None


STEPS_PER_TICK = 3  # автор, применение и одна повторная попытка на кампанию за проход восстановителя


class NarrativePreparerAdapter:
    """MasterService.narrative_preparer: режиссёр только для кампаний, которым он сейчас разрешён."""

    def __init__(self, service: Any, session_maker: async_sessionmaker[AsyncSession]) -> None:
        self.service = service
        self.session_maker = session_maker

    async def _allowed(self, campaign_id: str) -> bool:
        async with self.session_maker() as s:
            campaign = await s.get(Campaign, campaign_id)
            allowed = campaign is not None and await director_blocker(s, campaign) is None
            await s.rollback()  # ensure_state мог создать строку: чтение не пишет
        return allowed

    async def prepare_once(self, campaign_id: str) -> Any:
        if not await self._allowed(campaign_id):
            return None  # задание остаётся в очереди: включат replan или поднимут лимит — продолжится
        return await self.service.prepare_once(campaign_id)

    async def run_due(self, *, limit: int = 20) -> tuple[Any, ...]:
        """Кампании с ожидающими заданиями по очереди; сбой одной не прерывает остальные (R15)."""
        async with self.session_maker() as s:
            q = (
                select(NarrativeWork.campaign_id)
                .where(NarrativeWork.status.in_(("pending", "prepared", "retry_wait", "preparing")))
                .distinct()
            )
            cids = list((await s.scalars(q)).all())
        reports = []
        for cid in cids[:limit]:
            try:
                for _ in range(STEPS_PER_TICK):  # черновик, затем его применение — в одном тике
                    rep = await self.prepare_once(cid)
                    if rep is None:
                        break
                    reports.append(rep)
                    if rep.status != "prepared":
                        break
            except Exception:  # noqa: BLE001 — одна кампания не останавливает остальные
                log.exception("фоновая адаптация кампании %s не удалась", cid)
        return tuple(reports)
