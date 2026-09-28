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
    mods_ = _collect(effs, cat)
    res, vul, imm = mod.defenses(mods_)
    return Actor(
        id=ch.id,
        name=ch.name,
        kind="character",
        obj=ch,
        hp=_hp_from(ch.resources or {}, d.hp_max),
        ac=d.ac + mod.add_value(mods_, "ac"),
        abilities=d.abilities,
        mods=d.mods,
        saves=d.saves,
        skills=d.skills,
        pb=d.pb,
        attacks=[a.as_dict() for a in d.attacks],
        resistances=set(d.resistances) | res,
        vulnerabilities=vul,
        immunities=imm,
        condition_immunities=mod.condition_immunities(mods_),
        effects=effs,
        modifiers=mods_,
        zone="party",
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
    )


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
        if a.kind == "character" and b.kind == "character":
            return 5
        if a.kind == "character":
            return ZONE_FT.get(b.zone, 30)
        if b.kind == "character":
            return ZONE_FT.get(a.zone, 30)
        return 30

    def in_scene_entities(self) -> list[Entity]:
        loc = self.scene.location_id
        return [e for e in self.entities.values() if e.kind != "location" and (loc is None or e.location_id == loc)]

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
            "inventory": [it.id for items in self.inventory.values() for it in items],
        }

    def scene_table(self) -> str:
        """Таблица сцены для мастера: единственный источник чисел в его контексте (раздел 7.1)."""
        loc = self.entities.get(self.scene.location_id or "")
        mode = "бой" if self.scene.mode == "combat" else "свободный режим"
        head = f"СЦЕНА: {loc.name if loc else 'локация не задана'} · {mode}"
        if self.scene.mode == "combat":
            head += f" · раунд {self.scene.round}"
        lines = [head, f"Игровое время: {format_time(self.scene.game_time)}"]
        for ch in self.characters.values():
            if ch.status not in PLAYABLE and ch.status != "dead":
                continue
            a = self.actor(ch.id)
            lines.append(f"{a.id}  {a.name} (герой)  {a.status()}  КД {a.ac}{_effects_note(a)}")
            items = self.inventory.get(ch.id, [])
            if items:
                inv = ", ".join(
                    f"{it.id} {self.item_name(it)}"
                    + (f" ×{it.qty}" if it.qty > 1 else "")
                    + (" [надет]" if it.equipped else "")
                    for it in items
                )
                lines.append(f"    снаряжение: {inv}")
        for en in self.in_scene_entities():
            if en.kind == "creature":
                try:
                    a = self.actor(en.id)
                except WorldError:
                    continue
                att = (en.state or {}).get("attitude", "hostile")
                lines.append(
                    f"{a.id}  {a.name} [{en.template_id}]  {a.status()}  КД {a.ac}  "
                    f"{ZONE_NAMES.get(en.zone, en.zone)}  отношение: {att}{_effects_note(a)}"
                )
            else:
                lines.append(f"{en.id}  {en.name} ({en.kind})  {ZONE_NAMES.get(en.zone, en.zone)}")
        others = [e for e in self.entities.values() if e.kind == "location" and e.id != self.scene.location_id]
        if others:
            lines.append("Известные локации: " + ", ".join(f"{e.id} {e.name}" for e in others))
        return "\n".join(lines)


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
