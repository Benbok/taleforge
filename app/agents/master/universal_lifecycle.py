"""Universal session framing and private questions without a legacy catalog."""

import json

from app.core.campaigns import Viewer, master_seat
from app.core.chat import next_seq
from app.core.universal.places import public_location_name
from app.core.universal.references import link_scene_text, location_reference
from app.core.universal.scene import universal_scene
from app.db.models import Campaign, Entity, Message, User
from app.gateway.events import publish_message


async def open_universal_session(service, cid, session_id):
    async with service.intro_lock(cid):
        async with service.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or c.ruleset_id != "universal":
                return False
            if (c.settings or {}).get("universal_intro_message_id"):
                return True
            entry = await s.get(Entity, (c.settings or {}).get("studio_entry_location_id", ""))
            text = "\n\n".join(x for x in (c.public_intro, entry.description if entry else "") if x)
            if not text:
                return True
            framing = {"location": {"id": entry.id, "name": public_location_name(c, entry)}} if entry else {}
            msg = Message(
                campaign_id=cid,
                session_id=session_id,
                kind="narration",
                seat_id=master_seat(c).id,
                seq=await next_seq(s, cid),
                content=link_scene_text(text, framing),
                data={"universal": True, "intro": True, "location_ref": location_reference(framing)},
            )
            s.add(msg)
            await s.flush()
            c.settings = {**(c.settings or {}), "universal_intro_message_id": msg.id}
            await s.commit()
        await publish_message(service.bus, msg)
        return True


async def answer_universal_whisper(service, cid, mid):
    from app.agents.master.universal import _call

    async with service.maker() as s:
        c = await s.get(Campaign, cid)
        if c is None or c.ruleset_id != "universal":
            return False, None
        source = await s.get(Message, mid)
        if source is None:
            return True, None
        seat = next((seat for seat in c.seats if seat.id == source.seat_id), None)
        if seat is None or not seat.user_id:
            return True, None
        user = await s.get(User, seat.user_id)
        scene = await universal_scene(s, c, Viewer(user, c, seat))
        question = source.content
    error = False
    try:
        text = await _call(
            service,
            c,
            None,
            "whisper",
            [
                {
                    "role": "system",
                    "content": (
                        "Ответь игроку на вопрос только по открытым фактам сцены. "
                        "Не меняй мир, ресурсы или результаты проверок. Для игрового действия попроси "
                        "написать намерение в общий чат. Не выдумывай скрытые факты."
                    ),
                },
                {"role": "user", "content": json.dumps({"scene": scene, "question": question}, ensure_ascii=False)},
            ],
        )
    except Exception:
        text, error = "Мастер не смог ответить. Попробуйте спросить ещё раз.", True
    async with service.maker() as s:
        source = await s.get(Message, mid)
        if source is None:
            return True, None
        source.data = {**(source.data or {}), "answer": "failed" if error else "answered"}
        msg = Message(
            campaign_id=cid,
            session_id=source.session_id,
            kind="narration",
            seat_id=master_seat(c).id,
            visible_to=[seat.id, master_seat(c).id],
            seq=await next_seq(s, cid),
            content=link_scene_text(text, scene),
            data={"whisper_reply": mid, "location_ref": location_reference(scene)},
        )
        s.add(msg)
        await s.commit()
    await publish_message(service.bus, msg)
    await service._states(cid, [mid], "failed" if error else "answered")
    return True, None if error else msg.id
