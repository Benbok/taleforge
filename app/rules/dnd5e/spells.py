"""Заклинания по SRD 5.1: заклинатель класса на уровне, списки заклинаний, выбор при создании и числа сотворения.

Функции чистые: получают записи класса и заклинаний как словари из пакета и ничего не читают сами. Что герой знает,
лежит в листе: ``cantrips`` (заговоры), ``spells`` (известные заклинания, у волшебника — книга заклинаний) и
``prepared`` (подготовленные на сегодня у жреца, друида, паладина, волшебника, диагноста). Потраченные ячейки —
в ресурсах героя: ``slots_used`` ({круг: сколько}), ``pact_used`` (ячейки договора колдуна) и ``concentration``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.rules.dnd5e.engine import Dnd5eEngine

engine = Dnd5eEngine()

# Как класс SRD обращается с заклинаниями (раздел «Spellcasting» каждого класса). Ключ — имя класса в srd_ref.
# mode: known — знает несколько и творит любое из них; prepared — готовит на день из всего списка класса;
# spellbook — готовит из своей книги. prepare_div: делитель уровня в числе подготовленных (паладин — половина).
# ritual: known — ритуалом только известные, prepared — только подготовленные, book — любые из книги.
CASTING: dict[str, dict[str, Any]] = {
    "Bard": {"mode": "known", "ritual": "known"},
    "Cleric": {"mode": "prepared", "prepare_div": 1, "ritual": "prepared"},
    "Druid": {"mode": "prepared", "prepare_div": 1, "ritual": "prepared"},
    "Paladin": {"mode": "prepared", "prepare_div": 2, "ritual": None},
    "Ranger": {"mode": "known", "ritual": None},
    "Sorcerer": {"mode": "known", "ritual": None},
    "Warlock": {"mode": "known", "ritual": None},
    "Wizard": {"mode": "spellbook", "prepare_div": 1, "ritual": "book", "book_start": 6, "book_per_level": 2},
}
MODE_RU = {"known": "известные", "prepared": "подготовленные", "spellbook": "книга заклинаний"}
# В бою за ход успевают только заклинания, которые творятся действием, бонусным действием или реакцией.
COMBAT_TIMES = ("1 action", "1 bonus action", "1 reaction")
TIME_RU = {
    "1 action": "действие",
    "1 bonus action": "бонусное действие",
    "1 reaction": "реакция",
    "1 minute": "1 минута",
    "10 minutes": "10 минут",
    "1 hour": "1 час",
    "8 hours": "8 часов",
    "12 hours": "12 часов",
    "24 hours": "24 часа",
}
TIME_SECONDS = {
    "1 minute": 60,
    "10 minutes": 600,
    "1 hour": 3600,
    "8 hours": 28800,
    "12 hours": 43200,
    "24 hours": 86400,
}
RITUAL_SECONDS = 600  # ритуал — на 10 минут дольше обычного сотворения
SCHOOL_RU = {
    "abjuration": "ограждение",
    "conjuration": "вызов",
    "divination": "прорицание",
    "enchantment": "очарование",
    "evocation": "воплощение",
    "illusion": "иллюзия",
    "necromancy": "некромантия",
    "transmutation": "преобразование",
}
TOUCH_FT = 5


class SpellError(ValueError):
    """Заклинание нельзя выбрать или сотворить: причина словами для игрока и мастера."""


@dataclass
class Caster:
    """Заклинатель класса на уровне: откуда числа, сколько знает и готовит, какие ячейки есть."""

    class_id: str
    ability: str
    mode: str  # known | prepared | spellbook
    level: int
    save_dc: int
    attack: int
    ability_mod: int
    cantrips: int  # сколько заговоров знает
    known: int | None  # сколько заклинаний знает (known) или сколько в книге (spellbook)
    prepared: int | None  # сколько готовит на день (prepared, spellbook)
    slots: list[int] = field(default_factory=list)  # ячейки 1..N круга
    pact_slots: int = 0
    pact_level: int = 0
    max_level: int = 9  # потолок круга мира и класса
    ritual: str | None = None
    list_ref: dict[int, list[str]] | None = None  # свой список класса (диагност), иначе — class_refs заклинаний

    @property
    def top_level(self) -> int:
        """Высший круг, заклинания которого герой может выучить и сотворить ячейкой."""
        top = max((i + 1 for i, n in enumerate(self.slots) if n > 0), default=0)
        if self.pact_slots:
            top = max(top, self.pact_level)
        return min(top, self.max_level)

    @property
    def casts(self) -> bool:
        return self.cantrips > 0 or self.top_level > 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "ability": self.ability,
            "mode": self.mode,
            "save_dc": self.save_dc,
            "attack": self.attack,
            "cantrips": self.cantrips,
            "known": self.known,
            "prepared": self.prepared,
            "slots": self.slots,
            "pact_slots": self.pact_slots,
            "pact_level": self.pact_level,
            "top_level": self.top_level,
            "ritual": self.ritual,
        }


def _row(class_data: dict, level: int) -> dict:
    rows = [r for r in class_data.get("levels") or [] if isinstance(r, dict)]
    return next((r for r in rows if int(r.get("level", 0)) == level), {})


def _style(class_data: dict) -> dict[str, Any]:
    ref = (class_data.get("srd_ref") or {}).get("name")
    style = dict(CASTING.get(ref or "", {}))
    sc = class_data.get("spellcasting") or {}
    if isinstance(sc.get("prepared"), str):  # свой класс мира: формула подготовки строкой (диагност)
        style.setdefault("mode", "prepared")
        style.setdefault("prepare_div", 2 if re.search(r"level\s*/\s*2", sc["prepared"]) else 1)
        if sc.get("ritual"):
            style.setdefault("ritual", "prepared")
    for k in ("mode", "prepare_div", "ritual", "book_start", "book_per_level"):
        if k in sc:
            style[k] = sc[k]
    style.setdefault("mode", "known")
    return style


def caster(
    class_data: dict | None, class_id: str, level: int, abilities: dict[str, int], cap: int = 9
) -> Caster | None:
    """Заклинатель класса на уровне или None, если класс не творит заклинаний."""
    d = class_data or {}
    sc = d.get("spellcasting") or {}
    ability = sc.get("ability")
    if not ability:
        return None
    style = _style(d)
    row = _row(d, level)
    mod = engine.ability_modifier(int(abilities.get(ability, 10)))
    pb = engine.proficiency_bonus(level)
    max_level = min(int(d.get("max_spell_level") or 9), cap)
    slots = [int(x) for x in row.get("slots") or []][:max_level]
    pact = int(row.get("pact_slots") or 0)
    mode = style["mode"]
    known = row.get("spells_known")
    prepared = None
    if mode in ("prepared", "spellbook"):
        prepared = max(1, mod + level // int(style.get("prepare_div", 1)))
    if mode == "spellbook":
        known = int(style.get("book_start", 6)) + int(style.get("book_per_level", 2)) * (level - 1)
    list_ref = None
    if isinstance(d.get("spell_list"), dict):
        list_ref = {
            int(k): [x.get("spell_ref") for x in v or [] if isinstance(x, dict) and x.get("spell_ref")]
            for k, v in d["spell_list"].items()
        }
    c = Caster(
        class_id=class_id,
        ability=ability,
        mode=mode,
        level=level,
        save_dc=8 + pb + mod,
        attack=pb + mod,
        ability_mod=mod,
        cantrips=int(row.get("cantrips") or 0),
        known=int(known) if known is not None else None,
        prepared=prepared,
        slots=slots,
        pact_slots=pact,
        pact_level=min(int(row.get("pact_slot_level") or 0), max_level) if pact else 0,
        max_level=max_level,
        ritual=style.get("ritual"),
        list_ref=list_ref,
    )
    if mode == "prepared" and c.top_level == 0:
        c.prepared = 0  # паладин 1-го уровня ещё не колдует
    if not c.casts:
        return None if not (c.known or c.prepared) else c
    return c


def class_list(c: Caster, spells: dict[str, dict], forbidden: set[str] = frozenset()) -> list[str]:
    """Заклинания класса, доступные герою: из своего списка класса или по class_refs записей заклинаний.
    Без запрещённых миром и без кругов выше потолка."""
    out = []
    if c.list_ref is not None:
        ids = {s for v in c.list_ref.values() for s in v}
    else:
        ids = {sid for sid, s in spells.items() if c.class_id in (s.get("class_refs") or [])}
    for sid in ids:
        s = spells.get(sid)
        if s is None or sid in forbidden or s.get("player_available") is False:
            continue
        if int(s.get("level", 0)) > c.max_level:
            continue
        out.append(sid)
    return sorted(out, key=lambda x: (int(spells[x].get("level", 0)), spells[x].get("name", x)))


@dataclass
class Choice:
    """Что герой выбрал: заговоры, известные (или книга) и подготовленные."""

    cantrips: list[str]
    spells: list[str]
    prepared: list[str]

    @classmethod
    def of(cls, sheet: dict) -> Choice:
        def ids(k: str) -> list[str]:
            return [str(x) for x in sheet.get(k) or [] if isinstance(x, str)]

        return cls(ids("cantrips"), ids("spells"), ids("prepared"))


def needs(c: Caster) -> dict[str, int]:
    """Сколько выбрать: заговоров, заклинаний (известных или в книге) и подготовленных."""
    out = {"cantrips": c.cantrips, "spells": 0, "prepared": 0}
    if c.mode in ("known", "spellbook"):
        out["spells"] = int(c.known or 0)
    if c.mode in ("prepared", "spellbook"):
        out["prepared"] = int(c.prepared or 0)
    return out


def validate(
    c: Caster, ch: Choice, spells: dict[str, dict], forbidden: set[str] = frozenset(), exact: bool = True
) -> list[str]:
    """Ошибки выбора заклинаний. ``exact`` — при создании нужно ровно столько, сколько даёт класс; в игре — не больше
    (новые места появляются с уровнем, и игрок добирает их в книге заклинаний)."""
    errs: list[str] = []
    allowed = set(class_list(c, spells, forbidden))
    need = needs(c)

    def count(name: str, got: list[str], n: int) -> None:
        if len(set(got)) != len(got):
            errs.append(f"{name}: одно заклинание выбрано дважды")
        elif exact and len(got) != n:
            errs.append(f"{name}: выберите {n} (выбрано {len(got)})")
        elif len(got) > n:
            errs.append(f"{name}: не больше {n} (выбрано {len(got)})")

    count("заговоры", ch.cantrips, need["cantrips"])
    for sid in ch.cantrips:
        s = spells.get(sid)
        if s is None or int(s.get("level", -1)) != 0 or sid not in allowed:
            errs.append(f"заговоры: «{(s or {}).get('name', sid)}» не заговор вашего класса")
    if c.mode in ("known", "spellbook"):
        label = "книга заклинаний" if c.mode == "spellbook" else "заклинания"
        count(label, ch.spells, need["spells"])
        for sid in ch.spells:
            s = spells.get(sid)
            lvl = int((s or {}).get("level", -1))
            if s is None or sid not in allowed or lvl < 1:
                errs.append(f"{label}: «{(s or {}).get('name', sid)}» нет в списке вашего класса")
            elif lvl > c.top_level:
                errs.append(f"{label}: «{s.get('name', sid)}» {lvl}-го круга, вам пока доступен {c.top_level}-й")
    elif ch.spells:
        errs.append("заклинания: ваш класс не учит заклинания заранее, а готовит их на день")
    if c.mode in ("prepared", "spellbook"):
        pool = set(ch.spells) if c.mode == "spellbook" else allowed
        count("подготовленные", ch.prepared, need["prepared"])
        for sid in ch.prepared:
            s = spells.get(sid)
            lvl = int((s or {}).get("level", -1))
            if s is None or sid not in pool or lvl < 1:
                where = "в вашей книге" if c.mode == "spellbook" else "в списке вашего класса"
                errs.append(f"подготовленные: «{(s or {}).get('name', sid)}» нет {where}")
            elif lvl > c.top_level:
                errs.append(f"подготовленные: «{s.get('name', sid)}» {lvl}-го круга, вам пока доступен {c.top_level}-й")
    elif ch.prepared:
        errs.append("подготовленные: ваш класс не готовит заклинания, он творит известные")
    return errs


def can_cast_now(c: Caster, ch: Choice, spell_id: str, spell: dict, ritual: bool) -> str | None:
    """Знает ли герой заклинание так, чтобы сотворить его сейчас. None — может, иначе причина."""
    lvl = int(spell.get("level", 0))
    name = spell.get("name", spell_id)
    if lvl == 0:
        return None if spell_id in ch.cantrips else f"заговор «{name}» не из ваших заговоров"
    if ritual:
        if not spell.get("ritual"):
            return f"«{name}» не ритуал"
        if c.ritual is None:
            return "ваш класс не творит ритуалы"
        pool = {"known": ch.spells, "prepared": ch.prepared, "book": ch.spells}.get(c.ritual, [])
        return None if spell_id in pool else f"ритуалом творят только {MODE_RU.get(c.ritual, c.ritual)} заклинания"
    if c.mode == "known":
        return None if spell_id in ch.spells else f"«{name}» нет среди ваших заклинаний"
    if spell_id not in ch.prepared:
        return f"«{name}» не подготовлено: готовят после продолжительного отдыха"
    return None


def slots_left(c: Caster, resources: dict) -> dict[int, int]:
    """Сколько ячеек осталось по кругам (без ячеек договора)."""
    used = {int(k): int(v) for k, v in (resources.get("slots_used") or {}).items()}
    return {i + 1: max(0, n - used.get(i + 1, 0)) for i, n in enumerate(c.slots) if n > 0}


def pact_left(c: Caster, resources: dict) -> int:
    return max(0, c.pact_slots - int(resources.get("pact_used") or 0))


# Свиток заклинания (SRD 5.1, Spell Scroll): сложность спасброска и бонус атаки по кругу записанного заклинания.
SCROLL_STATS: dict[int, tuple[int, int]] = {
    0: (13, 5), 1: (13, 5), 2: (13, 5), 3: (15, 7), 4: (15, 7),
    5: (17, 9), 6: (17, 9), 7: (18, 10), 8: (18, 10), 9: (19, 11),
}  # fmt: skip


def on_class_list(c: Caster, spell_id: str, spell: dict) -> bool:
    """Есть ли заклинание в списке класса героя — без оглядки на круг."""
    if c.list_ref is not None:
        return any(spell_id in v for v in c.list_ref.values())
    return c.class_id in (spell.get("class_refs") or [])


def scroll_check(c: Caster | None, spell_id: str, spell: dict) -> int | None:
    """Может ли герой прочесть свиток. None — читает свободно; число — сложность проверки заклинательной
    характеристики (круг выше тех, что ему доступны); SpellError — не может вовсе."""
    name = spell.get("name", spell_id)
    if c is None:
        raise SpellError(f"«{name}» — для незаклинателя это просто знаки: свиток читают только заклинатели")
    if not on_class_list(c, spell_id, spell):
        raise SpellError(f"«{name}» не из списка вашего класса: такой свиток вам не прочесть")
    lvl = int(spell.get("level", 0))
    return 10 + lvl if lvl > c.top_level else None


def pick_slot(c: Caster, resources: dict, spell_level: int, slot_level: int | None) -> tuple[str, int]:
    """Какой ячейкой творить: ('slot', круг) или ('pact', круг). Ошибка — если подходящей ячейки нет."""
    if slot_level is not None and slot_level < spell_level:
        raise SpellError(f"ячейка {slot_level}-го круга мала: заклинание {spell_level}-го круга")
    if slot_level is not None and slot_level > c.max_level:
        raise SpellError(f"ячеек выше {c.max_level}-го круга у героя нет")
    pact = pact_left(c, resources)
    if c.pact_slots and (slot_level is None or slot_level == c.pact_level) and spell_level <= c.pact_level:
        if pact:
            return "pact", c.pact_level
        if not c.slots:
            raise SpellError("ячейки договора потрачены: они вернутся после короткого отдыха")
    left = slots_left(c, resources)
    if slot_level is not None:
        if left.get(slot_level, 0) > 0:
            return "slot", slot_level
        raise SpellError(f"ячейки {slot_level}-го круга потрачены{_left_note(left)}")
    for lvl in sorted(left):
        if lvl >= spell_level and left[lvl] > 0:
            return "slot", lvl
    raise SpellError(f"нет свободной ячейки {spell_level}-го круга и выше{_left_note(left)}")


def _left_note(left: dict[int, int]) -> str:
    free = [f"{k}-й круг ×{v}" for k, v in sorted(left.items()) if v > 0]
    return f"; свободны: {', '.join(free)}" if free else "; все ячейки потрачены до продолжительного отдыха"


def spend(resources: dict, kind: str, level: int) -> dict:
    res = dict(resources)
    if kind == "pact":
        res["pact_used"] = int(res.get("pact_used") or 0) + 1
    else:
        used = {str(k): int(v) for k, v in (res.get("slots_used") or {}).items()}
        used[str(level)] = used.get(str(level), 0) + 1
        res["slots_used"] = used
    return res


def dice_at(table: dict | None, key: int) -> str | None:
    """Кости из таблицы по кругу ячейки или уровню героя: берётся ближайшая ступень не выше ``key``."""
    if not isinstance(table, dict) or not table:
        return None
    steps = sorted((int(k), v) for k, v in table.items())
    out = None
    for k, v in steps:
        if k <= key:
            out = v
    return str(out if out is not None else steps[0][1])


def damage_parts(spell: dict, slot_level: int, char_level: int) -> list[tuple[str, str]]:
    """[(кости, вид урона)] заклинания на этой ячейке (заговор — по уровню героя)."""
    out = []
    for p in spell.get("damage") or []:
        expr = dice_at(p.get("by_slot"), slot_level) or dice_at(p.get("by_char_level"), char_level)
        if expr and p.get("type"):
            out.append((expr.replace(" ", ""), str(p["type"])))
    return out


def heal_expr(spell: dict, slot_level: int, ability_mod: int) -> str | None:
    """Кости лечения на этой ячейке: MOD — модификатор заклинательной характеристики."""
    expr = dice_at(spell.get("heal_by_slot"), slot_level)
    if not expr:
        return None
    expr = expr.replace(" ", "").replace("MOD", str(ability_mod)).replace("+-", "-")
    return expr


def missiles(spell: dict, slot_level: int) -> int:
    """Число снарядов у заклинаний вроде «Волшебной стрелы»: база и +1 за круг выше."""
    auto = spell.get("auto_hit") or {}
    base = int(auto.get("count", 1))
    return base + max(0, slot_level - int(spell.get("level", 1))) * int(auto.get("per_slot", 0))


def range_ft(spell: dict) -> int | None:
    """Дальность в футах: «касание» — 5, «на себя» — 0, иначе из данных; None — без ограничения в сцене."""
    r = str(spell.get("range", ""))
    if r == "Touch":
        return TOUCH_FT
    if r == "Self":
        return 0
    if spell.get("range_ft"):
        return int(spell["range_ft"])
    m = re.match(r"(\d+) mile", r)
    if m:
        return int(m.group(1)) * 5280
    return None


def cast_seconds(spell: dict, ritual: bool) -> int:
    return TIME_SECONDS.get(str(spell.get("casting_time")), 6) + (RITUAL_SECONDS if ritual else 0)


def summary(spell: dict) -> dict[str, Any]:
    """Карточка заклинания для интерфейса: русские подписи, описание и числа."""
    lvl = int(spell.get("level", 0))
    comps = list(spell.get("components") or [])
    return {
        "id": spell.get("id"),
        "name": spell.get("name"),
        "level": lvl,
        "school": SCHOOL_RU.get(str(spell.get("school")), spell.get("school")),
        "casting_time": TIME_RU.get(str(spell.get("casting_time")), spell.get("casting_time")),
        "combat": str(spell.get("casting_time")) in COMBAT_TIMES,
        "range": range_ru(spell),
        "components": comps,
        "material": spell.get("material_ru") or spell.get("material"),
        "duration": duration_ru(spell),
        "concentration": bool(spell.get("concentration")),
        "ritual": bool(spell.get("ritual")),
        "description": spell.get("description") or spell.get("srd_text") or "",
        "higher_levels": spell.get("higher_levels") or spell.get("srd_text_higher") or "",
        "flavor": spell.get("flavor") or "",
        "attack": spell.get("attack"),
        "save": (spell.get("save") or {}).get("stat"),
        "area": spell.get("area"),
        "targets": target_kind(spell),
    }


def target_kind(spell: dict) -> str:
    """Кого выбирать целью в интерфейсе: enemy — врага, ally — союзника или себя, self — никого, area — область."""
    if spell.get("heal_by_slot"):
        return "ally"
    if spell.get("area") and not spell.get("attack"):
        return "area" if str(spell.get("range")) != "Self" or spell.get("save") else "self"
    if spell.get("attack") or spell.get("save") or spell.get("damage") or spell.get("auto_hit"):
        return "enemy"
    if str(spell.get("range")) == "Self":
        return "self"
    return spell.get("target") or "any"


def range_ru(spell: dict) -> str:
    r = str(spell.get("range", ""))
    if r == "Touch":
        return "касание"
    if r == "Self":
        a = spell.get("area") or {}
        return f"на себя ({AREA_RU.get(a.get('shape'), a.get('shape'))} {a.get('size_ft')} фт)" if a else "на себя"
    if spell.get("range_ft"):
        return f"{spell['range_ft']} фт"
    return {"Sight": "в пределах видимости", "Unlimited": "без ограничений", "Special": "особая"}.get(
        r, r.replace("miles", "миль").replace("mile", "миля")
    )


AREA_RU = {"cone": "конус", "sphere": "сфера", "cube": "куб", "line": "линия", "cylinder": "цилиндр"}


def area_radius(area: dict) -> int:
    """Как далеко от точки на дистанции достаёт область: радиус сферы или цилиндра, сторона куба, длина линии."""
    return int(area.get("size_ft") or 0)


def area_span(area: dict) -> int:
    """Наибольшее расстояние между двумя существами внутри одной области: поперечник сферы или цилиндра,
    сторона куба, длина конуса или линии."""
    size = int(area.get("size_ft") or 0)
    return 2 * size if area.get("shape") in ("sphere", "cylinder") else size


def duration_ru(spell: dict) -> str:
    d = str(spell.get("duration", ""))
    table = {
        "Instantaneous": "мгновенно",
        "1 round": "1 раунд",
        "1 minute": "1 минута",
        "10 minutes": "10 минут",
        "1 hour": "1 час",
        "8 hours": "8 часов",
        "24 hours": "24 часа",
        "7 days": "7 дней",
        "10 days": "10 дней",
        "30 days": "30 дней",
        "Until dispelled": "пока не рассеют",
        "Until dispelled or triggered": "пока не рассеют или не сработает",
        "Special": "особая",
    }
    up_to = {
        "1 round": "1 раунда",
        "1 minute": "1 минуты",
        "10 minutes": "10 минут",
        "1 hour": "1 часа",
        "2 hours": "2 часов",
        "8 hours": "8 часов",
        "24 hours": "24 часов",
        "1 day": "1 дня",
    }
    if d.startswith("Up to "):
        rest = d.removeprefix("Up to ")
        return "до " + up_to.get(rest, rest)
    return table.get(d, d)
