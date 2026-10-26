"""Authenticated equipment controls execute the same saved action/exchange as chat."""

import hashlib

from sqlalchemy import select

from app.agents.master.action_results import public_outcome
from app.core.campaigns import AccessDenied, Conflict
from app.core.chat import active_session, next_seq
from app.core.universal.clock import lock_campaign
from app.core.universal.combat import enemy_source_key, run_exchange
from app.core.universal.effects import scope_changes
from app.core.universal.exploration_views import exploration_game_card
from app.core.universal.interpretation import compile_exploration
from app.core.universal.inventory import ensure_inventory
from app.core.universal.references import location_reference
from app.core.universal.resolution import ResolutionContext
from app.core.universal.rolls import ensure_completion_message, ensure_roll_message
from app.core.universal.scene import universal_scene
from app.db.models import Character, CombatExchange, Entity, MasterTurn, Message, now
from app.rules.universal.exploration import EffectChange, EffectIntentV2, ExplorationAction, IntentReview, IntentV2


async def perform_item_action(session, viewer, hero, body, dice):
    if not viewer.seat or viewer.seat.id != hero.seat_id or hero.sheet.get("rules_version") != "universal.v1":
        raise AccessDenied("Действие доступно игроку этого героя")
    game = await active_session(session, hero.campaign_id)
    if game is None:
        raise Conflict("Начните игровую сессию")
    await lock_campaign(session, hero.campaign_id)
    await ensure_inventory(session, hero.campaign_id, hero.id)
    mid = "m_" + hashlib.sha256(f"{hero.campaign_id}:{hero.id}:{body.request_key}".encode()).hexdigest()[:24]
    binding = body.model_dump(mode="json")
    source = await session.get(Message, mid)
    if source is not None and (source.intent or {}).get("item_control") != binding:
        raise Conflict("Ключ действия уже использован с другими параметрами")
    scene = await universal_scene(session, viewer.campaign, viewer)
    allowed = {e["id"] for e in scene.get("entities", [])} | {hero.id}
    allowed.update(
        row.id
        for row in await session.scalars(
            select(Character).where(
                Character.campaign_id == hero.campaign_id,
                Character.location_id == hero.location_id,
                Character.status.in_(["active", "approved"]),
            )
        )
    )
    ctx = ResolutionContext(
        session, hero.campaign_id, viewer.user.id, viewer.seat.id, hero.id, dice, frozenset(allowed)
    )
    audience = [
        row.seat_id
        for row in await session.scalars(
            select(Character).where(
                Character.campaign_id == hero.campaign_id,
                Character.location_id == hero.location_id,
                Character.status.in_(["active", "approved"]),
                Character.seat_id.is_not(None),
            )
        )
    ]
    if source is None:
        if body.kind == "weapon_attack" and not body.target_id:
            raise Conflict("Выберите цель атаки")
        if body.kind != "guard" and not body.item_id:
            raise Conflict("Выберите предмет")
        item = await session.get(Entity, body.item_id) if body.item_id else None
        if body.kind != "guard" and (item is None or item.campaign_id != hero.campaign_id):
            raise AccessDenied("Предмет недоступен")
        label = {
            "equip": "Надеваю",
            "unequip": "Снимаю",
            "consume": "Использую",
            "weapon_attack": "Атакую",
            "guard": "Защищаюсь",
        }[body.kind]
        text = f"{label}: {item.name}." if item else label + "."
        source = Message(
            id=mid,
            campaign_id=hero.campaign_id,
            session_id=game.id,
            seat_id=hero.seat_id,
            author_user_id=viewer.user.id,
            seq=await next_seq(session, hero.campaign_id),
            kind="action",
            content=text,
            intent={"item_control": binding},
            visible_to=audience,
        )
        session.add(source)
        await session.flush()
        targets = [body.target_id or hero.id]
        op = EffectIntentV2(
            kind=body.kind, object_id=body.item_id, target_id=body.target_id if body.kind == "consume" else None
        )
        intent = IntentV2(
            name=text,
            source="item" if body.kind in {"weapon_attack", "consume"} else "mundane",
            player_request="ordinary",
            delivery="item",
            resolution="attack" if body.kind == "weapon_attack" else "automatic",
            intensity="normal",
            targets=targets,
            effects=[op],
        )
        action = await compile_exploration(
            ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=mid, source_text=text, evidence="")
        )
    else:
        saved = await session.scalar(
            select(CombatExchange).where(
                CombatExchange.campaign_id == hero.campaign_id, CombatExchange.source_key == mid
            )
        )
        if saved is None:
            raise Conflict("Действие не было сохранено")
        action = ExplorationAction.model_validate(saved.proposal)
    results = await run_exchange(ctx, action, request_key=mid)
    if results[0].failure:
        raise Conflict(results[0].failure.message)
    source = await session.get(Message, mid)
    exchange = await session.scalar(
        select(CombatExchange).where(CombatExchange.campaign_id == hero.campaign_id, CombatExchange.source_key == mid)
    )
    changed = await scope_changes(ctx, [EffectChange.model_validate(change) for change in exchange.changes])
    scene = await universal_scene(session, viewer.campaign, viewer)
    messages = []
    if not source.turn_id:
        outcome = public_outcome(results[0], "Изменение снаряжения")
        outcome["enemy_reply"] = [public_outcome(result, "Ответ врага") for result in results[1:]]
        outcome["completion"] = [change.model_dump(mode="json") for change in changed if not change.private]
        turn = MasterTurn(
            campaign_id=hero.campaign_id,
            session_id=game.id,
            upto_seq=source.seq,
            status="done",
            finished_at=now(),
            trace=dict(universal=True, sources=[mid], audience=audience, scene=scene, outcomes={mid: outcome}),
        )
        session.add(turn)
        await session.flush()
        source.turn_id = turn.id
        messages.append(source)
        for source_id in (mid, enemy_source_key(mid)):
            card = await ensure_roll_message(session, hero.campaign_id, game.id, turn.id, source_id, audience)
            if card:
                messages.append(card)
        completion = await ensure_completion_message(session, hero.campaign_id, game.id, turn.id, mid, audience)
        if completion:
            messages.append(completion)
        text = " ".join(
            [
                *(result.description or "" for result in results),
                *(change.description for change in changed if not change.private),
            ]
        )
        narration = Message(
            campaign_id=hero.campaign_id,
            session_id=game.id,
            turn_id=turn.id,
            seq=await next_seq(session, hero.campaign_id),
            kind="narration",
            content=text,
            visible_to=audience,
            data=dict(
                universal=True, scope="party", location_ref=location_reference(scene), location_id=hero.location_id
            ),
        )
        session.add(narration)
        await session.flush()
        turn.narration_message_id = narration.id
        messages.append(narration)
    await session.commit()
    await session.refresh(hero)
    return await exploration_game_card(session, hero), messages
