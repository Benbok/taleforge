"""Инструменты последствий: поступки героев, ответ мира и вдохновение (правила — ``app/core/standing.py``).

Мастер называет поступок и его вес, а сервер сам двигает отношение стороны, расходит круги по связанным фракциям,
назначает срок ответа и напоминает мастеру, когда ответ созрел. События скрыты от игроков: отношение они узнают
по тому, как с ними обходится мир.
"""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import standing as sd
from app.core.plot import DAY
from app.db.models import Entity
from app.tools.master import _character
from app.tools.registry import ToolContext, ToolError, tool

STANDING_TOOLS = ("record_deed", "expose_deed", "resolve_response", "get_standing", "grant_inspiration")


def _book(ctx: ToolContext) -> dict:
    return sd.book(ctx.world.scene.state)


def _save(ctx: ToolContext, b: dict) -> dict:
    """Пишет раздел отношений в сцену и возвращает обратную дельту."""
    sc = ctx.world.scene
    inverse = {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)}
    sc.state = {**(sc.state or {}), "standing": b}
    return inverse


def _subject(ctx: ToolContext, subject_id: str) -> tuple[str, str, str | None, Entity | None]:
    """(вид, имя, шаблон, сущность): фракция пакета, NPC или существо реестра, место (его жители)."""
    rec = ctx.world.catalog.find(subject_id, "faction")
    if rec is not None:
        return "faction", rec.name, None, None
    en = ctx.world.entities.get(subject_id)
    if en is not None and en.kind == "creature":
        if (en.state or {}).get("dead"):
            raise ToolError(f"{en.name} мёртв: отвечать будет его фракция или место — укажите их")
        return "npc", en.name, en.template_id, en
    if en is not None and en.kind == "location":
        return "place", en.name, en.template_id, en
    raise ToolError(
        f"нет стороны {subject_id}: укажите фракцию (lookup_template kind=faction), NPC сцены или локацию реестра"
    )


def _delay(ctx: ToolContext, kind: str):
    """Срок ответа: фракции собираются несколько дней, NPC и местные отвечают сразу, как только это правдоподобно."""
    if kind != "faction":
        return None
    return lambda: ctx.dice.roll(sd.FACTION_DELAY).total * DAY


def _sync_attitude(en: Entity | None, tier: int, inverse: list) -> str | None:
    """NPC теплеет или остывает сам. Во враждебного его переводит только мастер: не всякий обиженный нападает."""
    if en is None or en.kind != "creature":
        return None
    st = dict(en.state or {})
    att = st.get("attitude", "hostile")
    new = "friendly" if tier >= 1 and att == "neutral" else "neutral" if tier <= -1 and att == "friendly" else None
    if new is None:
        return None
    inverse.append({"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)})
    en.state = {**st, "attitude": new}
    return new


def _apply(ctx: ToolContext, b: dict, deed: dict, inverse: list) -> list[dict]:
    """Поступок меняет отношение стороны и тех, кого задели круги. Возвращает изменения по сторонам."""
    now = int(ctx.world.scene.game_time)
    changes = []
    ch = sd.shift(
        b,
        deed["subject_id"],
        deed["kind"],
        deed["name"],
        deed["points"],
        deed["text"],
        deed["by"],
        deed["by_ids"],
        now,
        _delay(ctx, deed["kind"]),
    )
    en = ctx.world.entities.get(deed["subject_id"])
    att = _sync_attitude(en, sd.tier_of(sd.points_of(b, deed["subject_id"])), inverse)
    if att:
        ch["attitude"] = att
        ctx.changed.add(en.id)
    changes.append(ch)
    for fid, name, pts, why in sd.ripple(
        ctx.world.catalog, deed["subject_id"], deed["kind"], deed["points"], deed.get("template_id")
    ):
        c2 = sd.shift(
            b,
            fid,
            "faction",
            name,
            pts,
            f"{deed['text']} ({why})",
            deed["by"],
            deed["by_ids"],
            now,
            _delay(ctx, "faction"),
        )
        c2["why"] = why
        changes.append(c2)
    sd.ripen(b, now)
    return changes


class DeedArgs(BaseModel):
    subject_id: str = Field(
        description="кому помогли или навредили: id фракции (faction.*), NPC или существа сцены (en_…), "
        "локации реестра — тогда это её жители"
    )
    character_ids: list[str] = Field(min_length=1, max_length=8, description="кто из героев это сделал")
    effect: Literal["help", "harm"] = Field(description="help — помогли, harm — навредили")
    weight: Literal["minor", "major", "critical"] = Field(
        description="minor — мелочь (грубость, мелкая услуга); major — серьёзно (спасли товар, избили, обокрали); "
        "critical — судьбоносно (спасли жизнь или дело, убили своего, сорвали главный план)"
    )
    secret: bool = Field(
        False, description="никто из них не видел и не узнал: отношение не меняется, пока правда не всплывёт"
    )
    reason: str = Field(min_length=3, max_length=300, description="что сделали, одной фразой")


@tool(
    "record_deed",
    "Поступок героев перед NPC, фракцией или жителями места: помогли или навредили. Отношение и его круги по "
    "связанным фракциям считает сервер; когда отношение перейдёт на новую ступень, сторона захочет отблагодарить "
    "или отомстить, и ты получишь это как созревший ответ. Вызывай на заметные поступки, не на каждую реплику.",
    DeedArgs,
    ids={"character_ids": "characters"},
    closes=False,
)
async def record_deed(ctx: ToolContext, a: DeedArgs) -> dict:
    kind, name, template_id, _ = _subject(ctx, a.subject_id)
    heroes = [_character(ctx, cid) for cid in dict.fromkeys(a.character_ids)]
    pts = sd.WEIGHT[a.weight] * (1 if a.effect == "help" else -1)
    deed = {
        "subject_id": a.subject_id,
        "kind": kind,
        "name": name,
        "template_id": template_id,
        "points": pts,
        "text": a.reason,
        "by": [h.name for h in heroes],
        "by_ids": [h.id for h in heroes],
        "at": int(ctx.world.scene.game_time),
    }
    b = _book(ctx)
    inverse: list = []
    if a.secret:
        deed["id"] = sd._next_id(b, "deed")
        b["hidden"].append(deed)
        inverse.insert(0, _save(ctx, b))
        result = {
            "secret_deed": deed["id"],
            "subject": name,
            "note": "никто не видел: отношение не изменилось. Если правда всплывёт — expose_deed",
        }
    else:
        changes = _apply(ctx, b, deed, inverse)
        inverse.insert(0, _save(ctx, b))
        result = {"changes": changes}
    await ctx.record(
        "record_deed",
        target_id=a.subject_id if a.subject_id in ctx.world.entities else None,
        payload={**result, "effect": a.effect, "weight": a.weight, "reason": a.reason, "by": deed["by"]},
        inverse=inverse,
        hidden=True,
    )
    return result


class ExposeArgs(BaseModel):
    deed_id: str = Field(description="тайный поступок из get_standing (deed…)")
    how: str = Field(min_length=3, max_length=300, description="как правда всплыла")


@tool(
    "expose_deed",
    "Тайный поступок героев всплыл: свидетель, улика, болтливый сообщник. Теперь он меняет отношение, как явный.",
    ExposeArgs,
    closes=False,
)
async def expose_deed(ctx: ToolContext, a: ExposeArgs) -> dict:
    b = _book(ctx)
    deed = next((d for d in b["hidden"] if d.get("id") == a.deed_id), None)
    if deed is None:
        hidden = ", ".join(d["id"] for d in b["hidden"]) or "нет"
        raise ToolError(f"нет тайного поступка {a.deed_id}; тайные поступки: {hidden}")
    b["hidden"].remove(deed)
    deed = {**deed, "text": f"{deed['text']} (всплыло: {a.how})"}
    inverse: list = []
    changes = _apply(ctx, b, deed, inverse)
    inverse.insert(0, _save(ctx, b))
    result = {"exposed": a.deed_id, "changes": changes}
    await ctx.record("expose_deed", payload={**result, "how": a.how}, inverse=inverse, hidden=True)
    return result


class ResolveArgs(BaseModel):
    response_id: str = Field(description="созревший ответ (resp…) из подсказки хода или get_standing")
    how: str = Field(min_length=3, max_length=500, description="как сторона отблагодарила или отомстила")


@tool(
    "resolve_response",
    "Отмечает, что сторона ответила героям: благодарность или месть случилась в игре. Сначала сделай это "
    "инструментами (give_item, spawn_entity, learn_fact, apply_effect…), потом отметь здесь.",
    ResolveArgs,
    closes=False,
)
async def resolve_response(ctx: ToolContext, a: ResolveArgs) -> dict:
    b = _book(ctx)
    resp = next((r for r in b["responses"] if r["id"] == a.response_id), None)
    if resp is None or resp["status"] == "done":
        open_ = ", ".join(r["id"] for r in b["responses"] if r["status"] != "done") or "нет"
        raise ToolError(f"нет открытого ответа {a.response_id}; открыты: {open_}")
    sd.ripen(b, int(ctx.world.scene.game_time))
    if resp["status"] != "ready":
        raise ToolError(f"{resp['name']} ещё не готовы ответить: ответ созреет позже")
    resp["status"] = "done"
    resp["how"] = a.how
    inverse = [_save(ctx, b)]
    result = {"subject": resp["name"], "mood": sd.MOOD_RU[resp["mood"]], "how": a.how}
    await ctx.record("resolve_response", payload=result, inverse=inverse, hidden=True)
    return result


class NoArgs(BaseModel):
    pass


@tool(
    "get_standing",
    "Отношение к отряду: фракции, NPC и места с их ступенью и последними поступками, ответы (ждут, созрели) и "
    "тайные поступки героев. Только для мастера.",
    NoArgs,
    mutating=False,
    closes=False,
)
async def get_standing(ctx: ToolContext, a: NoArgs) -> dict:
    b = _book(ctx)
    now = int(ctx.world.scene.game_time)
    sd.ripen(b, now)  # только для показа: живой мастер видит созревшее и без хода ИИ
    responses = []
    for r in b["responses"]:
        if r["status"] == "done":
            continue
        item = {k: r[k] for k in ("id", "name", "status", "targets", "reason")}
        item["mood"] = sd.MOOD_RU[r["mood"]]
        item["tier"] = sd.tier_label(int(r["tier"]))
        if r["status"] == "pending":
            item["ready_in_hours"] = max(0, (int(r["due_at"]) - now) // 3600)
        else:
            item["means"] = sd.means(ctx.world.catalog, r)
        responses.append(item)
    hidden = [{"id": d["id"], "subject": d["name"], "by": d["by"], "what": d["text"]} for d in b["hidden"]]
    return {"standing": sd.standing_summary(b), "responses": responses, "secret_deeds": hidden}


class InspirationArgs(BaseModel):
    character_id: str
    reason: str = Field(
        min_length=3,
        max_length=300,
        description="за что: яркий отыгрыш черт, идеала, привязанности или слабости героя, смелое или хитрое "
        "решение, помощь отряду или другому герою",
    )


@tool(
    "grant_inspiration",
    "Вдохновение (SRD): награда герою за яркую, находчивую или самоотверженную игру. Вдохновение не копится: оно "
    "либо есть, либо нет. Герой тратит его на преимущество в атаке, проверке или спасброске (inspiration=true в "
    "roll_check или resolve_attack), когда игрок об этом просит.",
    InspirationArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def grant_inspiration(ctx: ToolContext, a: InspirationArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if sd.has_inspiration(ch.resources):
        raise ToolError(f"у {ch.name} уже есть вдохновение: оно не копится. Отдай награду другому герою")
    inverse = [{"table": "characters", "id": ch.id, "field": "resources", "before": copy.deepcopy(ch.resources)}]
    ch.resources = {**(ch.resources or {}), "inspiration": True}
    ctx.changed.add(ch.id)
    result = {"character": ch.name, "inspiration": True, "reason": a.reason}
    await ctx.record("grant_inspiration", target_id=ch.id, payload=result, inverse=inverse)
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} получает вдохновение: {a.reason}"})
    return result


async def run_standing(ctx: ToolContext) -> str:
    """Перед фазой решения: ответы, чей срок пришёл, созревают; мастер получает блок созревших ответов."""
    b = _book(ctx)
    if not b["responses"]:
        return ""
    fresh = sd.ripen(b, int(ctx.world.scene.game_time))
    if fresh:
        inverse = [_save(ctx, b)]
        await ctx.record(
            "standing_ripen",
            payload={"ready": [{"id": r["id"], "subject": r["name"], "mood": r["mood"]} for r in fresh]},
            inverse=inverse,
            hidden=True,
        )
    here = {e.id for e in ctx.world.in_scene_entities()}
    return sd.ready_note(b, ctx.world.catalog, here)
