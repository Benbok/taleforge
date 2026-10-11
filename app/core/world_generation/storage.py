"""Резерв, lease и атомарная материализация (§4.4, §6.3, §6.4).

- ``reserve_root`` / ``activate`` — в транзакции команды: строка фазы с неизменным резервом и запрос подготовки;
- ``claim`` — короткая ``world_write``: условный UPDATE строки → ``preparing``, токен, lease 90 секунд и снимок
  ревизии мира, от которой считается результат;
- ``commit_result`` — одна ``world_write`` с ожидаемой ревизией снимка: CAS строки по токену и ревизии, все
  объекты, резервы детей, сводка контейнера, manifest и событие. Любая ошибка откатывает всё;
- ``release_conflict`` — мир изменился: lease освобождается, второй конфликт — ``blocked/stale_context``;
- ``block`` — диагностируемая причина без повторов.

Время — часы процесса (сервер однопроцессный), не БД: отступление от §6.3, см. docs/world-objects-delivery3.md.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.world_generation.contracts import POLICY_VERSION, Plan, Proposal, digest
from app.core.world_generation.policy import root_reservation
from app.core.world_generation.profiles import ProfileError, load_profile, profile_ref_for
from app.core.world_objects import read_world_object
from app.core.world_tx import world_write
from app.db.models import Campaign, Entity, PlotAnchorBinding, WorldGenerationState, as_utc, now

log = logging.getLogger(__name__)

WGS = WorldGenerationState
LEASE = timedelta(seconds=90)
RETRY_AFTER = timedelta(seconds=1)
MAX_CONFLICTS = 2


class LeaseLost(Exception):
    """Lease истёк или строку ведёт другой владелец: работа бросается без записи."""


@dataclass(frozen=True)
class Claim:
    ref: str
    campaign_id: str
    token: str
    revision: int  # ревизия строки после захвата
    world_revision: int  # ревизия мира после захвата: от неё посчитан результат
    lease_until: datetime


# --- в транзакции команды ---


def authored_templates(entities: dict[str, Entity], place_id: str) -> list[str | None]:
    """Предметы, уже лежащие в месте до подготовки (авторская добыча): по шаблону на каждую единицу."""
    from app.core.world import is_scene_item

    out: list[str | None] = []
    for e in sorted(entities.values(), key=lambda x: x.id):
        if e.location_id != place_id or not is_scene_item(e):
            continue
        raw = (e.state or {}).get("world_object")
        if isinstance(raw, dict) and raw.get("generation_ref"):
            continue
        out.extend([e.template_id] * max(1, int((e.state or {}).get("qty") or 1)))
    return out


async def find(session: AsyncSession, campaign_id: str, target_id: str, phase: str) -> WorldGenerationState | None:
    return await session.scalar(
        select(WGS).where(WGS.campaign_id == campaign_id, WGS.target_entity_id == target_id, WGS.phase == phase)
    )


async def reserve_root(session: AsyncSession, campaign: Campaign, world: Any, location: Entity) -> WorldGenerationState:
    """Корень места: резерв фиксируется один раз. Неверный профиль — сразу ``blocked/unsupported_source``."""
    row = await find(session, campaign.id, location.id, "location_initial")
    if row is not None:
        return row
    ref = profile_ref_for(location, world.catalog)
    try:
        profile = load_profile(world.catalog, ref)
    except ProfileError as e:
        row = WGS(
            campaign_id=campaign.id,
            target_entity_id=location.id,
            phase="location_initial",
            status="blocked",
            last_error="unsupported_source",
            profile_ref=ref,
            generator_version=POLICY_VERSION,
            result_manifest={"blocked": "unsupported_source", "detail": str(e)},
        )
    else:
        reservation = root_reservation(campaign, location.id, profile, authored_templates(world.entities, location.id))
        row = WGS(
            campaign_id=campaign.id,
            target_entity_id=location.id,
            phase="location_initial",
            status="unprepared",
            reservation=reservation,
            seed=reservation["seed"],
            profile_ref=profile.ref,
            source_versions=[profile.source],
            generator_version=POLICY_VERSION,
        )
    session.add(row)
    await session.flush()
    return row


def activate(row: WorldGenerationState) -> bool:
    """Запрос подготовки. Повторный запрос ничего не меняет."""
    if row.status != "unprepared" or row.requested_at is not None:
        return False
    t = now()
    row.requested_at = t
    row.next_attempt_at = t
    row.revision += 1
    return True


def retry(row: WorldGenerationState) -> None:
    """Повтор ведущего: ``blocked → unprepared``, тот же seed и резерв, счётчик конфликтов сброшен."""
    t = now()
    row.status = "unprepared"
    row.last_error = None
    row.result_manifest = None
    row.conflict_count = 0
    row.lease_token = None
    row.lease_until = None
    row.requested_at = row.requested_at or t
    row.next_attempt_at = t
    row.revision += 1


# --- исполнитель ---


async def _plot_conflict(session: AsyncSession, row: WorldGenerationState) -> bool:
    """Сюжетные обязательства — поставка 4: зарезервированная зацепка у цели не игнорируется."""
    q = select(PlotAnchorBinding.id).where(
        PlotAnchorBinding.campaign_id == row.campaign_id,
        PlotAnchorBinding.state == "reserved",
        (PlotAnchorBinding.target_location_id == row.target_entity_id)
        | (PlotAnchorBinding.holder_entity_id == row.target_entity_id),
    )
    return (await session.scalar(q)) is not None


def due(row: WorldGenerationState, t: datetime | None = None) -> bool:
    t = t or now()
    if row.status == "unprepared":
        return row.requested_at is not None and (row.next_attempt_at is None or as_utc(row.next_attempt_at) <= t)
    if row.status == "preparing":
        return row.lease_until is None or as_utc(row.lease_until) <= t
    return False


async def claim(maker, campaign_id: str, ref: str) -> Claim | str:
    """Захват фазы. Строка — почему не захвачена: ``ready``, ``blocked``, ``unexamined``, ``later`` (ждёт
    ``next_attempt_at``), ``leased`` (живой lease), ``busy`` (строку изменили между чтением и захватом), ``unknown``."""
    async with maker() as s:
        row = await s.get(WGS, ref)
        if row is None or row.campaign_id != campaign_id:
            return "unknown"
        if row.status in ("ready", "blocked"):
            return row.status
        if row.status == "unprepared" and row.requested_at is None:
            return "unexamined"
        t = now()
        if not due(row, t):
            return "later" if row.status == "unprepared" else "leased"
        base = row.revision  # ORM-UPDATE ниже синхронизирует объект сессии: ревизию запоминаем до него
        conflict = await _plot_conflict(s, row)
        world = await world_write(s, campaign_id)
        if world is None:
            return "unknown"
        cas = (WGS.id == ref) & (WGS.revision == base) & (WGS.status == row.status)
        if conflict:
            values: dict[str, Any] = {
                "status": "blocked",
                "last_error": "plot_conflict",
                "lease_token": None,
                "lease_until": None,
                "result_manifest": {"blocked": "plot_conflict", "detail": "у цели зарезервирована сюжетная зацепка"},
                "revision": WGS.revision + 1,
                "updated_at": t,
            }
            done = await s.execute(update(WGS).where(cas).values(**values))
            if done.rowcount != 1:
                await s.rollback()
                return "busy"
            await s.commit()
            return "blocked"
        token = secrets.token_hex(16)
        until = t + LEASE
        done = await s.execute(
            update(WGS)
            .where(cas)
            .values(
                status="preparing",
                lease_token=token,
                lease_until=until,
                attempt_count=WGS.attempt_count + 1,
                context_digest=digest({"reservation": row.reservation, "world_revision": world}),
                revision=WGS.revision + 1,
                updated_at=t,
            )
        )
        if done.rowcount != 1:
            await s.rollback()
            return "busy"
        await s.commit()
        return Claim(ref, campaign_id, token, base + 1, world, until)


async def _close(maker, claim: Claim, values: dict[str, Any]) -> bool:
    """Условная запись строки по токену и ревизии захвата."""
    async with maker() as s:
        await world_write(s, claim.campaign_id)
        cas = (WGS.id == claim.ref) & (WGS.lease_token == claim.token) & (WGS.revision == claim.revision)
        done = await s.execute(update(WGS).where(cas).values(**values, revision=WGS.revision + 1, updated_at=now()))
        if done.rowcount != 1:
            await s.rollback()
            return False
        await s.commit()
        return True


async def block(maker, claim: Claim, reason: str, detail: str = "") -> bool:
    log.info("подготовка %s заблокирована: %s %s", claim.ref, reason, detail)
    return await _close(
        maker,
        claim,
        {
            "status": "blocked",
            "last_error": reason,
            "lease_token": None,
            "lease_until": None,
            "result_manifest": {"blocked": reason, "detail": detail},
        },
    )


async def release_conflict(maker, claim: Claim) -> str:
    """Мир изменился между снимком и записью. Возвращает новый статус строки или ``lost``."""
    async with maker() as s:
        row = await s.get(WGS, claim.ref)
        if row is None or row.lease_token != claim.token or row.revision != claim.revision:
            return "lost"
        count = int(row.conflict_count or 0) + 1
    values: dict[str, Any] = {"conflict_count": count, "lease_token": None, "lease_until": None}
    if count >= MAX_CONFLICTS:
        values |= {
            "status": "blocked",
            "last_error": "stale_context",
            "result_manifest": {"blocked": "stale_context", "detail": "мир менялся во время подготовки"},
        }
    else:
        values |= {"status": "unprepared", "next_attempt_at": now() + RETRY_AFTER}
    if not await _close(maker, claim, values):
        return "lost"
    return values["status"]


def _object_state(role: str, ref: str, parent: str | None, visual_key: str | None) -> dict[str, Any]:
    return {
        **({"visual_key": visual_key} if visual_key else {}),
        "world_object": {
            "schema_version": 1,
            "role": role,
            "unique": False,
            "container_id": parent,
            "capabilities": ["inspect"],
            "revision": 0,
            "origin": "generated",
            "generation_ref": ref,
        },
    }


async def commit_result(maker, dice_factory, claim: Claim, plan: Plan, proposal: Proposal) -> dict[str, Any]:
    """Записать результат одной транзакцией. ``WorldConflict`` — мир изменился после снимка; ``LeaseLost`` —
    строку ведёт другой владелец; ``Blocked`` — цель исчезла. Во всех случаях ничего не записано."""
    from app.core.object_policy import observe
    from app.core.world_generation.contracts import Blocked
    from app.tools.master.items import _container_state, _put_in_scene
    from app.tools.runtime import open_context

    async with maker() as s:
        campaign = await s.get(Campaign, claim.campaign_id)
        await world_write(s, claim.campaign_id, claim.world_revision)
        if now() >= claim.lease_until:
            raise LeaseLost(claim.ref)
        cas = (
            (WGS.id == claim.ref)
            & (WGS.lease_token == claim.token)
            & (WGS.revision == claim.revision)
            & (WGS.status == "preparing")
        )
        done = await s.execute(update(WGS).where(cas).values(revision=WGS.revision + 1, updated_at=now()))
        if done.rowcount != 1:
            raise LeaseLost(claim.ref)
        ctx = await open_context(s, campaign, dice_factory(), turn_id=None, seat_id=None)
        row = await s.get(WGS, claim.ref)
        target = ctx.world.entities.get(plan.target_id)
        root = plan.phase == "location_initial"
        if target is None or target.kind != ("location" if root else "object"):
            raise Blocked("target_missing", "цели подготовки больше нет")
        if not root:
            view = read_world_object(target)
            if view.role != "container" or view.metadata.get("physical") == "destroyed":
                raise Blocked("target_missing", "контейнер разрушен или больше не контейнер")
        place = target.id if root else target.location_id
        parent = None if root else target.id

        made: dict[str, str] = {}
        children: dict[str, str] = {}
        by_slot = {o.slot_ref: o for o in proposal.objects}
        for slot in plan.slots:
            obj = by_slot.get(slot.slot_ref)
            if obj is None:
                continue  # обстановку предложение может опустить
            if slot.role == "item":
                rec = ctx.world.catalog.find(slot.template_id or "", "item_template")
                shown = None if rec is not None and obj.name == rec.name else obj.name
                en, _ = await _put_in_scene(
                    ctx,
                    slot.template_id or "",
                    shown,
                    1,
                    slot.zone,
                    obj.description,
                    place=place,
                    container_id=parent,
                    force_new=True,
                    generation_ref=row.id,
                )
            else:
                if slot.role == "container":
                    state = {
                        "visual_key": slot.visual_key or "item:chest",
                        "world_object": {
                            **_container_state(status="unprepared", profile=row.profile_ref),
                            "container_id": parent,
                            "generation_ref": row.id,
                        },
                    }
                else:
                    state = _object_state("prop", row.id, parent, slot.visual_key)
                en = Entity(
                    campaign_id=campaign.id,
                    kind="object",
                    name=obj.name,
                    description=obj.description,
                    location_id=place,
                    zone=slot.zone,
                    state=state,
                )
                s.add(en)
                await s.flush()
                ctx.world.entities[en.id] = en
            made[slot.slot_ref] = en.id
            if slot.role == "container":
                reservation = plan.children[slot.slot_ref]
                child = WGS(
                    campaign_id=campaign.id,
                    target_entity_id=en.id,
                    phase="container_contents",
                    status="unprepared",
                    reservation=reservation,
                    seed=reservation["seed"],
                    profile_ref=row.profile_ref,
                    source_versions=list(row.source_versions or []),
                    generator_version=POLICY_VERSION,
                )
                s.add(child)
                await s.flush()
                children[slot.slot_ref] = child.id

        if not root:
            st = dict(target.state or {})
            wo = dict(st.get("world_object") or {})
            wo["contents"] = {**(wo.get("contents") or {}), "status": "ready"}
            wo["revision"] = int(wo.get("revision") or 0) + 1
            target.state = {**st, "world_object": wo}
        manifest = {
            "schema_version": 1,
            "phase": plan.phase,
            "path": plan.reservation.get("path"),
            "objects": [{"slot_ref": k, "id": v} for k, v in made.items()],
            "children": children,
            "spent": plan.spent,
        }
        t = now()
        row.status = "ready"
        row.quality = "normal"
        row.lease_token = None
        row.lease_until = None
        row.last_error = None
        row.completed_at = t
        row.result_manifest = manifest
        row.result_digest = digest(manifest)
        await ctx.record(
            "prepare_scene",
            target_id=target.id,
            payload={"generation_id": row.id, "phase": plan.phase, "objects": len(made), "spent": plan.spent},
            hidden=True,
        )
        await observe(ctx, place, [], only=list(made.values()))
        await s.commit()
        return manifest
