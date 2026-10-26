"""Durable hero → one eligible enemy → shared step. No model I/O under write locks."""

import hashlib
from dataclasses import replace
from datetime import UTC, timedelta

from sqlalchemy import select

from app.core.campaigns import AccessDenied, Conflict
from app.core.universal.clock import clock_view, complete_step, lock_campaign
from app.core.universal.combat_actions import effective_actor, initialize_combatant
from app.core.universal.inventory import create_item, ensure_inventory, equipped_items, state_of
from app.core.universal.profiles import load_actor
from app.core.universal.validation import authorize_actor
from app.db.models import Character, CombatExchange, Entity, Event, now
from app.rules.universal.exploration import (
    AbilityDefinitionV2,
    EffectIntentV2,
    ExplorationAction,
    ExplorationOutcome,
    definition_key,
)
from app.rules.universal.items import ItemProfile


def enemy_source_key(source):
    return "reply-" + hashlib.sha256(source.encode()).hexdigest()[:40]


async def eligible_enemies(ctx, exchange):
    s = ctx.session
    hero = await s.get(Character, exchange.actor_id)
    targets = []
    for player in await s.scalars(
        select(Character)
        .where(
            Character.campaign_id == ctx.campaign_id,
            Character.location_id == hero.location_id,
            Character.status.in_(["active", "approved"]),
            Character.seat_id.is_not(None),
        )
        .execution_options(populate_existing=True)
    ):
        if (await load_actor(s, ctx.campaign_id, player.id))[1].hp > 0:
            targets.append(player.id)
    if not targets:
        return []
    result = []
    for foe in await s.scalars(
        select(Entity)
        .where(Entity.campaign_id == ctx.campaign_id, Entity.kind == "creature", Entity.location_id == hero.location_id)
        .execution_options(populate_existing=True)
    ):
        from app.core.universal.visibility import visible_entity

        if not foe.state.get("hostile") or not await visible_entity(s, ctx.campaign_id, hero.id, foe):
            continue
        await initialize_combatant(s, ctx.campaign_id, foe.id)
        if (await load_actor(s, ctx.campaign_id, foe.id))[1].hp <= 0:
            continue
        state = await effective_actor(s, ctx.campaign_id, foe.id, pending_event_id=exchange.hero_event_id)
        if state["cannot_act"] or state["cannot_target"] or (state["cannot_move"] and foe.zone == "far"):
            continue
        result.append(dict(actor_id=foe.id, name=foe.name, target_ids=targets, zone=foe.zone))
    return sorted(result, key=lambda row: ({"melee": 0, "near": 1, "far": 2}.get(row["zone"], 3), row["actor_id"]))


async def authorize_enemy(ctx, proposal, *, require_active=True):
    row = await ctx.session.get(CombatExchange, ctx.exchange_id, populate_existing=True)
    if (
        row is None
        or row.campaign_id != ctx.campaign_id
        or row.enemy_actor_id != ctx.actor_id
        or row.source_key != ctx.parent_source_id
        or proposal.actor_id != ctx.actor_id
    ):
        raise AccessDenied("Нет сохранённого права на ответ врага")
    actor = await ctx.session.get(Entity, ctx.actor_id, populate_existing=True)
    if actor is None or actor.campaign_id != ctx.campaign_id:
        raise AccessDenied("Враг недоступен")
    if require_active:
        choices = await eligible_enemies(ctx, row)
        if row.status != "reply_pending" or not any(
            c["actor_id"] == actor.id and row.enemy_target_id in c["target_ids"] for c in choices
        ):
            raise AccessDenied("Враг больше не может ответить")
    return actor


async def _reply_action(ctx, exchange):
    s = ctx.session
    await ensure_inventory(s, ctx.campaign_id, exchange.enemy_actor_id)
    weapons = [
        row
        for row in await equipped_items(s, ctx.campaign_id, exchange.enemy_actor_id)
        if state_of(row).profile.kind == "weapon"
    ]
    if not weapons:
        weapons = [
            await create_item(
                s,
                ctx.campaign_id,
                exchange.enemy_actor_id,
                ItemProfile(name="Удар", kind="weapon"),
                "natural-attack",
                equipped=True,
            )
        ]
    weapon = weapons[0]
    spec = EffectIntentV2(kind="weapon_attack", object_id=weapon.id)
    definition = AbilityDefinitionV2(
        name="Ответ врага", source="item", attribute=state_of(weapon).profile.attribute, effects=[spec], delivery="item"
    )
    definition.id = definition_key(definition)
    return ExplorationAction(
        actor_id=exchange.enemy_actor_id,
        source_message_id=enemy_source_key(exchange.source_key),
        source_hash=exchange.proposal["source_hash"],
        definition=definition,
        resolution="attack",
        attribute=definition.attribute,
        difficulty=12,
        targets=[exchange.enemy_target_id],
        operations=[spec],
        cost=0,
        elapsed_game_seconds=int(exchange.elapsed_seconds),
    )


def _results(exchange, repeated=False):
    results = []
    for value in (exchange.hero_outcome, exchange.enemy_outcome):
        if value is not None:
            outcome = ExplorationOutcome.model_validate(value)
            if repeated:
                outcome = outcome.model_copy(update={"status": "repeated"})
            results.append(outcome)
    return results


async def run_exchange(ctx, action, choose_reply=None, request_key=None):
    from app.core.universal.exploration_resolution import resolve_exploration

    if ctx.npc_reply:
        raise AccessDenied("Ответ врага не открывает новый обмен")
    s = ctx.session
    request_key = request_key or action.source_message_id
    await lock_campaign(s, ctx.campaign_id)
    await authorize_actor(ctx, action, require_active=False)
    exchange = await s.scalar(
        select(CombatExchange).where(
            CombatExchange.campaign_id == ctx.campaign_id, CombatExchange.source_key == request_key
        )
    )
    if exchange is None:
        pending = await s.scalar(
            select(CombatExchange.id).where(
                CombatExchange.campaign_id == ctx.campaign_id, CombatExchange.status.not_in(["ticks_done", "rejected"])
            )
        )
        if pending:
            raise Conflict("Сначала должен завершиться предыдущий игровой шаг")
        clock = await clock_view(s, ctx.campaign_id)
        exchange = CombatExchange(
            campaign_id=ctx.campaign_id,
            source_key=request_key,
            actor_id=action.actor_id,
            proposal=action.model_dump(mode="json"),
            sequence=str(int(clock["step_index"]) + 1),
            started_seconds=clock["game_seconds"],
            elapsed_seconds=str(action.elapsed_game_seconds),
            status="hero_pending",
        )
        s.add(exchange)
        await s.flush()
    elif ExplorationAction.model_validate(exchange.proposal).model_dump(mode="json") != action.model_dump(mode="json"):
        raise Conflict("Сохранённое действие изменено")
    if exchange.status in {"ticks_done", "rejected"}:
        return _results(exchange, True)
    exchange_id = exchange.id
    if exchange.status == "hero_pending":
        result = await resolve_exploration(replace(ctx, defer_step=True, exchange_id=exchange_id), action, request_key)
        exchange.hero_outcome = result.model_dump(mode="json")
        if result.status == "denied":
            exchange.status = "rejected"
            await s.commit()
            return _results(exchange)
        event = await s.scalar(
            select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == request_key)
        )
        exchange.hero_event_id = event.id
        exchange.status = "reply_pending"
        await s.commit()
    if exchange.status == "reply_pending":
        if exchange.selection_attempted:
            expires = exchange.selection_expires_at
            if expires and expires.replace(tzinfo=UTC) > now():
                await s.rollback()
                raise Conflict("Ответ врага ещё подготавливается; действие героя уже сохранено")
            choice = (
                dict(actor_id=exchange.enemy_actor_id, target_id=exchange.enemy_target_id)
                if exchange.enemy_actor_id
                else None
            )
        else:
            choices = await eligible_enemies(ctx, exchange)
            exchange.selection_attempted = True
            if choose_reply is None:
                choice = (
                    dict(actor_id=choices[0]["actor_id"], target_id=choices[0]["target_ids"][0]) if choices else None
                )
                if choice:
                    exchange.enemy_actor_id, exchange.enemy_target_id = choice["actor_id"], choice["target_id"]
                await s.commit()
            else:
                exchange.selection_expires_at = now() + timedelta(seconds=30)
                await s.commit()
                try:
                    choice = await choose_reply(dict(enemies=choices, source_key=request_key)) if choices else None
                except Exception:
                    choice = None
        await lock_campaign(s, ctx.campaign_id)
        exchange = await s.get(CombatExchange, exchange_id, populate_existing=True)
        if exchange.status == "reply_pending":
            exchange.selection_expires_at = None
            current = await eligible_enemies(ctx, exchange)
            eligible = choice is not None and any(
                c["actor_id"] == choice.get("actor_id") and choice.get("target_id") in c["target_ids"] for c in current
            )
            if eligible:
                exchange.enemy_actor_id = choice["actor_id"]
                exchange.enemy_target_id = choice["target_id"]
                await s.flush()
                reply = await _reply_action(ctx, exchange)
                npc_ctx = replace(
                    ctx,
                    actor_id=exchange.enemy_actor_id,
                    npc_reply=True,
                    defer_step=True,
                    parent_source_id=exchange.source_key,
                    exchange_id=exchange.id,
                    pending_event_id=exchange.hero_event_id,
                    allowed_target_ids=frozenset(c for e in current for c in e["target_ids"]),
                )
                result = await resolve_exploration(npc_ctx, reply, reply.source_message_id)
                if result.status in {"applied", "repeated"}:
                    exchange.enemy_outcome = result.model_dump(mode="json")
            exchange.status = "ticks_pending"
            await s.commit()
    await lock_campaign(s, ctx.campaign_id)
    exchange = await s.get(CombatExchange, exchange_id, populate_existing=True)
    if exchange.status == "ticks_pending":
        # Combat regeneration is suppressed for the complete hero/reply pair, including a saved pass.
        from app.core.world import get_scene

        scene = await get_scene(s, ctx.campaign_id)
        from app.core.universal.encounters import hostile_locations

        if scene is not None:
            scene.mode = "combat" if await hostile_locations(s, ctx.campaign_id) else "free"
        step = await complete_step(s, ctx.campaign_id, request_key, int(exchange.elapsed_seconds), dice=ctx.dice)
        exchange.changes = step.changes
        from app.core.universal.vitality import progress_unconscious_party

        continuation = await progress_unconscious_party(ctx, request_key)
        exchange.changes = [*exchange.changes, *(c.model_dump(mode="json") for c in continuation)]
        exchange.status = "ticks_done"
        await s.commit()
    return _results(exchange)
