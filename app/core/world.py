"""Мир кампании для механики: персонажи и сущности как «участники» с числами из движка правил.

Хиты, эффекты и зоны читаются из БД на каждый ход и туда же пишутся; модель чисел не хранит (раздел 7.1).
Зоны дальности считаются относительно отряда: сущность вплотную, близко или далеко от героев.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogView, Entry
from app.db.models import ActiveEffect, Campaign, CampaignSecret, Character, Entity, InventoryItem, Scene
from app.rules.base import DeathSaves, HitPoints
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e.character import derive
from app.rules.dnd5e.engine import Dnd5eEngine
from app.rules.dnd5e.tables import ABILITIES, SKILLS

ZONE_FT = {"melee": 5, "near": 30, "far": 120}
ZONE_NAMES = {"melee": "вплотную", "near": "близко", "far": "далеко"}
PLAYABLE = ("approved", "active")
engine = Dnd5eEngine()


class WorldError(Exception):
    """Нарушение правил мира: нет такой сущности, цель мертва, нет действия. Уходит модели как ошибка."""


@dataclass
class Actor:
    id: str
    name: str
    kind: str  # character | creature
    obj: Character | Entity
    hp: HitPoints
    ac: int
    abilities: dict[str, int]
    mods: dict[str, int]
    saves: dict[str, int]
    skills: dict[str, int]
    pb: int
    attacks: list[dict]
    resistances: set[str] = field(default_factory=set)
    vulnerabilities: set[str] = field(default_factory=set)
    immunities: set[str] = field(default_factory=set)
    condition_immunities: set[str] = field(default_factory=set)
    effects: list[tuple[ActiveEffect, Entry]] = field(default_factory=list)
    modifiers: mod.Modifiers = field(default_factory=mod.Modifiers)
    zone: str = "near"
    template_id: str | None = None
    speed: int = 30  # футов за ход, для перемещения в бою

    @property
    def alive(self) -> bool:
        return not self.hp.dead

    @property
    def conscious(self) -> bool:
        return self.alive and self.hp.current > 0

    def status(self) -> str:
        if self.hp.dead:
            return "мёртв"
        if self.hp.current == 0:
            return "стабилен" if self.hp.death_saves.stable else "при смерти"
        return f"хиты {self.hp.current}/{self.hp.maximum}" + (f" +{self.hp.temp} врем." if self.hp.temp else "")

    def save_hp(self) -> dict:
        """Пишет хиты обратно в карточку. Возвращает прежние значения для обратной дельты."""
        hp = {
            "hp": self.hp.current,
            "hp_max": self.hp.maximum,
            "temp_hp": self.hp.temp,
            "dead": self.hp.dead,
            "death_saves": [self.hp.death_saves.successes, self.hp.death_saves.failures],
        }
        if isinstance(self.obj, Character):
            before = {k: (self.obj.resources or {}).get(k) for k in hp}
            self.obj.resources = {**(self.obj.resources or {}), **hp}
            if self.hp.dead:
                self.obj.status = "dead"
        else:
            before = {k: (self.obj.state or {}).get(k) for k in hp}
            self.obj.state = {**(self.obj.state or {}), **hp}
        return before

    def ability_check_bonus(self, stat: str) -> tuple[int, str]:
        """Бонус проверки: навык (``perception``) или характеристика (``dex``). Возвращает бонус и что это."""
        if stat in SKILLS:
            return self.skills.get(stat, self.mods[SKILLS[stat]]), SKILLS[stat]
        if stat in ABILITIES:
            return self.mods[stat], stat
        raise WorldError(f"нет навыка или характеристики {stat}; допустимо: {', '.join([*ABILITIES, *SKILLS])}")


def _hp_from(data: dict, maximum: int) -> HitPoints:
    ds = data.get("death_saves") or [0, 0]
    return HitPoints(
        current=int(data.get("hp", maximum)),
        maximum=int(data.get("hp_max", maximum)),
        temp=int(data.get("temp_hp", 0)),
        death_saves=DeathSaves(int(ds[0]), int(ds[1])),
        dead=bool(data.get("dead", False)),
    )


def _effects_for(target_id: str, effects: list[ActiveEffect], cat: CatalogView) -> list[tuple[ActiveEffect, Entry]]:
    out = []
    for e in effects:
        if e.target_id != target_id:
            continue
        rec = cat.find(e.effect_template_id)
        if rec is not None:
            out.append((e, rec))
    return out


def _collect(effs: list[tuple[ActiveEffect, Entry]], cat: CatalogView) -> mod.Modifiers:
    def lookup(name: str) -> dict | None:
        rec = cat.find(name if "." in name else f"condition.{name}")
        return {"id": rec.id, **rec.data} if rec else None

    return mod.collect(((rec.id, rec.data, e.stacks) for e, rec in effs), lookup)


def lineage_features(sheet: dict, cat: CatalogView) -> tuple[Entry | None, dict | None, list[dict]]:
    """Вторая раса героя после Порога (sheet.lineage_id) и его каста (sheet.lineage_caste): запись, каста и черты."""
    lin = cat.find(sheet.get("lineage_id") or "", "lineage")
    if lin is None:
        return None, None, []
    caste = next((c for c in lin.data.get("castes") or [] if c.get("id") == sheet.get("lineage_caste")), None)
    feats = [f for f in lin.data.get("features") or [] if isinstance(f, dict)]
    feats += [f for f in (caste or {}).get("features") or [] if isinstance(f, dict)]
    return lin, caste, feats


def natural_ac(feats: list[dict], dex_mod: int) -> int | None:
    """«Тело роя»: КД 13 + Лов без доспехов (модификатор set ac_base)."""
    for f in feats:
        for m in f.get("modifiers") or []:
            if m.get("op") == "set" and m.get("target") == "ac_base":
                base = str(m.get("value", "")).split("+")[0].strip()
                if base.isdigit():
                    return int(base) + dex_mod
    return None


def character_actor(
    ch: Character, cat: CatalogView, inventory: list[InventoryItem], effects: list[ActiveEffect]
) -> Actor:
    sheet = ch.sheet or {}
    cls = cat.find(sheet.get("class_id", ""), "class")
    origin = cat.find(sheet.get("origin_id", ""), "origin")
    inv = []
    for it in inventory:
        rec = cat.find(it.item_template_id, "item_template")
        if rec is not None:
            inv.append((it.id, {"id": rec.id, **rec.data}, it.equipped, it.display_name or rec.name))
    d = derive(sheet, cls.data if cls else None, origin.data if origin else None, inv)
    effs = _effects_for(ch.id, effects, cat)
    lin, _, feats = lineage_features(sheet, cat)
    lin_mods = [m for f in feats for m in f.get("modifiers") or [] if isinstance(m, dict)]
    extra = [(lin.id, {"modifiers": lin_mods}, 1)] if lin else []
    mods_ = mod.collect(
        [*extra, *((rec.id, rec.data, e.stacks) for e, rec in effs)],
        lambda name: (lambda r: {"id": r.id, **r.data} if r else None)(
            cat.find(name if "." in name else f"condition.{name}")
        ),
    )
    res, vul, imm = mod.defenses(mods_)
    skills = dict(d.skills)
    for m in lin_mods:
        # владения навыками от Порога: к навыку, которым герой ещё не владеет, прибавляется бонус мастерства
        s = m.get("value")
        if m.get("op") == "proficiency" and m.get("kind") == "skill" and s in SKILLS and skills[s] == d.mods[SKILLS[s]]:
            skills[s] += d.pb
    ac = d.ac
    armored = any(
        eq and item.get("category") == "armor" and item.get("armor_type") != "shield" for _, item, eq, _ in inv
    )
    natural = natural_ac(feats, d.mods["dex"]) if lin else None
    # «Доспехи мага» и подобные: базовый КД без доспеха из эффекта (set ac_base)
    spell_base = natural_ac([rec.data for _, rec in effs], d.mods["dex"])
    if spell_base is not None:
        natural = max(natural or 0, spell_base)
    if natural is not None and not armored:
        shield = next((i for _, i, eq, _ in inv if eq and i.get("armor_type") == "shield"), None)
        ac = max(ac, natural + (int(shield.get("ac_bonus", 2)) if shield else 0))
    floor = max(
        (
            int(m["value"])
            for _, m in mods_.own("set")
            if m.get("target") == "ac_min" and isinstance(m.get("value"), int)
        ),
        default=0,
    )
    ac = max(ac, floor)  # «Дубовая кожа»: КД не ниже 16
    return Actor(
        id=ch.id,
        name=ch.name,
        kind="character",
        obj=ch,
        hp=_hp_from(ch.resources or {}, d.hp_max),
        ac=ac + mod.add_value(mods_, "ac"),
        abilities=d.abilities,
        mods=d.mods,
        saves=d.saves,
        skills=skills,
        pb=d.pb,
        attacks=[a.as_dict() for a in d.attacks],
        resistances=set(d.resistances) | res,
        vulnerabilities=vul,
        immunities=imm,
        condition_immunities=mod.condition_immunities(mods_),
        effects=effs,
        modifiers=mods_,
        zone="party",
        speed=int(d.speed or 30),
    )


def creature_stats(template: dict) -> dict:
    """Числа существа из шаблона (блок статов SRD). Без характеристик и КД существо в бой не выходит."""
    if not template.get("abilities") or template.get("ac") is None or not template.get("hp"):
        raise WorldError("у шаблона нет блока статов (abilities, ac, hp): его нельзя выставить в сцену")
    abil = {a: int(template["abilities"].get(a, 10)) for a in ABILITIES}
    mods = {a: engine.ability_modifier(v) for a, v in abil.items()}
    pb = engine.proficiency_bonus(max(1, min(20, int(_cr_level(template.get("cr", 0))))))
    saves = {a: int((template.get("saves") or {}).get(a, mods[a])) for a in ABILITIES}
    skills = {s: int((template.get("skills") or {}).get(s, mods[a])) for s, a in SKILLS.items()}
    attacks = []
    for act in template.get("actions") or []:
        if act.get("attack_bonus") is None or not act.get("damage"):
            continue
        dmg = act["damage"][0]
        rng = act.get("range") or {}
        attacks.append(
            {
                "key": act.get("key") or act.get("name", "attack"),
                "name": act.get("name", "атака"),
                "attack_bonus": int(act["attack_bonus"]),
                "damage": dmg["dice"],
                "damage_type": dmg["type"],
                "extra_damage": [x for x in act["damage"][1:] if x.get("dice")],
                "kind": "ranged" if "ranged" in str(act.get("kind", "")) else "melee",
                "reach_ft": int(act.get("reach_ft", 5)),
                "normal_ft": rng.get("normal"),
                "long_ft": rng.get("long"),
            }
        )
    return {"abilities": abil, "mods": mods, "pb": pb, "saves": saves, "skills": skills, "attacks": attacks}


def _cr_level(cr: Any) -> int:
    """Бонус мастерства существа по SRD растёт с показателем опасности так же, как у героя с уровнем."""
    c = float(cr or 0)
    return 1 if c < 5 else 5 if c < 9 else 9 if c < 13 else 13 if c < 17 else 17


def creature_actor(en: Entity, cat: CatalogView, effects: list[ActiveEffect]) -> Actor:
    rec = cat.find(en.template_id or "", "creature_template")
    if rec is None:
        raise WorldError(f"у сущности {en.id} нет шаблона существа")
    st = creature_stats(rec.data)
    effs = _effects_for(en.id, effects, cat)
    mods_ = _collect(effs, cat)
    res, vul, imm = mod.defenses(mods_)
    return Actor(
        id=en.id,
        name=en.name,
        kind="creature",
        obj=en,
        hp=_hp_from(en.state or {}, int((rec.data.get("hp") or {}).get("average", 1))),
        ac=int(rec.data["ac"]) + mod.add_value(mods_, "ac"),
        abilities=st["abilities"],
        mods=st["mods"],
        saves=st["saves"],
        skills=st["skills"],
        pb=st["pb"],
        attacks=st["attacks"],
        resistances=set(rec.data.get("damage_resistances") or []) | res,
        vulnerabilities=set(rec.data.get("damage_vulnerabilities") or []) | vul,
        immunities=set(rec.data.get("damage_immunities") or []) | imm,
        condition_immunities=set(rec.data.get("condition_immunities") or []) | mod.condition_immunities(mods_),
        effects=effs,
        modifiers=mods_,
        zone=en.zone,
        template_id=en.template_id,
        speed=_walk_speed(rec.data.get("speed")),
    )


def _walk_speed(v: Any) -> int:
    """Скорость существа из шаблона: число, {walk: 30} или строка «30 ft., fly 60 ft.»."""
    if isinstance(v, dict):
        v = v.get("walk") or next(iter(v.values()), 30)
    if isinstance(v, (int, float)):
        return int(v)
    digits = "".join(ch if ch.isdigit() else " " for ch in str(v or "")).split()
    return int(digits[0]) if digits else 30


@dataclass
class World:
    campaign: Campaign
    catalog: CatalogView
    scene: Scene
    characters: dict[str, Character]
    entities: dict[str, Entity]
    inventory: dict[str, list[InventoryItem]]
    effects: list[ActiveEffect]
    plot: dict[str, Any] = field(default_factory=dict)  # каркас сюжета (скрыт от игроков, см. app/core/plot.py)
    # место группы, ради которой идёт ход мастера, когда отряд разделён; None — весь отряд (design/party-split.md)
    focus: str | None = None
    crew: set[str] = field(default_factory=set)  # герои этой группы: куда бы они ни ушли за ход, сцена с ними
    _actors: dict[str, Actor] = field(default_factory=dict)

    def actor(self, actor_id: str) -> Actor:
        if actor_id in self._actors:
            return self._actors[actor_id]
        if actor_id in self.characters:
            a = character_actor(self.characters[actor_id], self.catalog, self.inventory.get(actor_id, []), self.effects)
        elif actor_id in self.entities and self.entities[actor_id].kind == "creature":
            a = creature_actor(self.entities[actor_id], self.catalog, self.effects)
        elif actor_id in self.entities:
            raise WorldError(f"{actor_id} — не существо: у локаций и объектов нет хитов и действий")
        else:
            raise WorldError(
                f"нет участника {actor_id} в сцене. Существо, которое только упомянуто, сначала выставьте spawn_entity"
            )
        self._actors[actor_id] = a
        return a

    def item_name(self, it: InventoryItem) -> str:
        if it.display_name:
            return it.display_name
        rec = self.catalog.find(it.item_template_id)
        return rec.name if rec else it.item_template_id

    def invalidate(self, actor_id: str) -> None:
        self._actors.pop(actor_id, None)

    def distance_ft(self, a: Actor, b: Actor) -> int:
        """Футы между участниками по их позициям в сцене (app/core/positions.py)."""
        from app.core.positions import distance, pos_of

        if self.actor_place(a.id) != self.actor_place(b.id):
            raise WorldError(f"{a.name} и {b.name} в разных местах: отряд разделён, отсюда не достать")
        both = a.kind == "creature" and b.kind == "creature"
        return distance(pos_of(self, a.id), pos_of(self, b.id), both_creatures=both)

    # --- места отряда (разделение отряда, design/party-split.md) ---

    def place_of(self, ch: Character) -> str | None:
        """Где стоит герой: своё место, если его переводили отдельно, иначе место сцены."""
        return ch.location_id or self.scene.location_id

    def actor_place(self, actor_id: str) -> str | None:
        ch = self.characters.get(actor_id)
        if ch is not None:
            return self.place_of(ch)
        en = self.entities.get(actor_id)
        return en.location_id if en is not None else None

    def groups(self) -> dict[str | None, list[Character]]:
        """Герои отряда по местам. Одна запись — отряд вместе; несколько — отряд разделился."""
        return party_groups(self.characters.values(), self.scene)

    @property
    def split(self) -> bool:
        return len(self.groups()) > 1

    def scene_places(self) -> list[str]:
        """Места, которые сейчас в сцене: где стоят герои. Пока отряд вместе, это одно место сцены; ход группы
        разделившегося отряда видит только её место."""
        if self.focus:
            here = [self.place_of(self.characters[i]) for i in self.crew if i in self.characters]
            return [p for p in dict.fromkeys(here) if p] or [self.focus]
        places = [p for p in self.groups() if p]
        if not places and self.scene.location_id:
            places = [self.scene.location_id]
        return places

    def in_scene_entities(self, place: str | None = None) -> list[Entity]:
        """Сущности рядом с героями: в месте ``place`` или во всех местах, где стоят герои отряда."""
        places = [place] if place else self.scene_places()
        if not places:
            return [e for e in self.entities.values() if e.kind != "location"]
        return [e for e in self.entities.values() if e.kind != "location" and e.location_id in places]

    def fighting_here(self) -> bool:
        """Идёт бой, и он касается группы хода: в очереди инициативы есть кто-то из её места."""
        if self.scene.mode != "combat":
            return False
        if not self.focus or not self.scene.turn_order:
            return True
        mine = set(self.scene_places())
        return any(self.actor_place(x["id"]) in mine for x in self.scene.turn_order)

    def in_fight(self, actor_id: str | None = None) -> bool:
        """Идёт ли бой для героя (или для группы хода, если герой не указан). Бой другой части отряда не в счёт."""
        from app.core.combat import fights

        if self.scene.mode != "combat":
            return False
        if actor_id is None:
            return self.fighting_here()
        return fights(self.scene, self.characters, self.entities, actor_id)

    def home(self) -> str | None:
        """Основное место сцены: место сцены, если там есть герои, иначе первое место, где они стоят."""
        places = self.scene_places()
        if self.scene.location_id in places or not places:
            return self.scene.location_id
        return places[0]

    def place_arg(self, location_id: str | None, what: str = "это") -> str | None:
        """Куда ставить новое в сцене. Пока отряд вместе — место сцены; разделился — нужно назвать место героев."""
        places = self.scene_places()
        if location_id:
            if location_id not in places:
                names = ", ".join(f"{p} {self._place_name(p)}" for p in places) or "нет"
                raise WorldError(f"в месте {location_id} нет героев; места отряда: {names}")
            return location_id
        if len(places) > 1:
            names = ", ".join(f"{p} {self._place_name(p)}" for p in places)
            raise WorldError(f"отряд разделён: укажи location_id — в каком месте {what} ({names})")
        return self.home()

    # --- часы групп: у разошедшегося отряда у каждой части своё время, у кампании — наибольшее из них ---
    # ``scene.state["lag"]`` — на сколько секунд герой отстаёт от часов кампании. Пока отряд вместе, отставания нет.

    def lags(self) -> dict[str, int]:
        return {k: int(v) for k, v in ((self.scene.state or {}).get("lag") or {}).items() if v}

    def _set_lags(self, lag: dict[str, int]) -> None:
        st = {k: v for k, v in (self.scene.state or {}).items() if k != "lag"}
        self.scene.state = {**st, **({"lag": lag} if lag else {})}

    def enter_clock(self) -> int:
        """Ход группы: часы сцены на время ход показывают время этой группы. Возвращает часы кампании до хода."""
        t0 = self.scene.game_time
        if self.crew:
            lag = self.lags()
            self.scene.game_time = t0 - min((lag.get(i, 0) for i in self.crew), default=0)
        return t0

    def settle_clock(self, t0: int) -> None:
        """После хода группы: часы кампании — наибольшие из часов групп; кто позади, копит отставание."""
        if not self.crew:
            return
        lag, mine = self.lags(), self.scene.game_time
        now = max(t0, mine)
        new = {}
        for ch in self.characters.values():
            v = now - mine if ch.id in self.crew else lag.get(ch.id, 0) + now - t0
            if v > 0 and ch.status in PLAYABLE:
                new[ch.id] = v
        self._set_lags(new)
        self.scene.game_time = now

    def catch_up(self) -> list[tuple[list[str], int]]:
        """Части отряда сошлись: отставшие догоняют. Возвращает, кто и на сколько секунд отстал."""
        lag = self.lags()
        if not lag:
            return []
        groups = self.groups()
        out: list[tuple[list[str], int]] = []
        new: dict[str, int] = {}
        for heroes in groups.values():
            least = min(lag.get(h.id, 0) for h in heroes) if len(groups) > 1 else 0
            behind: dict[int, list[str]] = {}
            for h in heroes:
                if lag.get(h.id, 0) > least:
                    behind.setdefault(lag[h.id] - least, []).append(h.name)
                if least:
                    new[h.id] = least
            out += [(names, d) for d, names in behind.items()]
        self._set_lags(new)
        return out

    def _place_name(self, place_id: str | None) -> str:
        e = self.entities.get(place_id or "")
        return e.name if e else "место не задано"

    def valid_ids(self) -> dict[str, list[str]]:
        """Допустимые значения полей на этот ход (раздел 7.1, «динамические схемы»)."""
        chars = [c.id for c in self.characters.values() if c.status in PLAYABLE]
        ents = [e.id for e in self.in_scene_entities()]
        living = [i for i in chars + ents if i in self.characters or self.entities[i].kind == "creature"]
        return {
            "characters": chars,
            "entities": ents,
            "combatants": living,
            "locations": [e.id for e in self.entities.values() if e.kind == "location"],
            "places": self.scene_places(),  # места, где стоят герои
            # о ком можно узнать факт: герои, места и все сущности мира
            "subjects": chars + [e.id for e in self.entities.values()],
            "inventory": [it.id for items in self.inventory.values() for it in items],
            # предметы, лежащие в сцене: их можно подобрать
            "scene_items": [e.id for e in self.in_scene_entities() if is_scene_item(e)],
            # все существа мира, включая ушедших со сцены: за побеждённых без убийства дают опыт
            "creatures": [e.id for e in self.entities.values() if e.kind == "creature"],
        }

    def scene_table(self) -> str:
        """Таблица сцены для мастера: единственный источник чисел в его контексте (раздел 7.1). Разделившийся отряд
        показан по местам: у каждого места свои герои, существа, предметы и области."""
        groups = self.groups()
        apart: dict[str | None, list[Character]] = {}
        if self.focus:  # ход группы: в таблице только её места, остальные — одной строкой
            mine = set(self.scene_places())
            apart = {p: h for p, h in groups.items() if p not in mine}
            groups = {p: h for p, h in groups.items() if p in mine}
        fight = self.fighting_here()
        mode = "бой" if fight else "свободный режим"
        if len(groups) > 1:
            head = f"СЦЕНА: отряд разделён, мест: {len(groups)} · {mode}"
        else:
            loc = self.entities.get(self.scene_places()[0] if self.scene_places() else "")
            head = f"СЦЕНА: {loc.name if loc else 'локация не задана'} · {mode}"
        if fight:
            head += f" · раунд {self.scene.round}"
        lines = [head, f"Игровое время: {format_time(self.scene.game_time)}"]
        shown = [ch for ch in self.characters.values() if ch.status in PLAYABLE or ch.status == "dead"]
        if apart:
            shown = [ch for ch in shown if self.place_of(ch) in groups]
        if len(groups) <= 1:
            lines += self._hero_lines(shown)
            lines += self._place_lines(None)
        else:
            for place, heroes in groups.items():
                lines.append("")
                lines.append(f"МЕСТО {place} {self._place_name(place)}: здесь {', '.join(h.name for h in heroes)}")
                lines += self._hero_lines([ch for ch in shown if self.place_of(ch) == place])
                lines += self._place_lines(place)
            fallen = [ch for ch in shown if ch.status == "dead" and self.place_of(ch) not in groups]
            if fallen:
                lines.append("")
                lines += self._hero_lines(fallen)
            lines.append("")
            lines.append(
                "Отряд разделён: существо, предмет или примету ставь с location_id нужного места; описывай каждому "
                "месту только то, что видят стоящие там герои."
            )
        if apart:
            lines.append(
                "Отряд разделён, этот ход — только для героев выше. Другие части отряда (не описывай их, они услышат "
                "свой ответ отдельно): "
                + "; ".join(f"{', '.join(h.name for h in hs)} — {self._place_name(p)}" for p, hs in apart.items())
            )
        here = set(self.scene_places())
        others = [e for e in self.entities.values() if e.kind == "location" and e.id not in here]
        if others:
            lines.append("Известные локации: " + ", ".join(f"{e.id} {e.name}" for e in others))
        return "\n".join(lines)

    def _hero_lines(self, chars: list[Character]) -> list[str]:
        lines = []
        for ch in chars:
            a = self.actor(ch.id)
            lines.append(f"{a.id}  {a.name} (герой)  {a.status()}  КД {a.ac}{_pos_note(self, a.id)}{_effects_note(a)}")
            items = self.inventory.get(ch.id, [])
            if items:
                inv = ", ".join(
                    f"{it.id} {self.item_name(it)}"
                    + (f" ×{it.qty}" if it.qty > 1 else "")
                    + (" [надет]" if it.equipped else "")
                    for it in items
                )
                lines.append(f"    снаряжение: {inv}")
            magic = self._spell_line(ch)
            if magic:
                lines.append(f"    {magic}")
        return lines

    def _spell_line(self, ch: Character) -> str | None:
        """Что герой может сотворить: без этой строки мастер считает героя немагом и выдумывает эффекты."""
        from app.core.spells import book_view

        try:
            b = book_view(ch.sheet or {}, ch.resources or {}, self.catalog)
        except Exception:  # noqa: BLE001 — сломанный лист не должен ронять таблицу сцены
            return None
        if b is None:
            return None
        ready = [x for x in b["spells"] if x["prepared"]]
        slots = ", ".join(f"{k}-й {v}/{b['slots'][int(k) - 1]}" for k, v in b["slots_left"].items() if v is not None)
        if b.get("pact_slots"):
            slots += f"{', ' if slots else ''}договор {b['pact_level']}-й {b['pact_left']}/{b['pact_slots']}"
        head = f"заклинатель: Сл {b['save_dc']}, атака {b['attack']:+d}, ячейки: {slots or 'нет'}"
        if (b.get("concentration") or {}).get("name"):
            head += f", концентрация: {b['concentration']['name']}"
        spells = "; ".join(
            f"{x['id']} {x['name']} ({'заговор' if x['level'] == 0 else str(x['level']) + '-й'})" for x in ready
        )
        return f"{head}; заклинания (для cast_spell): {spells or 'не выбраны'}"

    def _sketch_line(self, place: str) -> str:
        """Закрытое описание места и эскиз для схемы игроков (app/core/sketch.py) или напоминание описать место."""
        from app.core import sketch

        e = self.entities.get(place)
        st = (e.state or {}) if e is not None else {}
        sk = sketch.of_place(e, self.catalog, self.entities)
        name = e.name if e is not None else place
        layout = str(st.get("layout") or "")
        head = f"{place} «{name}»"
        secret = f"\n  закрытое описание (видишь только ты): {layout[:1500]}" if layout else ""
        if sk is None:
            if layout:
                return f"{head}: эскиз строится по закрытому описанию.{secret}"
            return (
                f"У места {place} «{name}» нет закрытого описания и эскиза: игроки не видят, что вокруг. Опиши его "
                "describe_place — планировка и размер в футах, где вошёл отряд, выходы и что за ними, крупные "
                "предметы, тайное; схема построится по описанию. Или нарисуй её сам sketch_place."
            )
        tag = (
            " (по карте книги)"
            if sk.get("book")
            else " (построен по описанию, поправить — sketch_place)"
            if sk.get("auto")
            else ""
        )
        return f"{head}, {sketch.describe(sk)}{tag}{secret}"

    def _place_lines(self, place: str | None) -> list[str]:
        """Существа, предметы, приметы и области места (``None`` — всех мест, где стоят герои)."""
        lines = [self._sketch_line(p) for p in ([place] if place else self.scene_places()) if p]
        for en in self.in_scene_entities(place):
            if en.kind == "creature":
                try:
                    a = self.actor(en.id)
                except WorldError:
                    continue
                att = (en.state or {}).get("attitude", "hostile")
                lines.append(
                    f"{a.id}  {a.name} [{en.template_id}]  {a.status()}  КД {a.ac}  "
                    f"{ZONE_NAMES.get(en.zone, en.zone)}{_pos_note(self, en.id, zone=False)}  отношение: {att}"
                    f"{_effects_note(a)}"
                )
            elif is_scene_item(en):
                qty = int((en.state or {}).get("qty") or 1)
                lines.append(
                    f"{en.id}  {en.name} (предмет [{en.template_id}]{f' ×{qty}' if qty > 1 else ''}, можно подобрать)  "
                    f"{ZONE_NAMES.get(en.zone, en.zone)}"
                )
            else:
                lines.append(f"{en.id}  {en.name} ({en.kind})  {ZONE_NAMES.get(en.zone, en.zone)}")
        from app.core.positions import active_areas, inside

        for ar in active_areas(self, place):
            data = ar.state["area"]
            who = [
                x.name
                for x in [*self.characters.values(), *self.in_scene_entities(ar.location_id)]
                if (x.id in self.characters and x.status in PLAYABLE) or getattr(x, "kind", "") == "creature"
                if inside(self, ar, x.id)
            ]
            tail = f", до {format_time(data['expires_at'])}" if data.get("expires_at") is not None else ""
            lines.append(
                f"{ar.id}  область «{ar.name}» радиус {data['radius_ft']} фт, {ZONE_NAMES.get(ar.zone, ar.zone)}"
                f"{tail}; внутри: {', '.join(who) or 'никого'}"
            )
        return lines


def party_groups(chars, scene: Scene) -> dict[str | None, list[Character]]:
    """Играбельные герои по местам: своё место героя или место сцены (design/party-split.md)."""
    out: dict[str | None, list[Character]] = {}
    for ch in chars:
        if ch.status in PLAYABLE:
            out.setdefault(ch.location_id or scene.location_id, []).append(ch)
    return out


def viewer_places(chars, scene: Scene, hero: Character | None) -> tuple[str | None, list[str]]:
    """Что из сцены видит зритель: основное место и места, чьё окружение ему показывать. Герой разделившегося отряда
    видит только своё место; мастер и зритель без героя — все места, где стоят герои."""
    groups = party_groups(chars, scene)
    places = [p for p in groups if p]
    if hero is not None and hero.status in PLAYABLE:
        here = hero.location_id or scene.location_id
        return here, [here] if here else []
    if not places:
        return scene.location_id, [scene.location_id] if scene.location_id else []
    return (scene.location_id if scene.location_id in places else places[0]), places


def is_scene_item(e: Entity) -> bool:
    """Предмет, лежащий в сцене (объект с шаблоном предмета): его можно подобрать в инвентарь."""
    return e.kind == "object" and bool((e.state or {}).get("item"))


def _pos_note(w: World, actor_id: str, zone: bool = True) -> str:
    """Позиция для таблицы мастера: только то, что отличается от «в строю, на земле, без укрытия»."""
    from app.core.positions import COVER_NAMES, ELEVATION_NAMES, pos_of, to_master

    p = pos_of(w, actor_id)
    parts = []
    if p.cell is not None:
        c, r = to_master(w, w.actor_place(actor_id), p.cell)
        parts.append(f"клетка ({c}, {r})")
    elif zone and p.zone:
        parts.append(ZONE_NAMES.get(p.zone, p.zone) + " от отряда")
    if p.bearing and p.cell is None:
        parts.append(f"сторона {p.bearing}")
    if p.elevation != "ground":
        parts.append(ELEVATION_NAMES.get(p.elevation, p.elevation))
    if p.cover != "none":
        parts.append(COVER_NAMES.get(p.cover, p.cover))
    return f"  [{', '.join(parts)}]" if parts else ""


def _effects_note(a: Actor) -> str:
    if not a.effects:
        return ""
    return "  [" + ", ".join(rec.name + (f" ×{e.stacks}" if e.stacks > 1 else "") for e, rec in a.effects) + "]"


def format_time(seconds: int) -> str:
    days, rem = divmod(int(seconds), 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    return f"день {days + 1}, {h:02d}:{m:02d}" + (f":{s:02d}" if s else "")


async def get_scene(session: AsyncSession, campaign_id: str) -> Scene:
    scene = await session.get(Scene, campaign_id)
    if scene is None:
        scene = Scene(campaign_id=campaign_id, mode="free", round=0, turn_order=[])
        session.add(scene)
        await session.flush()
    return scene


async def load_world(session: AsyncSession, campaign: Campaign, catalog: CatalogView) -> World:
    chars = (await session.scalars(select(Character).where(Character.campaign_id == campaign.id))).all()
    ents = (await session.scalars(select(Entity).where(Entity.campaign_id == campaign.id))).all()
    ids = [c.id for c in chars]
    inv_rows = (
        (await session.scalars(select(InventoryItem).where(InventoryItem.character_id.in_(ids)))).all() if ids else []
    )
    inventory: dict[str, list[InventoryItem]] = {}
    for it in inv_rows:
        inventory.setdefault(it.character_id, []).append(it)
    effects = list((await session.scalars(select(ActiveEffect).where(ActiveEffect.campaign_id == campaign.id))).all())
    secret = await session.get(CampaignSecret, campaign.id)
    return World(
        campaign=campaign,
        catalog=catalog,
        scene=await get_scene(session, campaign.id),
        characters={c.id: c for c in chars},
        entities={e.id: e for e in ents},
        inventory=inventory,
        effects=effects,
        plot=copy.deepcopy(secret.plot) if secret and secret.plot else {},
    )
