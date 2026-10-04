"""Ритм сессии и эпилог (проект «Подготовка кампании», раздел 7.5–7.6).

На старте сессии ИИ-мастер с каркасом ставит цель на вечер, на паузе оставляет зацепку на следующую сессию,
а когда кампания завершена — пишет эпилог: хронику и судьбу каждого героя. В ваншоте мастер следит за числом
ходов и ведёт к финалу (подсказка в системной инструкции, см. ``pacing_note``). Если отряд несколько ходов подряд
буксует на одном препятствии, мастер получает подсказку подбросить миру новую возможность (``stall_note``).
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select

from app.agents import memory
from app.agents.prelude import _ai_plan, _call_tool, _hero, _spec
from app.core import plot
from app.core.campaigns import master_seat
from app.core.chat import next_seq
from app.core.linker import link_text
from app.db.models import Campaign, Character, GameSession, MasterTurn, Message
from app.gateway.events import envelope, publish_message

log = logging.getLogger(__name__)

GOAL_TOOL = "submit_session_goal"
NEXT_TOOL = "submit_session_hook"
EPILOGUE_TOOL = "submit_epilogue"
ONESHOT_TURNS = 30  # ходов мастера на ваншот: после 70% мастер сводит историю к финалу
STALL_TURNS = 3  # ходов подряд без продвижения: мастер подбрасывает отряду новую возможность
# Вызовы, после которых история сдвинулась: новое место, находка, новый участник, событие мира, шаг сюжета
PROGRESS_TOOLS = {
    "move",
    "enter_room",
    "make_current",
    "create_location",
    "link_locations",
    "spawn_entity",
    "give_item",
    "place_item",
    "pick_up_item",
    "keep_found_item",
    "learn_fact",
    "set_scene_mode",
    "roll_fortune",
    "resolve_response",
    "advance_plot",
    "develop",
    "plot_reveal",
    "end_act",
    "award_xp",
}


def pacing_note(length: str | None, turns: int, limit: int = ONESHOT_TURNS) -> str:
    """Подсказка о темпе для ваншота. В кампаниях подлиннее темп задают акты."""
    if length != "oneshot":
        return ""
    if turns >= limit:
        return f"Ваншот: сыграно {turns} ходов из примерно {limit}. Время вышло: веди к развязке и финалу сейчас."
    if turns >= int(limit * 0.7):
        return f"Ваншот: сыграно {turns} ходов из примерно {limit}. Пора сводить нити к финалу."
    return f"Ваншот: вся история — за одну сессию, примерно {limit} ходов; сыграно {turns}."


def _stalled(trace: dict) -> bool | None:
    """Буксовал ли отряд в этом ходе: попытки не удались и ничего не сдвинулось. None — ход боя, он не в счёт."""
    if trace.get("combat"):
        return None
    failed = moved = False
    for call in trace.get("calls") or []:
        r = call.get("result") or {}
        if not r.get("ok"):
            continue
        tool = call.get("tool")
        if tool == "cancel_action" and not call.get("auto"):
            failed = True
        elif tool == "roll_check":
            if (r.get("result") or {}).get("success"):
                moved = True
            else:
                failed = True
        elif tool in PROGRESS_TOOLS:
            moved = True
    return failed and not moved


async def stalled_turns(s, cid: str, session_id: str | None) -> int:
    """Сколько последних ходов сессии подряд отряд буксует: попытки проваливаются, а мир не меняется."""
    q = (
        select(MasterTurn.trace)
        .where(MasterTurn.campaign_id == cid, MasterTurn.session_id == session_id, MasterTurn.status == "done")
        .order_by(MasterTurn.finished_at.desc())
        .limit(10)
    )
    n = 0
    for trace in await s.scalars(q):
        stuck = _stalled(trace or {})
        if stuck is None or not stuck:
            break
        n += 1
    return n


def stall_note(turns: int, limit: int = STALL_TURNS) -> str:
    """Подсказка фазе решения, когда отряд застрял. Не решение за игроков, а новый инструмент в мире."""
    if turns < limit:
        return ""
    return (
        f"Отряд буксует уже {turns} хода подряд: попытки не удаются, а в мире ничего не меняется. Не отвечай ещё "
        "одним «не вышло». Если новые реплики снова упираются в то же препятствие, дай миру сдвинуться: событие "
        "(roll_fortune), проходящий NPC, которого заинтересовала возня героев (spawn_entity), находка (place_item), "
        "звук, обвал, смена караула, слух (learn_fact). Это не подсказка с готовым решением и не отмена уже "
        "установленных фактов, а новая возможность, которой игроки могут воспользоваться по-своему.\n\n"
    )


async def turns_played(s, cid: str) -> int:
    q = select(func.count()).select_from(MasterTurn).where(MasterTurn.campaign_id == cid, MasterTurn.status == "done")
    return int(await s.scalar(q) or 0)


async def _context(s, c: Campaign, p: dict) -> str:
    last = await memory.latest(s, c.id)
    recap = (last.content or {}).get("recap") if last else ""
    parts = [plot.now_block(p)]
    if recap:
        parts.append(f"Что было (пересказ для игроков): {recap}")
    return "\n\n".join(parts)


async def _post(svc, cid: str, text: str, session_id: str | None) -> str:
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        msg = Message(
            campaign_id=cid,
            session_id=session_id,
            seq=await next_seq(s, cid),
            seat_id=master_seat(c).id,
            kind="narration",
            content=await link_text(s, cid, text),
        )
        s.add(msg)
        await s.commit()
    await publish_message(svc.bus, msg)
    return msg.id


def _system(p: dict, persona: str | None) -> dict:
    return {
        "role": "system",
        "content": f"Ты — мастер ролевой игры «{p.get('title')}» по D&D 5e на русском языке. {persona or ''}",
    }


def _one_line(field: str, limit: int):
    def check(args: dict) -> tuple[str | None, list[str]]:
        text = str(args.get(field) or "").strip()
        return text[:limit], [] if text else [f"нужно поле {field}"]

    return check


async def session_goal(svc, cid: str, session_id: str) -> str | None:
    """Цель на вечер: что отряд может успеть за эту сессию, в словах героев и без тайн каркаса."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        cfg, p = await _ai_plan(s, c) if c else (None, {})
        if cfg is None:
            return None
        ctx = await _context(s, c, p)
        persona = cfg.persona
    msgs = [
        _system(p, persona),
        {
            "role": "user",
            "content": f"{ctx}\n\nНачинается сессия. Поставь отряду цель на этот вечер: одна-две фразы, которые видят "
            "игроки. Это то, что герои уже знают и хотят сделать, а не тайна каркаса. Цель должна быть достижима "
            "за вечер и вести к ближайшему открытому узлу.",
        },
    ]
    spec = _spec(GOAL_TOOL, "Сдать цель на вечер.", {"goal": {"type": "string", "maxLength": 300}}, ["goal"])
    goal = await _call_tool(svc, c, cfg, "session_goal", msgs, spec, _one_line("goal", 300))
    if not goal:
        return None
    return await _post(svc, cid, f"Цель на этот вечер: {goal}", session_id)


async def session_hook(svc, cid: str, session_id: str | None) -> str | None:
    """Зацепка на следующую сессию: чем закончился вечер и что ждёт героев дальше."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        cfg, p = await _ai_plan(s, c) if c else (None, {})
        if cfg is None:
            return None
        ctx = await _context(s, c, p)
        rows = (
            await s.scalars(
                select(Message)
                .where(Message.campaign_id == cid, Message.session_id == session_id, Message.kind == "narration")
                .order_by(Message.seq.desc())
                .limit(3)
            )
        ).all()
        last = "\n".join(m.content for m in reversed(rows) if not m.visible_to)
        persona = cfg.persona
    msgs = [
        _system(p, persona),
        {
            "role": "user",
            "content": f"{ctx}\n\nПоследние сцены вечера:\n{last or 'нет'}\n\nСессия окончена. Оставь игрокам зацепку "
            "на следующий раз: одна-две фразы, интрига без раскрытия тайн. Не решай за героев.",
        },
    ]
    spec = _spec(
        NEXT_TOOL, "Сдать зацепку на следующую сессию.", {"hook": {"type": "string", "maxLength": 400}}, ["hook"]
    )
    hook = await _call_tool(svc, c, cfg, "session_hook", msgs, spec, _one_line("hook", 400))
    if not hook:
        return None
    return await _post(svc, cid, f"В следующий раз: {hook}", session_id)


async def epilogue(svc, cid: str) -> dict | None:
    """Эпилог кампании: хроника для всех и судьба каждого героя. Мир и герои остаются — кампанию можно
    продолжить новой. Эпилог хранится в ``settings.epilogue``."""
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        cfg, p = await _ai_plan(s, c) if c else (None, {})
        if cfg is None or (c.settings or {}).get("epilogue"):
            return None
        ctx = await _context(s, c, p)
        heroes = (
            await s.scalars(
                select(Character).where(
                    Character.campaign_id == cid, Character.status.in_(("approved", "active", "dead"))
                )
            )
        ).all()
        roster = "\n\n".join([await _hero(s, c, ch, private=False) + f" Статус: {ch.status}." for ch in heroes])
        ids = {ch.id: ch.name for ch in heroes}
        persona = cfg.persona
        game = await s.scalar(
            select(GameSession).where(GameSession.campaign_id == cid).order_by(GameSession.started_at.desc()).limit(1)
        )
        session_id = game.id if game else None
    msgs = [
        _system(p, persona),
        {
            "role": "user",
            "content": f"{plot.render(p)}\n\n{ctx}\n\nГерои:\n{roster}\n\nКампания завершена. Напиши эпилог: "
            "хронику кампании для всех (1–3 абзаца: что герои сделали и к какому финалу пришёл мир; теперь можно "
            "раскрыть тайны, до которых они дошли) и судьбу каждого героя (2–3 фразы, по его поступкам).",
        },
    ]

    def check(args: dict) -> tuple[dict | None, list[str]]:
        chronicle = str(args.get("chronicle") or "").strip()
        fates = [f for f in args.get("fates") or [] if isinstance(f, dict)]
        errs = [] if chronicle else ["нужна хроника"]
        got = {str(f.get("character_id")): str(f.get("text") or "").strip() for f in fates}
        missing = [n for i, n in ids.items() if not got.get(i)]
        if missing:
            errs.append("нет судьбы героев: " + ", ".join(missing))
        return {"chronicle": chronicle[:4000], "fates": {i: got[i][:800] for i in ids if got.get(i)}}, errs

    spec = _spec(
        EPILOGUE_TOOL,
        "Сдать эпилог кампании.",
        {
            "chronicle": {"type": "string", "maxLength": 4000},
            "fates": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "character_id": {"type": "string", "enum": list(ids)},
                        "text": {"type": "string", "maxLength": 800},
                    },
                    "required": ["character_id", "text"],
                },
            },
        },
        ["chronicle", "fates"],
    )
    result = await _call_tool(svc, c, cfg, "epilogue", msgs, spec, check)
    if result is None:
        return None
    fates = "\n\n".join(f"[[{i}|{ids[i]}]]: {t}" for i, t in result["fates"].items())
    await _post(svc, cid, "Эпилог. " + result["chronicle"], session_id)
    if fates:
        await _post(svc, cid, "Судьбы героев.\n\n" + fates, session_id)
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "epilogue": result}
        await s.commit()
    await svc.bus.publish(cid, envelope("campaign.epilogue", cid, result), None)
    return result
