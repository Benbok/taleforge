"""Парсер намерений (ТЗ, раздел 6): свободный текст игрока → проверяемое намерение.

Парсер — дешёвая быстрая модель со структурированным выводом (инструмент ``submit_intent``). Он не решает, получится
ли действие: только относит слова игрока к глаголу из закрытого списка и сопоставляет «гоблин слева» с id сущности.
Сервер проверяет ответ через Pydantic, подставляет id персонажа сам, обрезает лишние действия и решает, отклонить
реплику (оффтоп, чужой персонаж, непонятно) или пропустить её мастеру с намерением. Сбой парсера реплику не
блокирует: она уходит мастеру без намерения.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from app.core.world import PLAYABLE, ZONE_NAMES, World, is_scene_item
from app.db.models import Character

# Закрытый список глаголов ядра правил; всё, что не подошло, — custom и решается мастером
VERBS = (
    "attack",  # атаковать оружием или без
    "cast",  # сотворить заклинание
    "use_item",  # использовать предмет: зелье, инструмент, свиток
    "move",  # переместиться: сблизиться, отойти, уйти в другую локацию
    "inspect",  # осмотреть, изучить
    "search",  # искать, обыскать
    "interact",  # открыть, взломать, толкнуть предмет обстановки
    "pick_up",  # подобрать предмет, который лежит в сцене, и забрать себе
    "drop",  # бросить или оставить свой предмет
    "give",  # передать свой предмет другому герою
    "persuade",  # убедить
    "deceive",  # обмануть
    "intimidate",  # запугать
    "hide",  # спрятаться, красться
    "help",  # помочь союзнику
    "dodge",  # уклонение
    "dash",  # рывок
    "disengage",  # отход без атак по возможности
    "grapple",  # схватить, толкнуть существо
    "rest",  # отдых
    "talk",  # говорить с NPC без проверки
    "custom",  # нестандартное: мастер отнесёт к типу действия из правил
)
MOVE_VERBS = {"move", "dash", "disengage"}
LOW_CONFIDENCE = 0.5
ROUTE_CONFIDENCE = 0.8
MAX_ACTIONS_FREE = 3

PARSER_SYSTEM = (
    "Ты — парсер намерений текстовой ролевой игры по правилам D&D 5e. Игрок пишет, что делает его персонаж. "
    "Верни ровно один вызов submit_intent. Ты не мастер: не решай, получится ли действие, и не придумывай "
    "подробностей. Глагол — из списка; если ни один не подходит — custom. target_id и instrument_id бери только из "
    "перечней ниже; если игрок назвал цель, которой нет в сцене, оставь target_id пустым и понизь confidence. "
    "Если игрок заявляет результат («и убиваю его одним ударом»), убери его и поставь outcome_claim_removed. "
    "Сохраняй порядок шагов составной заявки в массиве actions: «подхожу и бью» — сначала move "
    "с target_id цели и zone=melee, затем attack с тем же target_id и выбранным instrument_id. "
    "Не подменяй перемещение атакой и не добавляй второй удар, преимущество или двойной урон из-за "
    "прыжка, хвата двумя руками или художественного описания: это не новые действия и не бонусы. "
    "kind: action — персонаж что-то делает (даже если при этом говорит); speech — только говорит, без действий; "
    "question_to_master — игрок спрашивает мастера о мире («что я вижу?»). "
    "problem: offtopic — реплика не про игру; other_character — игрок решает за другого героя; unclear — непонятно, "
    "что делает персонаж (тогда задай короткий вопрос в question). Прямую речь героя положи в speech."
)


class IntentAction(BaseModel):
    verb: Literal[VERBS]  # type: ignore[valid-type]
    target_id: str | None = Field(None, description="id цели из перечня сущностей сцены или героев")
    instrument_id: str | None = Field(None, description="id предмета из снаряжения героя")
    spell_id: str | None = Field(None, description="id заклинания из книги героя, если он творит заклинание")
    target_ids: list[str] = Field(
        default_factory=list, max_length=12, description="площадное заклинание: все, кого игрок накрывает областью"
    )
    free_target: str = Field(
        "",
        max_length=300,
        description="цель словами игрока, если её нет в сцене: «факел на стене», «иллюзорный ящик у двери»",
    )
    slot_level: int | None = Field(None, ge=1, le=9, description="круг ячейки, если игрок назвал его явно")
    ritual: bool = Field(False, description="заклинание творится ритуалом (игрок так сказал)")
    zone: Literal["melee", "near", "far"] | None = Field(None, description="куда перемещается: вплотную/близко/далеко")
    skill: str | None = Field(None, max_length=32, description="навык, если игрок его назвал")
    manner: str = Field("", max_length=300, description="как именно: «с разбега, целясь в ноги»")


class Intent(BaseModel):
    kind: Literal["action", "speech", "question_to_master"] = "action"
    actions: list[IntentAction] = Field(default_factory=list, max_length=8)
    speech: str | None = Field(None, max_length=1000)
    outcome_claim_removed: bool = False
    confidence: float = Field(1.0, ge=0, le=1)
    problem: Literal["none", "offtopic", "other_character", "unclear"] = "none"
    question: str | None = Field(None, max_length=300, description="уточняющий вопрос игроку при problem=unclear")


@dataclass
class ParseResult:
    intent: dict[str, Any] | None = None  # сохраняется в сообщении и уходит мастеру
    reject: str | None = None  # реплика не принимается: причина или уточняющий вопрос
    notice: str | None = None  # реплика принята, но игроку есть что сказать (лишние действия вернули)
    kind: str | None = None  # какой реплика стала в чате: action | speech | ooc (None — как прислал клиент)
    notes: list[str] = field(default_factory=list)


def _schema(values: dict[str, list[str]]) -> dict[str, Any]:
    act = IntentAction.model_json_schema()
    act.pop("title", None)
    for p in act["properties"].values():
        p.pop("title", None)
    for fname, allowed in values.items():
        if allowed and len(allowed) <= 60:
            act["properties"][fname] = {
                "anyOf": [{"type": "string", "enum": allowed}, {"type": "null"}],
                "description": act["properties"][fname].get("description", ""),
            }
    root = Intent.model_json_schema()
    root.pop("title", None)
    root.pop("$defs", None)
    for p in root["properties"].values():
        p.pop("title", None)
    root["properties"]["actions"] = {"type": "array", "items": act, "maxItems": 8}
    return root


def tool_spec(values: dict[str, list[str]]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "submit_intent",
            "description": "Намерение игрока: глаголы действий, цели и предметы по id, прямая речь, уверенность.",
            "parameters": _schema(values),
        },
    }


def context_for(world: World, ch: Character) -> tuple[str, dict[str, list[str]]]:
    """Что видит парсер: лист героя без чисел, его снаряжение и видимые сущности сцены с id (раздел 6, шаг 1)."""
    targets, lines = [], []
    for other in world.characters.values():
        if other.status in PLAYABLE:
            targets.append(other.id)
            lines.append(f"{other.id}  {other.name} (герой{', это он сам' if other.id == ch.id else ''})")
    for en in world.in_scene_entities():
        st = en.state or {}
        if st.get("fled"):
            continue
        targets.append(en.id)
        extra = " мёртв" if st.get("dead") else ""
        kind = "предмет, можно подобрать" if is_scene_item(en) else en.kind
        lines.append(f"{en.id}  {en.name} ({kind}, {ZONE_NAMES.get(en.zone, en.zone)}{extra})")
    items = world.inventory.get(ch.id, [])
    inv = [f"{it.id}  {world.item_name(it)}{' [надет]' if it.equipped else ''}" for it in items]
    spells = _castable(world, ch)
    sp = [f"{sid}  {name} ({'заговор' if lvl == 0 else f'{lvl}-й круг'})" for sid, name, lvl in spells]
    mode = "бой: за ход одно действие и перемещение" if world.in_fight(ch.id) else "свободный режим"
    text = (
        f"Персонаж игрока: {ch.id} {ch.name}. Режим сцены: {mode}.\n"
        f"Сущности сцены:\n{chr(10).join(lines) or 'нет'}\n"
        f"Снаряжение героя:\n{chr(10).join(inv) or 'нет'}\n"
        + (f"Заклинания героя (для cast — spell_id):\n{chr(10).join(sp)}\n" if sp else "")
        + f"Глаголы: {', '.join(VERBS)}."
    )
    return text, {"target_id": targets, "instrument_id": [it.id for it in items], "spell_id": [s[0] for s in spells]}


def _castable(world: World, ch: Character) -> list[tuple[str, str, int]]:
    """Заклинания, которые герой может сотворить: заговоры, известные и подготовленные."""
    from app.core.spells import book_view

    b = book_view(ch.sheet or {}, ch.resources or {}, world.catalog)
    return [(x["id"], x["name"], x["level"]) for x in (b or {}).get("spells", []) if x["prepared"]]


def check(raw: dict[str, Any], world: World, ch: Character) -> ParseResult:
    """Проверка ответа парсера сервером: схема, id, лимит действий, причины отказа (раздел 6)."""
    try:
        intent = Intent.model_validate(raw)
    except ValidationError:
        return ParseResult(notes=["ответ парсера не прошёл схему"])
    if intent.problem == "offtopic":
        return ParseResult(kind="ooc", notice="Похоже, это не про игру: сообщение ушло во внеигровой чат.")
    if intent.problem == "other_character":
        return ParseResult(reject=f"Нельзя решать за чужого героя: опишите, что делает {ch.name}.")
    if intent.problem == "unclear" or intent.confidence < LOW_CONFIDENCE:
        return ParseResult(reject=intent.question or f"Не понял, что делает {ch.name}. Опишите действие точнее.")

    valid_targets = set(world.characters) | {e.id for e in world.in_scene_entities()}
    own = {it.id for it in world.inventory.get(ch.id, [])}
    known = {s[0] for s in _castable(world, ch)}
    notes: list[str] = []
    acts: list[dict[str, Any]] = []
    for a in intent.actions:
        d = a.model_dump()
        if d["target_id"] and d["target_id"] not in valid_targets:
            notes.append(f"неизвестная цель {d['target_id']} убрана")
            d["target_id"] = None
        if d.get("target_ids"):
            bad = [t for t in d["target_ids"] if t not in valid_targets]
            if bad:
                notes.append(f"неизвестные цели {', '.join(bad)} убраны")
            d["target_ids"] = [t for t in dict.fromkeys(d["target_ids"]) if t in valid_targets]
        if d["instrument_id"] and d["instrument_id"] not in own:
            d["missing_item"] = True  # предмета нет: мастер обыграет («рука нащупывает пустые ножны»)
        if d["spell_id"] and d["spell_id"] not in known:
            d["unknown_spell"] = True  # такого заклинания герой не знает: мастер откажет словами
        if d["verb"] != "cast":
            d.pop("slot_level", None)
            d.pop("ritual", None)
            d.pop("target_ids", None)
            d.pop("free_target", None)
        acts.append(d)

    notice = None
    if world.in_fight(ch.id):
        main = [a for a in acts if a["verb"] not in MOVE_VERBS]
        moves = [a for a in acts if a["verb"] in MOVE_VERBS]
        keep = main[:1] + moves[:1] if main else moves[:1]
        dropped = [a for a in acts if a not in keep]
    else:
        keep, dropped = acts[:MAX_ACTIONS_FREE], acts[MAX_ACTIONS_FREE:]
    if dropped:
        keep = [a for a in acts if a in keep]  # порядок как у игрока
        notice = "За ход учтено: " + ", ".join(_verb_ru(a) for a in keep) + ". Остальное заявите следующим ходом."

    out = intent.model_dump()
    out.update(character_id=ch.id, actions=keep)
    kind = "speech" if intent.kind == "speech" and not keep else "action"
    return ParseResult(intent=out, notice=notice, notes=notes, kind=kind)


VERB_RU = {
    "attack": "атака",
    "cast": "заклинание",
    "use_item": "предмет",
    "move": "перемещение",
    "inspect": "осмотр",
    "search": "поиск",
    "interact": "взаимодействие",
    "pick_up": "подобрать",
    "drop": "бросить",
    "give": "передать",
    "persuade": "убеждение",
    "deceive": "обман",
    "intimidate": "запугивание",
    "hide": "скрытность",
    "help": "помощь",
    "dodge": "уклонение",
    "dash": "рывок",
    "disengage": "отход",
    "grapple": "захват",
    "rest": "отдых",
    "talk": "разговор",
    "custom": "особое действие",
}


def _verb_ru(a: dict[str, Any]) -> str:
    return VERB_RU.get(a["verb"], a["verb"])


def describe(intent: dict[str, Any] | None) -> str:
    """Намерение одной строкой для фазы решения мастера."""
    if not intent:
        return ""
    parts = []
    for a in intent.get("actions") or []:
        bits = [a["verb"]]
        for k in ("target_id", "instrument_id", "spell_id", "slot_level", "zone", "skill"):
            if a.get(k):
                bits.append(f"{k}={a[k]}")
        if a.get("target_ids"):
            bits.append(f"target_ids={','.join(a['target_ids'])}")
        if a.get("free_target"):
            bits.append(f"цель вне реестра: «{a['free_target']}» — заведи её инструментом, если нужно, потом действуй")
        if a.get("missing_item"):
            bits.append("ПРЕДМЕТА НЕТ В СНАРЯЖЕНИИ")
        if a.get("unknown_spell"):
            bits.append("ГЕРОЙ НЕ ЗНАЕТ ЭТОГО ЗАКЛИНАНИЯ")
        if a.get("manner"):
            bits.append(f"«{a['manner']}»")
        parts.append(" ".join(bits))
    out = "; ".join(parts) or intent.get("kind", "action")
    if intent.get("outcome_claim_removed"):
        out += "; заявленный игроком исход отброшен"
    return f"{out} (уверенность {intent.get('confidence', 1):.2f})"


def routable_attack(intent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Маршрутизатор механик (раздел 7): однозначная атака оружием по видимой цели идёт в resolve_attack без модели."""
    if not intent or intent.get("confidence", 0) < ROUTE_CONFIDENCE:
        return None
    acts = [a for a in intent.get("actions") or [] if a["verb"] not in MOVE_VERBS]
    if len(acts) != 1:
        return None
    a = acts[0]
    if a["verb"] != "attack" or not a.get("target_id") or not a.get("instrument_id") or a.get("missing_item"):
        return None
    return {"attacker_id": intent["character_id"], "target_id": a["target_id"], "attack": a["instrument_id"]}


def routable_cast(intent: dict[str, Any] | None) -> dict[str, Any] | None:
    """Однозначное заклинание из книги героя (кнопкой или ясной репликой) сервер творит сам через cast_spell.
    Площадные заклинания и заклинания без ясной цели остаются мастеру: он решает, кто попал в область."""
    if not intent or intent.get("confidence", 0) < ROUTE_CONFIDENCE:
        return None
    acts = [a for a in intent.get("actions") or [] if a["verb"] not in MOVE_VERBS]
    if len(acts) != 1:
        return None
    a = acts[0]
    if a["verb"] != "cast" or not a.get("spell_id") or a.get("unknown_spell"):
        return None
    if a.get("free_target"):
        return None  # цели нет в реестре: её сначала заводит мастер
    args: dict[str, Any] = {"caster_id": intent["character_id"], "spell_id": a["spell_id"]}
    if a.get("target_ids"):
        args["target_ids"] = list(a["target_ids"])
        args["area_chosen"] = True  # кого накрыть, игрок выбрал сам
    elif a.get("target_id"):
        args["target_ids"] = [a["target_id"]]
    if a.get("slot_level"):
        args["slot_level"] = int(a["slot_level"])
    if a.get("ritual"):
        args["ritual"] = True
    return args


SKILL_VERB_MAP: dict[str, tuple[str, str]] = {
    "hide": ("stealth", "dc.medium"),
    "search": ("perception", "dc.medium"),
    "inspect": ("investigation", "dc.medium"),
    "persuade": ("persuasion", "dc.medium"),
    "deceive": ("deception", "dc.medium"),
    "intimidate": ("intimidation", "dc.medium"),
    "grapple": ("athletics", "dc.medium"),
}


def routable_tool_call(intent: dict[str, Any] | None) -> tuple[str, dict[str, Any]] | None:
    """Маршрутизация типовых действий и проверок без обращения к модели решения (раздел 7).
    Возвращает (tool_name, args) или None.
    """
    if not intent or intent.get("confidence", 0) < ROUTE_CONFIDENCE:
        return None
    acts = [a for a in intent.get("actions") or [] if a["verb"] not in MOVE_VERBS]
    if len(acts) != 1:
        return None
    a = acts[0]
    char_id = intent.get("character_id")
    if not char_id:
        return None

    verb = a.get("verb")
    if verb == "use_item" and a.get("instrument_id") and not a.get("missing_item"):
        args: dict[str, Any] = {
            "character_id": char_id,
            "inventory_id": a["instrument_id"],
        }
        if a.get("target_id"):
            args["target_id"] = a["target_id"]
        return "use_item", args

    if verb == "rest":
        manner = (a.get("manner") or "").lower()
        kind = "long" if any(w in manner for w in ("длинн", "продолжит", "long", "ноч")) else "short"
        return "rest", {"character_ids": [char_id], "kind": kind}

    if verb in SKILL_VERB_MAP:
        stat, dc = SKILL_VERB_MAP[verb]
        from app.rules.dnd5e.tables import ABILITIES, SKILLS

        if a.get("skill") and (a["skill"] in SKILLS or a["skill"] in ABILITIES):
            stat = a["skill"]
        reason = a.get("manner") or _verb_ru(a)
        return "roll_check", {
            "character_id": char_id,
            "stat": stat,
            "kind": "check",
            "difficulty": dc,
            "reason": reason,
        }

    return None
