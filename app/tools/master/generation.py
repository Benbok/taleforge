"""Идемпотентное наполнение по запросу ведущего, без LLM и побочных эффектов при чтении."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.world_generation import (
    GENERATOR_VERSION,
    PROFILES,
    choose_loot,
    digest,
    permitted_pool,
    source_snapshot,
    stable_seed,
)
from app.core.world_objects import read_world_object
from app.db.models import Entity, PlotAnchorBinding, WorldGenerationState, now
from app.tools.master.items import _container_state, _put_in_scene
from app.tools.registry import ToolContext, ToolError, tool

ProfileName = Literal["таверна", "дом", "склад", "лаборатория", "склеп", "пещера", "мастерская", "казарма"]


class ResolveLocationArgs(BaseModel):
    location_id: str = Field(description="реальный id локации, не название")
    profile: ProfileName = Field(description="структурированный профиль, без определения по названию комнаты")


class ResolveContainerArgs(BaseModel):
    container_id: str = Field(description="id контейнера с contents.status=unprepared")


async def _locked_state(ctx: ToolContext, target: Entity, phase: str) -> tuple[WorldGenerationState, bool]:
    """Локация/контейнер — сериализующий замок; новая запись в той же транзакции."""
    await ctx.session.flush()
    await ctx.session.refresh(target, with_for_update=True)
    record = await ctx.session.scalar(
        select(WorldGenerationState)
        .where(
            WorldGenerationState.campaign_id == ctx.campaign.id,
            WorldGenerationState.target_entity_id == target.id,
            WorldGenerationState.phase == phase,
        )
        .with_for_update()
    )
    if record is not None:
        if record.status == "ready":
            return record, True
        if record.status != "unprepared":
            raise ToolError("материализация заблокирована или выполняется; повторять без восстановления нельзя")
    else:
        record = WorldGenerationState(
            campaign_id=ctx.campaign.id, target_entity_id=target.id, phase=phase, status="unprepared"
        )
        ctx.session.add(record)
        await ctx.session.flush()
    return record, False


def _complete(
    record: WorldGenerationState, profile: str, seed: int, versions: list[str], context: str, result: dict
) -> None:
    record.status = "ready"
    record.quality = "normal"
    record.generator_version = GENERATOR_VERSION
    record.profile_ref = profile
    record.source_versions = versions
    record.context_digest = context
    record.seed = seed
    record.result_digest = digest(result)
    record.reservation = result
    record.lease_token = None
    record.lease_until = None
    record.revision += 1
    record.completed_at = now()
    record.updated_at = now()
    record.last_error = None


async def _create_loot(
    ctx: ToolContext,
    target: Entity,
    template_id: str,
    generation_id: str,
    *,
    container_id: str | None = None,
    story: bool = False,
) -> Entity:
    item, _ = await _put_in_scene(
        ctx,
        template_id,
        None,
        1,
        "near",
        place=target.location_id if container_id else target.id,
        container_id=container_id,
        force_new=True,
        force_unique=story,
        generation_ref=generation_id,
    )
    return item


@tool(
    "resolve_location",
    "Однократно наполняет локацию физическими контейнерами и строго ограниченной добычей по выбранному "
    "профилю. Повтор не создаёт вещей. Не вызывай для уже подробно заданной автором комнаты без решения ведущего.",
    ResolveLocationArgs,
    ids={"location_id": "locations"},
    closes=False,
)
async def resolve_location(ctx: ToolContext, a: ResolveLocationArgs) -> dict:
    target = ctx.world.entities.get(a.location_id)
    if target is None or target.kind != "location" or target.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    record, ready = await _locked_state(ctx, target, "location_initial")
    if ready:
        return {"location_id": target.id, "ready": True, "repeated": True, **record.reservation}

    profile = PROFILES[a.profile]
    entries = permitted_pool(ctx.world.catalog, profile)
    versions, source_digest = source_snapshot(entries, a.profile, "location_initial")
    seed = stable_seed(ctx.campaign.id, target.id, "location_initial", a.profile)
    # Сюжетная фиксация основана только на явно сохранённом snapshot, не на выводах генератора.
    reservations = (
        await ctx.session.scalars(
            select(PlotAnchorBinding)
            .where(
                PlotAnchorBinding.campaign_id == ctx.campaign.id,
                PlotAnchorBinding.target_location_id == target.id,
            )
            .order_by(PlotAnchorBinding.anchor_id)
            .with_for_update()
        )
    ).all()
    scripted: list[tuple[PlotAnchorBinding, str]] = []
    pending: list[str] = []
    for binding in reservations:
        if binding.state != "reserved" or binding.holder_entity_id is not None:
            continue  # раскрытые, утраченные и уже связанные зацепки не пересоздаём
        snapshot = binding.source_snapshot or {}
        template_id = snapshot.get("item_template_id")
        if template_id is None:
            pending.append(binding.anchor_id)
            continue  # сюжет без готового предметного шаблона остаётся резервом
        if not isinstance(template_id, str) or ctx.world.catalog.find(template_id, "item_template") is None:
            raise ToolError(f"сюжетный резерв {binding.anchor_id}: недоступен шаблон {template_id}")
        scripted.append((binding, template_id))

    record.status = "preparing"
    record.attempt_count += 1
    record.lease_token = secrets.token_hex(16)
    record.lease_until = now() + timedelta(minutes=2)
    await ctx.session.flush()
    chosen = choose_loot(entries, seed, profile.budget_cp, profile.floor_items)

    made_containers: list[str] = []
    created_items: list[str] = []
    bound: list[str] = []
    for name, visual in profile.containers:
        container = Entity(
            campaign_id=ctx.campaign.id,
            kind="object",
            name=name,
            location_id=target.id,
            zone="near",
            state={
                "visual_key": visual,
                "world_object": {
                    **_container_state(status="unprepared", profile=a.profile),
                    "generation_ref": record.id,
                },
            },
        )
        ctx.session.add(container)
        await ctx.session.flush()
        ctx.world.entities[container.id] = container
        made_containers.append(container.id)

    for entry in chosen:
        item = await _create_loot(ctx, target, entry.id, record.id)
        created_items.append(item.id)

    for binding, template_id in scripted:
        item = await _create_loot(ctx, target, template_id, record.id, story=True)
        binding.holder_entity_id = item.id
        binding.state = "materialized"
        bound.append(binding.anchor_id)

    result = {"containers": made_containers, "items": created_items, "anchors": bound, "pending_anchors": pending}
    context = digest((source_digest, [(b.anchor_id, b.plot_ref) for b in reservations]))
    _complete(record, a.profile, seed, versions, context, result)
    await ctx.record(
        "resolve_location",
        target_id=target.id,
        payload={
            "profile": a.profile,
            "generation_id": record.id,
            "containers": len(made_containers),
            "items": len(created_items),
            "plot_anchors": len(bound),
        },
        hidden=True,
    )
    ctx.signals.add("map.changed")
    return {"location_id": target.id, "ready": True, "repeated": False, **result}


@tool(
    "resolve_container",
    "Однократно материализует содержимое подготовленного генератором контейнера. Старые и ручные пустые "
    "контейнеры не наполняет. Повтор безопасен, в том числе если добыча уже унесена.",
    ResolveContainerArgs,
    closes=False,
)
async def resolve_container(ctx: ToolContext, a: ResolveContainerArgs) -> dict:
    target = ctx.world.entities.get(a.container_id)
    if target is None or target.kind != "object" or target.campaign_id != ctx.campaign.id:
        raise ToolError("контейнер отсутствует или находится в другой кампании")
    view = read_world_object(target)
    if view.role != "container" or view.metadata.get("physical") == "destroyed":
        raise ToolError("цель не является действующим контейнером")
    record, ready = await _locked_state(ctx, target, "container_contents")
    if ready:
        return {"container_id": target.id, "ready": True, "repeated": True, **record.reservation}
    state = dict((target.state or {}).get("world_object") or {})
    if state.get("contents", {}).get("status") != "unprepared" or state.get("origin") != "generated":
        # Существующие вручную созданные пустые контейнеры ничего не получают.
        await ctx.session.delete(record)
        return {"container_id": target.id, "ready": True, "repeated": True, "items": []}
    profile_name = state.get("generation_profile")
    if profile_name not in PROFILES:
        raise ToolError("у контейнера нет валидного профиля генерации")
    profile = PROFILES[profile_name]
    entries = permitted_pool(ctx.world.catalog, profile)
    versions, context = source_snapshot(entries, profile_name, "container_contents")
    seed = stable_seed(ctx.campaign.id, target.id, "container_contents", profile_name)
    record.status = "preparing"
    record.attempt_count += 1
    record.lease_token = secrets.token_hex(16)
    record.lease_until = now() + timedelta(minutes=2)
    await ctx.session.flush()
    chosen = choose_loot(entries, seed, profile.budget_cp, profile.container_items)
    items = []
    for entry in chosen:
        item = await _create_loot(ctx, target, entry.id, record.id, container_id=target.id)
        items.append(item.id)
    target.state = {
        **(target.state or {}),
        "world_object": {
            **state,
            "contents": {**state.get("contents", {}), "status": "ready"},
            "revision": int(state.get("revision", 0)) + 1,
        },
    }
    result = {"items": items}
    _complete(record, profile_name, seed, versions, context, result)
    await ctx.record(
        "resolve_container",
        target_id=target.id,
        payload={"generation_id": record.id, "items": len(items)},
        hidden=True,
    )
    ctx.changed.add(target.id)
    # Не публикуем список тайного содержимого в публичной карте; inspect_container проверяет открытие.
    return {"container_id": target.id, "ready": True, "repeated": False, **result}
