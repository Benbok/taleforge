"""Recipient-scoped narration jobs, checkpointed independently after saved actions."""

import json

from app.agents.master.action_results import narration_parts
from app.agents.master.universal_mood import mood_note
from app.agents.master.universal_narration import SYSTEM as NARRATION_SYSTEM
from app.core.campaigns import Viewer
from app.core.chat import next_seq
from app.core.universal.references import link_scene_text, location_reference
from app.db.models import MasterTurn, Message, User
from app.gateway.events import publish_message


async def result_scene(session, campaign, source_id):
    from app.core.universal.scene import universal_scene

    source = await session.get(Message, source_id)
    seat = next(seat for seat in campaign.seats if seat.id == source.seat_id)
    return await universal_scene(session, campaign, Viewer(await session.get(User, seat.user_id), campaign, seat))


async def narration_jobs(service, campaign, tid, trace):
    if "narration_jobs" in trace:
        return trace["narration_jobs"]
    from app.agents.master.public_context import scene_audience

    async with service.maker() as session:
        turn = await session.get(MasterTurn, tid)
        if turn.narration_message_id:
            # A previously published legacy narration stays immutable.
            message = await session.get(Message, turn.narration_message_id)
            jobs = [
                dict(
                    sources=trace["sources"],
                    scene=trace.get("scene", {}),
                    audience=message.visible_to,
                    message_id=message.id,
                )
            ]
        else:
            by_place = {}
            for mid in trace["sources"]:
                scene = trace.get("result_scenes", {}).get(mid)
                if scene is None:
                    # Compatibility for unfinished multi-source turns created before scene checkpoints.
                    scene = await result_scene(session, campaign, mid)
                place = (scene.get("location") or {}).get("id")
                job = by_place.setdefault(place, dict(sources=[], scene=scene))
                job["sources"].append(mid)
                job["scene"] = scene
            jobs = list(by_place.values())
            for job in jobs:
                job["audience"] = await scene_audience(session, campaign.id, trace.get("audience"), job["scene"])
        if len(jobs) == 1 and "public_context" in trace:
            jobs[0]["public_context"] = trace["public_context"]
        trace["narration_jobs"] = jobs
        turn.trace = dict(trace)
        await session.commit()
    return jobs


async def describe_turn(service, c, game, tid, trace):
    from app.agents.master.universal import _call, log

    cid = c.id
    jobs = await narration_jobs(service, c, tid, trace)
    for index, job in enumerate(jobs):
        story, notices = narration_parts({mid: trace["outcomes"][mid] for mid in job["sources"]})
        async with service.maker() as s:
            saved_turn = await s.get(MasterTurn, tid)
            saved_narration = await s.get(Message, job["message_id"]) if job.get("message_id") else None
            if "public_context" not in job:
                from app.agents.master.public_context import public_context

                job["public_context"] = await public_context(
                    s, c, saved_turn.upto_seq, job["audience"], job["scene"], story
                )
                if index == 0:
                    trace["public_context"] = job["public_context"]
                    trace["narration_audience"] = job["audience"]
                saved_turn.trace = dict(trace)
                await s.commit()
        public = job["public_context"]
        narration_audience = job["audience"]
        if narration_audience is not None:
            service._audience[cid] = narration_audience
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
                    service,
                    c,
                    tid,
                    trace,
                    story,
                    scene,
                    history,
                    ask_narration,
                    tone,
                    context=public,
                    state_key="exploration_narration" if len(jobs) == 1 else f"exploration_narration_{index}",
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
            if not job.get("message_id"):
                m = Message(
                    campaign_id=cid,
                    session_id=game.id,
                    turn_id=tid,
                    kind="narration",
                    content=link_scene_text(text, scene),
                    seq=await next_seq(s, cid),
                    visible_to=narration_audience,
                    data={
                        "universal": True,
                        "location_ref": location_reference(scene),
                        "scope": "party" if narration_audience is not None else "public",
                        "location_id": (scene.get("location") or {}).get("id"),
                    },
                )
                s.add(m)
                await s.flush()
                job["message_id"] = m.id
                if not t.narration_message_id:
                    t.narration_message_id = m.id
            else:
                m = await s.get(Message, job["message_id"])
            t.trace = dict(trace)
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
