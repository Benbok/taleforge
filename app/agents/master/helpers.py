"""Реплики, история чата и тексты результатов хода для промптов мастера."""

from __future__ import annotations

import json

from sqlalchemy import select

from app.agents import intent as intents
from app.agents import textcalls
from app.agents.master.common import COMBAT_LENGTH, HISTORY, PLAYER_KINDS
from app.core import chat, combat
from app.db.models import Campaign, Character, Message, Scene, User
from app.tools import plot as plot_tools
from app.tools.audio import AUDIO_TOOLS
from app.tools.registry import ToolContext


async def _new_player_messages(s, c: Campaign) -> list[Message]:
    """Реплики игроков, которые ещё не взял ни один ход мастера (удачный, идущий или сорвавшийся: сорвавшийся ход
    просит игроков повторить действие, поэтому его реплики второй раз не берутся)."""
    players = {x.id for x in c.seats if x.role == "player"}
    q = select(Message).where(Message.campaign_id == c.id, Message.turn_id.is_(None), Message.kind.in_(PLAYER_KINDS))
    return [m for m in await s.scalars(q.order_by(Message.seq)) if m.seat_id in players]


async def _batches(s, c: Campaign) -> tuple[dict[str | None, list[Message]], dict]:
    """Невзятые реплики по группам отряда. Отряд вместе — один пакет под ключом None; разделился — по месту героя
    автора (игрок без героя — в группе места сцены)."""
    new = await _new_player_messages(s, c)
    groups = await chat.party(s, c)
    if not new:
        return {}, groups
    if len(groups) <= 1:
        return {None: new}, groups
    where = {h.seat_id: p for p, hs in groups.items() for h in hs if h.seat_id}
    sc = await s.get(Scene, c.id)
    home = sc.location_id if sc is not None and sc.location_id in groups else next(iter(groups))
    out: dict[str | None, list[Message]] = {}
    for m in new:
        out.setdefault(where.get(m.seat_id, home), []).append(m)
    return out, groups


def _in_fight(sc: Scene, heroes: list[Character]) -> bool:
    """Касается ли идущий бой этих героев: кто-то из них в очереди инициативы."""
    ids = {h.id for h in heroes}
    return any(x.get("id") in ids for x in sc.turn_order or [])


async def _turn_messages(s, c: Campaign, turn_id: str) -> list[Message]:
    players = {x.id for x in c.seats if x.role == "player"}
    q = select(Message).where(Message.campaign_id == c.id, Message.turn_id == turn_id, Message.kind.in_(PLAYER_KINDS))
    return [m for m in await s.scalars(q.order_by(Message.seq)) if m.seat_id in players]


async def _history(s, c: Campaign, before_seq: int, seats: set[str] | None = None) -> list[Message]:
    """Последние сообщения перед ходом. ``seats`` — места героев группы: другие части отряда её не слышат."""
    q = select(Message).where(
        Message.campaign_id == c.id, Message.seq < before_seq, Message.kind.notin_(("ooc", "roll"))
    )
    rows = (await s.scalars(q.order_by(Message.seq.desc()).limit(HISTORY * 3 if seats else HISTORY))).all()
    if seats:
        rows = [m for m in rows if m.visible_to is None or seats & set(m.visible_to)][:HISTORY]
    return list(reversed(rows))


def _heard_by(ctx: ToolContext, crew: set[str]) -> list[str] | None:
    """Кто видит ответ мастера: герои группы в начале хода и все, кто к концу хода стоит там же, где они.
    Так момент, когда отряд разделился, видят все, а встречу — обе стороны. None — все."""
    w = ctx.world
    groups = w.groups()
    ends = {w.place_of(w.characters[i]) for i in crew if i in w.characters}
    heroes = [h for p in ends for h in groups.get(p, [])] + [w.characters[i] for i in crew if i in w.characters]
    seats = chat.audience(ctx.campaign, heroes)
    every = {h.seat_id for hs in groups.values() for h in hs if h.seat_id}
    return None if every <= set(seats) else seats


async def _party_change(s, ctx: ToolContext, before: dict, crew: set[str], names) -> tuple[list[str], str]:
    """Отряд разделился или снова сошёлся за этот ход: строка для всех в чат и, при встрече, просьба мастеру
    коротко пересказать, что было с другой частью отряда (её реплики эта группа не видела)."""
    w = ctx.world
    after = w.groups()
    ends = {w.place_of(w.characters[i]) for i in crew if i in w.characters}
    met = [h for p in ends for h in after.get(p, []) if h.id not in crew]
    late = w.catch_up()  # сошлись части отряда с разным временем: отставшие догоняют
    notes: list[str] = []
    if len(before) <= 1 and len(after) > 1:
        notes.append("Отряд разделился: " + _where(w, after) + ".")
    elif len(before) > 1 and len(after) <= 1:
        notes.append("Отряд снова вместе.")
    elif len(before) > 1 and {frozenset(v) for v in before.values()} != {
        frozenset(h.id for h in hs) for hs in after.values()
    }:
        notes.append("Отряд: " + _where(w, after) + ".")
    clock = "".join(
        f"\nПока отряд был порознь, у {', '.join(names)} прошло на {span(sec)} меньше: часы догнали остальных, "
        "одной фразой скажи, чем они были заняты это время."
        for names, sec in late
    )
    if not met:
        return notes, clock.strip()
    seats = {h.seat_id for h in met if h.seat_id}
    q = select(Message).where(Message.campaign_id == ctx.campaign.id, Message.kind == "narration")
    rows = (await s.scalars(q.order_by(Message.seq.desc()).limit(30))).all()
    theirs = [m.content for m in rows if m.visible_to and seats & set(m.visible_to) and (m.data or {}).get("place")]
    told = "\n".join(f"- {t[:600]}" for t in reversed(theirs[:3])) or "- (их ходов не было)"
    meet = (
        f"Встреча: к героям присоединились {', '.join(h.name for h in met)}. Пока отряд был порознь, игроки не "
        "видели ответов друг друга. Одной-двумя фразами, без новых фактов, передай, что было с пришедшими, — "
        f"по последним ответам им:\n{told}{clock}"
    )
    return notes, meet


def span(sec: int) -> str:
    """Отрезок игрового времени словами: «8 ч», «20 мин»."""
    if sec >= 3600:
        return f"{round(sec / 3600)} ч"
    if sec >= 60:
        return f"{round(sec / 60)} мин"
    return f"{sec} с"


def _where(w, groups: dict) -> str:
    return "; ".join(f"{', '.join(h.name for h in hs)} — {w._place_name(p)}" for p, hs in groups.items())


async def _names(s, c: Campaign) -> dict[str, str]:
    ids = [x.user_id for x in c.seats if x.user_id] + [c.owner_id]
    rows = await s.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u.name for u in rows}


KIND_RU = {
    "action": "действие",
    "speech": "речь",
    "whisper": "шёпот мастеру",
    "narration": "мастер",
    "system": "система",
}


def _who(m: Message, char_by_seat: dict, names: dict) -> str:
    ch = char_by_seat.get(m.seat_id)
    player = names.get(m.author_user_id or "", "")
    if ch is not None:
        return f"{ch.name} ({ch.id}{', игрок ' + player if player else ''})"
    return player or "мастер"


def _render_history(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        if m.kind == "narration" and m.visible_to is not None:
            out.append(f"[мастер шёпотом, видит только адресат] {m.content}")
        elif m.kind == "narration":
            # старые ответы с вызовами, написанными текстом, модель стала бы повторять
            out.append(f"[мастер] {textcalls.clean(m.content)}")
        elif m.kind == "system":
            out.append(f"[система] {m.content}")
        else:
            out.append(f"[{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}: {m.content}")
    return "\n".join(out)


def _render_new(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        note = "" if m.seat_id in char_by_seat else " (у игрока ещё нет персонажа)"
        out.append(f"- [{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}{note}: {m.content}")
        if m.kind == "action" and m.intent:
            out.append(f"  намерение (разбор парсера): {intents.describe(m.intent)}")
    return "\n".join(out)


def _unsettled_fails(ctx: ToolContext, trace_calls: list[dict]) -> list[str]:
    """Герои с критическим провалом (натуральная 1 в проверке или атаке), чьё последствие не закреплено
    инструментом после броска."""
    from app.tools.master.checks import CONSEQUENCE_TOOLS

    open_: list[str] = []
    for t in trace_calls:
        res = t.get("result") or {}
        if not res.get("ok"):
            continue
        args, out = t.get("args") or {}, res.get("result") or {}
        if t["tool"] == "roll_check" and out.get("critical") == "fail":
            who = args.get("character_id")
        elif t["tool"] == "resolve_attack" and out.get("fumble"):
            who = args.get("attacker_id")
        else:
            who = None
            if t["tool"] in CONSEQUENCE_TOOLS:
                hit = {args.get(k) for k in ("target_id", "character_id", "actor_id")}
                open_ = [i for i in open_ if i not in hit]
        if who in ctx.world.characters and who not in open_:
            open_.append(who)
    return [i for i in open_ if ctx.world.actor(i).alive]


def _check_only(ctx: ToolContext, notes=()) -> bool:
    """Ход вне боя, в котором были только проверки: ответ — короткое литературное описание исхода."""
    tools = [ev.tool for ev in ctx.events if ev.tool not in AUDIO_TOOLS]
    return not notes and not ctx.world.in_fight() and bool(tools) and set(tools) == {"roll_check"}


def _narration_length(ctx: ToolContext, notes=()) -> str:
    if _check_only(ctx, notes):
        return "одно-два предложения"
    if notes or (combat.in_combat(ctx) and ctx.world.in_fight()):
        return COMBAT_LENGTH
    return (
        "один короткий абзац, два-четыре предложения; второй абзац — только если герои попали в новое место или "
        "случилось что-то важное для сюжета"
    )


def _render_results(ctx: ToolContext) -> str:
    out = []
    for ev in ctx.events:
        if ev.tool in AUDIO_TOOLS:
            continue
        res = ev.payload.get("result", ev.payload)
        if ev.tool in plot_tools.PLOT_TOOLS or ev.tool == "threat_clock":
            mark = " [СЮЖЕТ: только для мастера, прямо не называй]"
        else:
            mark = " [СКРЫТЫЙ БРОСОК: игрокам только последствия]" if ev.hidden else ""
        out.append(f"- {ev.tool}{mark}: {json.dumps(res, ensure_ascii=False, default=str)}")
    return "\n".join(out)
