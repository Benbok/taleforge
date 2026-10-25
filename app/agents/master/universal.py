"""Freeform Universal admission, atomic receipts and restartable narration."""

from __future__ import annotations

import json
from time import monotonic

from sqlalchemy import func, select

from app.agents.llm import decide_model_for, model_for
from app.agents.master.action_admission import obtain_prepared_action
from app.agents.master.action_results import mark_source, narration_parts, prepared_outcome, public_outcome
from app.agents.master.helpers import _batches
from app.agents.master.universal_narration import SYSTEM as NARRATION_SYSTEM
from app.agents.master.universal_narration import recent_history
from app.core.campaigns import Viewer, master_seat
from app.core.chat import active_session, next_seq
from app.core.universal.action_intents import LegacyAdmission
from app.core.universal.profiles import load_actor
from app.core.universal.references import link_scene_text, location_reference
from app.core.universal.resolution import ResolutionContext, resolve_action
from app.core.universal.rolls import ensure_roll_message
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
from app.gateway.events import envelope, publish_message
from app.rules.universal.failures import ActionModelError, action_failure

Admission = LegacyAdmission


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
            model = decide_model_for() if purpose == "decide" else model_for()
        else:
            model = model_for(cfg.provider, cfg.model)
        temperature = 0.2 if purpose == "decide" else cfg.temperature if cfg else 0.8
    options = {}
    if purpose == "decide":
        from app.core.universal.action_intents import ActionIntent

        options = dict(
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": "submit_action",
                        "description": "Semantic intent for server validation",
                        "parameters": ActionIntent.model_json_schema(),
                    },
                }
            ],
            tool_choice={"type": "function", "function": {"name": "submit_action"}},
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
        next((call for call in reply.tool_calls if call.name == "submit_action"), None) if purpose == "decide" else None
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
                async with service.maker() as s:
                    card = await ensure_roll_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    await s.commit()
                if card:
                    await publish_message(service.bus, card)
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
                from app.core.universal.scene import universal_scene

                user = await s.get(User, seat.user_id)
                public_scene = await universal_scene(s, c, Viewer(user, c, seat))
                known = list(await s.scalars(select(HeroAbility).where(HeroAbility.character_id == hero.id)))
                history = await recent_history(s, c, msg.seq - 1, trace.get("audience"), public_scene)
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
                    hero=sh.model_dump(mode="json"),
                    resources=resources.model_dump(mode="json"),
                    scene=public_scene,
                    history=history,
                    source=msg.content,
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

            compiled = await obtain_prepared_action(service, c, tid, mid, trace, context, scope, ask)
            trace["scene"] = public_scene
            outcome = prepared_outcome(compiled)
            if compiled.proposal is not None:
                async with service.maker() as s:
                    await service._status(cid, "rolling")
                    result = await resolve_action(
                        ResolutionContext(s, cid, **scope, dice=service.dice_factory()), compiled.proposal, mid
                    )
                    outcome = public_outcome(result, compiled.public_reason)
                    card = await ensure_roll_message(s, cid, game.id, tid, mid, trace.get("audience"))
                    await s.commit()
                if card:
                    await publish_message(service.bus, card)
            trace["outcomes"][mid] = outcome
            async with service.maker() as s:
                t = await s.get(MasterTurn, tid)
                t.trace = dict(trace)
                source = await s.get(Message, mid)
                mark_source(source, outcome)
                await s.commit()
        # Only public saved results enter narrator context, never admission/private studio.
        async with service.maker() as s:
            saved_turn = await s.get(MasterTurn, tid)
            saved_narration = (
                await s.get(Message, saved_turn.narration_message_id) if saved_turn.narration_message_id else None
            )
            history = await recent_history(s, c, saved_turn.upto_seq, trace.get("audience"), trace.get("scene", {}))
        await service._status(cid, "describing")
        story, notices = narration_parts(trace["outcomes"])
        if saved_narration:
            text = saved_narration.content
        elif not story:
            text = "\n\n".join(notices)
        else:
            text = await _call(
                service,
                c,
                tid,
                "narrate",
                [
                    {
                        "role": "system",
                        "content": NARRATION_SYSTEM,
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {"outcomes": story, "scene": trace.get("scene", {}), "recent_history": history},
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
                    content=link_scene_text(text, trace.get("scene", {})),
                    seq=await next_seq(s, cid),
                    visible_to=trace.get("audience"),
                    data={
                        "universal": True,
                        "location_ref": location_reference(trace.get("scene", {})),
                        "scope": "party" if trace.get("audience") is not None else "public",
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
        from app.agents import voicing

        channel = service._tts_for(c, voicing.TEXT)
        if channel and not (m.data or {}).get("audio"):
            try:
                audio = await service.tts.voice_for_narration(
                    service.media_dir, cid, m.content, provider=channel.provider, voice_name=channel.voice
                )
                async with service.maker() as s:
                    voiced = await s.get(Message, m.id)
                    voiced.data = {**voiced.data, "audio": audio}
                    await s.commit()
                    m = voiced
            except Exception:
                pass  # Optional voice failure never replays saved actions.
        await publish_message(service.bus, m)
        from app.core.characters import public_view
        from app.core.universal.scene import universal_scene
        from app.core.universal.state import game_card_of

        async with service.maker() as s:
            campaign = await s.get(Campaign, cid)
            heroes = list(
                await s.scalars(
                    select(Character).where(Character.campaign_id == cid, Character.status.in_(["active", "approved"]))
                )
            )
            for changed in heroes:
                await service.bus.publish(
                    cid, envelope("character.updated", cid, {"character": public_view(changed)}), None
                )
                if changed.seat_id:
                    await service.bus.publish(
                        cid, envelope("character.sheet", cid, {"character": game_card_of(changed)}), [changed.seat_id]
                    )
            for player in campaign.seats:
                if player.role != "player" or not player.user_id:
                    continue
                user = await s.get(User, player.user_id)
                snapshot = await universal_scene(s, campaign, Viewer(user, campaign, player))
                await service.bus.publish(cid, envelope("scene.updated", cid, snapshot), [player.id])
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
