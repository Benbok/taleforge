"""Freeform Universal admission, atomic receipts and restartable narration."""

from __future__ import annotations

import json
import logging
from time import monotonic

from sqlalchemy import func, select

from app.agents.llm import decide_model_for, model_for
from app.agents.master.action_admission import obtain_prepared_action
from app.agents.master.action_results import mark_source, narration_parts, prepared_outcome, public_outcome
from app.agents.master.helpers import _batches
from app.agents.master.universal_mood import mood_note
from app.agents.master.universal_narration import SYSTEM as NARRATION_SYSTEM
from app.agents.master.universal_narration import recent_history
from app.core.campaigns import Viewer, master_seat
from app.core.chat import active_session, next_seq
from app.core.universal.action_intents import LegacyAdmission
from app.core.universal.profiles import load_actor
from app.core.universal.references import link_scene_text, location_reference
from app.core.universal.resolution import ResolutionContext, resolve_action
from app.core.universal.rolls import ensure_completion_message, ensure_roll_message
from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    Character,
    HeroAbility,
    LlmCall,
    MasterTurn,
    Message,
    User,
    now,
)
from app.gateway.events import publish_message
from app.rules.universal.failures import ActionModelError, action_failure

Admission = LegacyAdmission


log = logging.getLogger(__name__)

STRUCTURED_MAX_TOKENS = 16384
NARRATION_MAX_TOKENS = 8192


def provider_schema(model) -> dict:
    """Tool schema for the provider. Gemini answers 400 to array length limits on larger closed schemas,
    so they are left out here; the server still enforces every limit when it validates the reply."""

    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if k not in {"minItems", "maxItems"}}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node

    return strip(model.model_json_schema())


def world_rules(secret):
    """What the world says about itself, for deciding what is possible. Never the private notes."""
    studio = ((secret.setting or {}).get("studio") or {}) if secret else {}
    return {key: str(studio.get(key) or "") for key in ("laws", "powers", "world")}


async def _call(service, campaign, turn, purpose, payload):
    async with service.maker() as s:
        spent = await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == campaign.id)) or 0
        limit = (campaign.settings or {}).get("spend_limit_usd")
        if limit is not None and spent >= float(limit):
            raise ValueError("Model spending limit exhausted")
        cfg = (
            await s.get(AgentConfig, master_seat(campaign).agent_config_id)
            if master_seat(campaign).agent_config_id
            else None
        )
        api_base = (cfg.settings or {}).get("api_base") if cfg else None
        if cfg is None or cfg.provider == "env" or cfg.model == "env":
            model = (
                decide_model_for()
                if purpose
                in {
                    "decide",
                    "exploration_decide",
                    "intent_review",
                    "narration_review",
                    "world_prepare",
                    "world_review",
                }
                else model_for()
            )
        else:
            model = model_for(cfg.provider, cfg.model)
        temperature = 0.2 if purpose == "decide" else cfg.temperature if cfg else 0.8
    options = {"max_tokens": NARRATION_MAX_TOKENS}  # reasoning shares this budget with the text
    if purpose in {
        "decide",
        "exploration_decide",
        "intent_review",
        "narration_review",
        "world_prepare",
        "world_review",
    }:
        from app.agents.master.exploration import NarrationReview
        from app.core.universal.action_intents import ActionIntent
        from app.rules.universal.exploration import IntentReview, IntentV2
        from app.rules.universal.world import WorldScenePlan, WorldSceneReview

        schema = {
            "decide": ActionIntent,
            "exploration_decide": IntentV2,
            "intent_review": IntentReview,
            "narration_review": NarrationReview,
            "world_prepare": WorldScenePlan,
            "world_review": WorldSceneReview,
        }[purpose]

        options = dict(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "submit_action",
                        "description": "Semantic intent for server validation",
                        "parameters": provider_schema(schema),
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "submit_action"}},
            # A thinking model spends this budget on reasoning first; a cut-off tool call is no answer at all.
            max_tokens=STRUCTURED_MAX_TOKENS,
        )
    started = monotonic()
    try:
        reply = await service.llm.complete(payload, model=model, api_base=api_base, temperature=temperature, **options)
    except Exception as exc:
        async with service.maker() as s:
            s.add(
                LlmCall(
                    campaign_id=campaign.id,
                    turn_id=turn,
                    purpose=purpose,
                    model=model,
                    latency_ms=int((monotonic() - started) * 1000),
                    error=type(exc).__name__,
                )
            )
            await s.commit()
        raise ActionModelError() from exc
    async with service.maker() as s:
        s.add(
            LlmCall(
                campaign_id=campaign.id,
                turn_id=turn,
                purpose=purpose,
                model=reply.model or model,
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                cost=reply.cost,
                latency_ms=int((monotonic() - started) * 1000),
            )
        )
        await s.commit()
    action_call = (
        next((call for call in reply.tool_calls if call.name == "submit_action"), None) if "tools" in options else None
    )
    if action_call is not None and not reply.blocked:
        return json.dumps(action_call.arguments, ensure_ascii=False)
    if reply.blocked or not reply.text.strip():
        raise ValueError("Model returned no usable text")
    return reply.text


async def run_universal_turn(service, cid, place=None):
    async with service.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None or master_seat(c).occupant_type != "agent":
            return None
        game = await active_session(s, cid)
        if game is None:
            return None
        # Failed/incomplete Universal work retains the original source IDs and admission.
        turns = list(
            await s.scalars(
                select(MasterTurn)
                .where(MasterTurn.campaign_id == cid, MasterTurn.session_id == game.id, MasterTurn.status != "done")
                .order_by(MasterTurn.started_at)
            )
        )
        turn = next(
            (
                t
                for t in turns
                if (t.trace or {}).get("universal")
                and (t.status == "running" or (t.trace or {}).get("recovery_attempts", 0) < 2)
            ),
            None,
        )
        if turn is None:
            batches, groups = await _batches(s, c)
            if not batches:
                return None
            if place not in batches:
                place = min(batches, key=lambda p: batches[p][0].seq)
            rows = [m for m in batches[place] if m.visible_to is None and m.session_id == game.id]
            if not rows:
                return None
            audience = None if place is None else [h.seat_id for h in groups.get(place, []) if h.seat_id]
            turn = MasterTurn(
                campaign_id=cid,
                session_id=game.id,
                upto_seq=rows[-1].seq,
                trace={
                    "universal": True,
                    "sources": [m.id for m in rows],
                    "audience": audience,
                    "admissions": {},
                    "outcomes": {},
                    "scene": {},
                },
            )
            s.add(turn)
            await s.flush()
            for m in rows:
                m.turn_id = turn.id
        turn.status = "running"
        await s.commit()
        tid, trace = turn.id, dict(turn.trace)
    ids = trace["sources"]
    if trace.get("audience") is not None:
        service._audience[cid] = trace["audience"]
    await service._states(cid, ids, "processing")
    try:
        await service._status(cid, "listening")
        for mid in ids:
            if mid in trace["outcomes"]:
                from app.core.universal.combat import enemy_source_key

                async with service.maker() as s:
                    card = await ensure_roll_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    enemy_card = await ensure_roll_message(
                        s, cid, game.id, tid, enemy_source_key(mid), trace.get("audience")
                    )
                    completion_card = await ensure_completion_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    await s.commit()
                if card:
                    await publish_message(service.bus, card)
                if enemy_card:
                    await publish_message(service.bus, enemy_card)
                if completion_card:
                    await publish_message(service.bus, completion_card)
                continue
            async with service.maker() as s:
                msg = await s.get(Message, mid)
                hero = await s.scalar(
                    select(Character).where(
                        Character.campaign_id == cid,
                        Character.seat_id == msg.seat_id,
                        Character.status.in_(["active", "approved"]),
                    )
                )
                if hero is None:
                    raise ValueError("Source seat has no admitted hero")
                seat = next(x for x in c.seats if x.id == msg.seat_id)
                if msg.author_user_id and msg.author_user_id not in {seat.user_id, seat.stand_in_user_id}:
                    raise ValueError("Source author does not control hero")
                sh, resources = await load_actor(s, cid, hero.id)
                secret = await s.get(CampaignSecret, cid)
                from app.core.universal.inventory import ensure_inventory, item_view, owned_items
                from app.core.universal.scene import universal_scene

                await ensure_inventory(s, cid, hero.id)
                inventory = [item_view(row) for row in await owned_items(s, cid, hero.id)]
                await s.commit()
                user = await s.get(User, seat.user_id)
                public_scene = await universal_scene(s, c, Viewer(user, c, seat))
                from app.core.map import party_map

                known_exits = (await party_map(s, Viewer(user, c, seat)))["exits"]
                known = list(await s.scalars(select(HeroAbility).where(HeroAbility.character_id == hero.id)))
                history = await recent_history(s, c, msg.seq - 1, trace.get("audience"), public_scene)
                from app.core.universal.objects import visible_objects
                from app.core.universal.perception import actor_constraints, established_evidence
                from app.db.models import Event

                evidence = await established_evidence(s, cid, hero.id)
                objects = await visible_objects(s, cid, hero.id)
                constraints = await actor_constraints(s, cid, hero.id)
                from app.core.universal.effects import active_effects

                running = [
                    dict(
                        id=e["id"],
                        kind=e["kind"],
                        label=e["definition"].get("label") or e["kind"],
                        description=e["definition"].get("appearance") or "",
                        remaining_seconds=e["remaining_seconds"],
                    )
                    for e in await active_effects(s, cid, hero.id)
                ]
                receipt = await s.scalar(select(Event).where(Event.campaign_id == cid, Event.idempotency_key == mid))
                old_receipt = receipt is not None and receipt.payload.get("schema_version") != 2
                allowed_targets = {e["id"] for e in public_scene.get("entities", [])}
                allowed_targets.add(hero.id)
                visible_heroes = await s.scalars(
                    select(Character).where(
                        Character.campaign_id == cid,
                        Character.location_id == hero.location_id,
                        Character.seat_id.is_not(None),
                        Character.status.in_(["active", "approved"]),
                    )
                )
                allowed_targets.update(h.id for h in visible_heroes)
                context = dict(
                    world=(secret.setting or {}).get("studio", {}) if secret else {},
                    # The text of the world decides what is allowed; the private notes stay with the master.
                    world_rules=world_rules(secret),
                    hero=sh.model_dump(mode="json"),
                    resources=resources.model_dump(mode="json"),
                    scene=public_scene,
                    history=history,
                    source=msg.content,
                    established_evidence=evidence,
                    objects=objects,
                    inventory=inventory,
                    known_exits=known_exits,
                    constraints=constraints,
                    active_effects=running,
                    known_abilities=[
                        dict(name=a.name, profile_id=a.profile_ref, revision=a.profile_revision, profile=a.definition)
                        for a in known
                    ],
                )
            context["actor_id"] = hero.id
            context["allowed_target_ids"] = sorted(allowed_targets)
            scope = dict(
                user_id=msg.author_user_id or seat.user_id,
                seat_id=seat.id,
                actor_id=hero.id,
                allowed_target_ids=frozenset(allowed_targets),
            )

            async def ask(payload):
                return await _call(service, c, tid, "decide", payload)

            old_prepared = trace.get("prepared", {}).get(mid)
            old_admission = trace.get("admissions", {}).get(mid)
            legacy = mid not in trace.get("exploration_bindings", {}) and (
                old_receipt
                or (old_prepared is not None and old_prepared.get("version") == 1)
                or (old_admission is not None and old_admission.get("schema_version") != 2)
            )
            if legacy:
                compiled = await obtain_prepared_action(service, c, tid, mid, trace, context, scope, ask)
            else:
                from app.agents.master.exploration import obtain_exploration_action

                async def ask_v2(purpose, payload):
                    return await _call(service, c, tid, purpose, payload)

                compiled = await obtain_exploration_action(service, c, tid, mid, trace, context, scope, ask_v2)
            trace["scene"] = public_scene
            outcome = prepared_outcome(compiled)
            if compiled.proposal is not None:
                async with service.maker() as s:
                    await service._status(cid, "rolling")
                    enemy_card = None
                    if getattr(compiled, "schema_version", None) == 2:
                        from app.core.universal.combat import enemy_source_key, run_exchange

                        ctx = ResolutionContext(s, cid, **scope, dice=service.dice_factory())
                        results = await run_exchange(ctx, compiled.proposal, request_key=mid)
                        result = results[0]
                    else:
                        results = []
                        result = await resolve_action(
                            ResolutionContext(s, cid, **scope, dice=service.dice_factory()), compiled.proposal, mid
                        )
                    outcome = public_outcome(result, compiled.public_reason)
                    trace["scene"] = await universal_scene(s, c, Viewer(user, c, seat))
                    if results:
                        from app.core.universal.effects import scope_changes
                        from app.db.models import CombatExchange
                        from app.rules.universal.exploration import EffectChange

                        exchange = await s.scalar(
                            select(CombatExchange).where(
                                CombatExchange.campaign_id == cid, CombatExchange.source_key == mid
                            )
                        )
                        outcome["enemy_reply"] = [public_outcome(reply, "Ответ врага") for reply in results[1:]]
                        changes = await scope_changes(
                            ctx, [EffectChange.model_validate(change) for change in exchange.changes]
                        )
                        outcome["completion"] = [
                            change.model_dump(mode="json") for change in changes if not change.private
                        ]
                        enemy_card = await ensure_roll_message(
                            s, cid, game.id, tid, enemy_source_key(mid), trace.get("audience")
                        )
                    card = await ensure_roll_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    completion_card = await ensure_completion_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    await s.commit()
                if card:
                    await publish_message(service.bus, card)
                if enemy_card:
                    await publish_message(service.bus, enemy_card)
                if completion_card:
                    await publish_message(service.bus, completion_card)
            trace["outcomes"][mid] = outcome
            async with service.maker() as s:
                t = await s.get(MasterTurn, tid)
                t.trace = dict(trace)
                source = await s.get(Message, mid)
                mark_source(source, outcome)
                await s.commit()
        # Checkpoint the same recipient-safe view before any text model call.
        # A resumed narration never rebuilds memory from a later world state.
        story, notices = narration_parts(trace["outcomes"])
        async with service.maker() as s:
            saved_turn = await s.get(MasterTurn, tid)
            saved_narration = (
                await s.get(Message, saved_turn.narration_message_id) if saved_turn.narration_message_id else None
            )
            if "public_context" not in trace:
                from app.agents.master.public_context import public_context

                trace["public_context"] = await public_context(
                    s, c, saved_turn.upto_seq, trace.get("audience"), trace.get("scene", {}), story
                )
                saved_turn.trace = dict(trace)
                await s.commit()
        public = trace["public_context"]
        story, scene, history = public["outcomes"], public["scene"], public["recent_history"]
        await service._status(cid, "describing")
        tone = await mood_note(service, c, tid, trace) if story and not saved_narration else ""
        if saved_narration:
            text = saved_narration.content
        elif not story:
            text = "\n\n".join(notices)
        else:
            if any(o.get("schema_version") == 2 for o in story.values()):
                from app.agents.master.exploration import reviewed_narration

                async def ask_narration(purpose, payload):
                    return await _call(service, c, tid, purpose, payload)

                text = await reviewed_narration(
                    service, c, tid, trace, story, scene, history, ask_narration, tone, context=public
                )
            else:
                text = await _call(
                    service,
                    c,
                    tid,
                    "narrate",
                    [
                        {
                            "role": "system",
                            "content": NARRATION_SYSTEM + ("\n\n" + tone if tone else ""),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(
                                public,
                                ensure_ascii=False,
                            ),
                        },
                    ],
                )
            if notices:
                text += "\n\n" + "\n\n".join(notices)
        async with service.maker() as s:
            t = await s.get(MasterTurn, tid)
            if not t.narration_message_id:
                m = Message(
                    campaign_id=cid,
                    session_id=game.id,
                    turn_id=tid,
                    kind="narration",
                    content=link_scene_text(text, scene),
                    seq=await next_seq(s, cid),
                    visible_to=trace.get("audience"),
                    data={
                        "universal": True,
                        "location_ref": location_reference(scene),
                        "scope": "party" if trace.get("audience") is not None else "public",
                        "location_id": (scene.get("location") or {}).get("id"),
                    },
                )
                s.add(m)
                await s.flush()
                t.narration_message_id = m.id
            else:
                m = await s.get(Message, t.narration_message_id)
            t.status, t.finished_at = "done", now()
            for mid in ids:
                source = await s.get(Message, mid)
                if source is not None:
                    mark_source(source, trace["outcomes"][mid])
            await s.commit()
        from app.agents import voiceover, voicing

        channel = service._tts_for(c, voicing.TEXT)
        if channel and not (m.data or {}).get("voice"):
            try:
                audio = await service.tts.voice_for_narration(
                    service.media_dir, cid, m.content, provider=channel.provider, voice_name=channel.voice
                )
                async with service.maker() as s:
                    voiced = await s.get(Message, m.id)
                    if audio:
                        # The chat's player reads voices/voice/voice_parts, as the old master wrote them.
                        voiced.data = {**voiced.data, **voiceover.data_of([audio], 1)}
                    await s.commit()
                    m = voiced
            except Exception:
                log.exception("master text voice failed")  # optional: never replays saved actions
        await publish_message(service.bus, m)
        from app.core.universal.publication import publish_game_state

        async with service.maker() as s:
            await publish_game_state(s, service.bus, await s.get(Campaign, cid))
        async with service.maker() as s:
            for mid in ids:
                source = await s.get(Message, mid)
                if source is not None:
                    await publish_message(service.bus, source, state="answered")
        await service._states(cid, ids, "answered")
        return tid
    except Exception as exc:
        async with service.maker() as s:
            t = await s.get(MasterTurn, tid)
            t.status = "failed"
            t.trace = {**trace, "error": str(exc)[:500]}
            failed_sources = []
            for mid in ids:
                source = await s.get(Message, mid)
                if source is None:
                    continue
                outcome = trace["outcomes"].get(mid)
                if outcome and outcome.get("failure"):
                    mark_source(source, outcome)
                else:
                    failure = (
                        action_failure("narration_unavailable")
                        if outcome
                        else getattr(exc, "failure", action_failure("internal_error"))
                    )
                    mark_source(source, {"failure": failure.model_dump()})
                failed_sources.append(source)
            await s.commit()
        for source in failed_sources:
            await publish_message(service.bus, source, state="failed")
        await service._states(cid, ids, "failed")
        return tid
    finally:
        await service._status(cid, "idle")
