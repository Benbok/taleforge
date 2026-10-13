"""Каталог и подробное описание игровых миров и наборов правил.

Каждый мир в Taleforge — это пакет контента (ContentPack) со своим паспортом (pack.yaml),
лор-фактами, фракциями, опорными локациями, происхождениями, классами, шкалами и бестиарием.
Система полностью динамическая: при добавлении любого нового пакета в content/ или импорте через БД,
он автоматически появляется в каталоге и получает собственную страницу детализации.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import BASE_PACK_ID, BASE_RULES
from app.content.manifest import version_tuple
from app.content.yaml_io import load_file
from app.core.campaigns import NotFound
from app.db.models import ContentPack, ContentRecord

DEFAULT_WORLD_CATEGORIES: dict[str, str] = {
    "echo-leviathans": "ОСНОВНОЙ СЕТТИНГ · БИОПАНК / ДИЗЕЛЬПАНК",
    "dnd5e-srd": "КЛАССИЧЕСКИЙ НАБОР ПРАВИЛ",
}

DEFAULT_WORLD_SUMMARIES: dict[str, str] = {
    "echo-leviathans": (
        "Мир титанов, павших сорок лет назад. Люди живут на остывающих телах гигантов, "
        "добывая ликвор и сражаясь с выводками Резонанса на Пепельной черте."
    ),
    "dnd5e-srd": (
        "Базовые правила классического фэнтези от Wizards of the Coast (CC BY 4.0). "
        "Подходит для кастомных приключений в традиционном сеттинге меча и магии."
    ),
}

DEFAULT_WORLD_DESCRIPTIONS: dict[str, str] = {
    "echo-leviathans": (
        "Сорок лет назад титаны пали с небес. На их гигантских остывающих телах человечество построило новую "
        "суровую цивилизацию: в позвоночных каналах гремят печи и фабрики, по жилам текут цистерны с ликвором, "
        "а на границах Пепельного кордона защитники сдерживают натиск чудовищ Резонанса. В этом мире плоть туш и "
        "механизмы сплелись воедино, а любая сила требует платы — Скверной или Переменой."
    ),
    "dnd5e-srd": (
        "Системный справочный документ D&D 5.1 (System Reference Document) от Wizards of the Coast под лицензией "
        "CC BY 4.0. "
        "Включает 12 базовых классов, 9 классических рас, сотни монстров, полный гримуар заклинаний, правила боевой "
        "системы "
        "и снаряжение для классических героических приключений."
    ),
}

DEFAULT_WORLD_BADGES: dict[str, list[str]] = {
    "echo-leviathans": [
        "Шкалы: Скверна и Перемена",
        "Уровни: 1–15",
        "Система: SRD 5.1 Hack",
    ],
    "dnd5e-srd": [
        "12 базовых классов",
        "Свободный бестиарий",
        "Уровни: 1–20",
        "Система: D&D 5e SRD",
    ],
}

DEFAULT_STATUS_BADGES: dict[str, str] = {
    "echo-leviathans": "АКТИВЕН В СИСТЕМЕ",
    "dnd5e-srd": "БАЗОВЫЙ ПАКЕТ",
}

TOPIC_TITLES: dict[str, str] = {
    "cosmology": "Космология и основы мира",
    "leviathans": "Левиафаны и туши",
    "history": "История и падение титанов",
    "now": "Современность и эпоха добычи",
    "war": "Война и Пепельная черта",
    "cordon": "Пепельный Кордон",
    "geography": "География и рубежи",
    "factions": "Фракции и Дома",
    "church": "Церковь Исполинов",
    "guild": "Гильдия Диагностов",
    "economy": "Экономика и субстанции",
    "mines": "Шахты и добыча",
    "daily_life": "Повседневная жизнь и быт",
    "politics": "Политика и синдикаты",
    "magic": "Магия и препараты",
    "echo": "Эхо и техники",
    "echolite": "Эхолит",
    "resonance": "Резонанс",
    "brood": "Выводки и порождения",
    "parasites": "Паразиты туш",
    "technology": "Технологии и механизмы",
    "nomenclature": "Номенклатура",
}


class WorldSummary(BaseModel):
    id: str
    name: str
    version: str
    category: str
    summary: str
    description: str
    ruleset: str
    ruleset_base: str | None = None
    level_cap: int = 20
    license: str | None = None
    badges: list[str] = Field(default_factory=list)
    status_badge: str
    is_base: bool = False
    counts: dict[str, int] = Field(default_factory=dict)


class LoreFactItem(BaseModel):
    id: str
    name: str
    text: str
    tags: list[str] = Field(default_factory=list)
    doc: str | None = None


class LoreTopicGroup(BaseModel):
    topic: str
    title: str
    facts: list[LoreFactItem]


class FactionItem(BaseModel):
    id: str
    name: str
    description: str
    goal: str | None = None
    resources: list[str] = Field(default_factory=list)
    seat_ref: str | None = None
    leader_ref: str | None = None
    relations: list[dict[str, Any]] = Field(default_factory=list)


class LocationDistrict(BaseModel):
    name: str
    text: str | None = None


class LocationItem(BaseModel):
    id: str
    name: str
    description: str
    location_type: str | None = None
    population: int | None = None
    ruler: str | None = None
    belt: str | None = None
    districts: list[LocationDistrict] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


ABILITY_DATIVE_RU: dict[str, str] = {
    "str": "Силе",
    "dex": "Ловкости",
    "con": "Телосложению",
    "int": "Интеллекту",
    "wis": "Мудрости",
    "cha": "Харизме",
}

SIZE_RU: dict[str, str] = {
    "tiny": "Крошечный",
    "small": "Маленький",
    "medium": "Средний",
    "large": "Большой",
    "huge": "Огромный",
    "gargantuan": "Громадный",
}

SRD_FEATURE_TRANSLATIONS: dict[str, dict[str, str]] = {
    "darkvision": {
        "name": "Тёмное зрение",
        "description": "Вы превосходно видите в темноте и при тусклом освещении в пределах 60 футов.",
    },
    "dwarven_resilience": {
        "name": "Дварфийская стойкость",
        "description": "Преимущество на спасброски против яда и сопротивление урону ядом.",
    },
    "stonecunning": {
        "name": "Знание камня",
        "description": "Удвоенный бонус мастерства к проверкам Истории о каменной кладке и изделиях из камня.",
    },
    "dwarven_combat_training": {
        "name": "Дварфийская боевая подготовка",
        "description": "Владение боевым топором, ручным топором, лёгким молотом и боевым молотом.",
    },
    "tool_proficiency": {
        "name": "Владение инструментами",
        "description": "Владение ремесленными инструментами на выбор: кузнечными, пивовара или каменщика.",
    },
    "dwarven_toughness": {
        "name": "Дварфийская выдержка",
        "description": "Максимум хитов увеличивается на 1 и ещё на 1 за каждый новый уровень.",
    },
    "fey_ancestry": {
        "name": "Наследие фей",
        "description": "Преимущество на спасброски против очарования, магия не может усыпить вас.",
    },
    "trance": {
        "name": "Транс",
        "description": "Медитация 4 часа в сутки вместо сна с получением всех преимуществ 8-часового отдыха.",
    },
    "keen_senses": {
        "name": "Острые чувства",
        "description": "Владение навыком Внимательность.",
    },
    "elf_weapon_training": {
        "name": "Эльфийская боевая подготовка",
        "description": "Владение длинным мечом, коротким мечом, коротким луком и длинным луком.",
    },
    "high_elf_cantrip": {
        "name": "Заговор высшего эльфа",
        "description": "Один заговор волшебника на выбор; базовая характеристика — Интеллект.",
    },
    "extra_language": {
        "name": "Дополнительный язык",
        "description": "Один дополнительный язык на ваш выбор.",
    },
    "brave": {
        "name": "Храбрость",
        "description": "Преимущество на спасброски против состояния испуга.",
    },
    "halfling_nimbleness": {
        "name": "Проворство полурослика",
        "description": "Вы можете перемещаться сквозь пространство любого существа крупнее вас.",
    },
    "lucky": {
        "name": "Везучесть",
        "description": (
            "При выпадении 1 на d20 (атака, проверка характеристики или спасбросок) можно перебросить кость."
        ),
    },
    "naturally_stealthy": {
        "name": "Естественная скрытность",
        "description": (
            "Вы можете попытаться спрятаться даже за существом, которое хотя бы на один размер крупнее вас."
        ),
    },
    "draconic_ancestry": {
        "name": "Драконье происхождение",
        "description": "Вид дракона определяет тип урона, область выдоха и сопротивление урону.",
    },
    "breath_weapon": {
        "name": "Оружие дыхания",
        "description": (
            "Выдох разрушительной энергии (урон 2d6, рост с уровнем; перезарядка после короткого или продолжительного "
            "отдыха)."
        ),
    },
    "damage_resistance": {
        "name": "Сопротивление урону",
        "description": "Сопротивление типу урона, связанному с вашим драконьим предком.",
    },
    "gnome_cunning": {
        "name": "Гномья хитрость",
        "description": "Преимущество на спасброски Интеллекта, Мудрости и Харизмы против магии.",
    },
    "artificers_lore": {
        "name": "Знания ремесленника",
        "description": (
            "Удвоенный бонус мастерства к проверкам Истории о магических, алхимических или механических предметах."
        ),
    },
    "tinker": {
        "name": "Жестянщик",
        "description": "Создание крошечных заводных механизмов (игрушка, зажигалка, музыкальная шкатулка).",
    },
    "skill_versatility": {
        "name": "Универсальность навыков",
        "description": "Владение двумя любыми навыками на ваш выбор.",
    },
    "savage_attacks": {
        "name": "Свирепые атаки",
        "description": "При критическом попадании рукопашным оружием добавляется одна дополнительная кость урона.",
    },
    "relentless_endurance": {
        "name": "Непоколебимая стойкость",
        "description": "Раз в продолжительный отдых при падении хитов до 0 вы можете остаться с 1 хитом вместо этого.",
    },
    "menacing": {
        "name": "Угрожающий вид",
        "description": "Владение навыком Запугивание.",
    },
    "hellish_resistance": {
        "name": "Адское сопротивление",
        "description": "Сопротивление урону огнём.",
    },
    "infernal_legacy": {
        "name": "Адское наследие",
        "description": (
            "Заговор «Чудотворство», с 3-го уровня «Адское возмездие» 2-го круга, с 5-го уровня «Тьма». "
            "Базовая характеристика — Харизма."
        ),
    },
}

ENGLISH_FEATURE_NAMES_TO_KEYS: dict[str, str] = {
    "darkvision": "darkvision",
    "dwarven resilience": "dwarven_resilience",
    "stonecunning": "stonecunning",
    "dwarven combat training": "dwarven_combat_training",
    "tool proficiency": "tool_proficiency",
    "dwarven toughness": "dwarven_toughness",
    "fey ancestry": "fey_ancestry",
    "trance": "trance",
    "keen senses": "keen_senses",
    "elf weapon training": "elf_weapon_training",
    "high elf cantrip": "high_elf_cantrip",
    "extra language": "extra_language",
    "brave": "brave",
    "halfling nimbleness": "halfling_nimbleness",
    "lucky": "lucky",
    "naturally stealthy": "naturally_stealthy",
    "draconic ancestry": "draconic_ancestry",
    "breath weapon": "breath_weapon",
    "damage resistance": "damage_resistance",
    "gnome cunning": "gnome_cunning",
    "artificer's lore": "artificers_lore",
    "tinker": "tinker",
    "skill versatility": "skill_versatility",
    "savage attacks": "savage_attacks",
    "relentless endurance": "relentless_endurance",
    "menacing": "menacing",
    "hellish resistance": "hellish_resistance",
    "infernal legacy": "infernal_legacy",
}


def _format_ability_bonuses(raw_bonuses: Any, ability_choose: Any = None) -> str:
    parts: list[str] = []

    if isinstance(raw_bonuses, dict):
        if len(raw_bonuses) == 6 and all(v == 1 for v in raw_bonuses.values()):
            parts.append("+1 ко всем характеристикам")
        else:
            for k, v in sorted(raw_bonuses.items(), key=lambda item: (-item[1], item[0])):
                ab_name = ABILITY_DATIVE_RU.get(k.lower(), k.upper())
                sign = f"+{v}" if v > 0 else str(v)
                parts.append(f"{sign} к {ab_name}")
    elif isinstance(raw_bonuses, list):
        for b in raw_bonuses:
            if not isinstance(b, dict):
                continue
            if "ability" in b:
                k = str(b["ability"]).lower()
                v = b.get("value", 1)
                ab_name = ABILITY_DATIVE_RU.get(k, k.upper())
                sign = f"+{v}" if v > 0 else str(v)
                parts.append(f"{sign} к {ab_name}")
            elif "choose" in b:
                cnt = b["choose"]
                val = b.get("value", 1)
                sign = f"+{val}" if val > 0 else str(val)
                fr = b.get("from")
                if fr == "any" or not fr:
                    if cnt == 1:
                        suffix = "другой на выбор" if b.get("distinct_from_fixed") else "характеристике на выбор"
                        parts.append(f"{sign} к любой {suffix}")
                    elif cnt in (2, 3, 4):
                        cnt_str = {2: "двум", 3: "трем", 4: "четырем"}.get(cnt, str(cnt))
                        distinct = "разным " if b.get("distinct") else ""
                        parts.append(f"{sign} к {cnt_str} {distinct}характеристикам на выбор")
                elif isinstance(fr, list):
                    options = " или ".join(ABILITY_DATIVE_RU.get(str(x).lower(), str(x).upper()) for x in fr)
                    suffix = " на выбор"
                    parts.append(f"{sign} к {options}{suffix}")

    if isinstance(ability_choose, dict):
        cnt = ability_choose.get("count", 1)
        val = ability_choose.get("bonus", 1)
        sign = f"+{val}" if val > 0 else str(val)
        cnt_str = {1: "одной", 2: "двум", 3: "трем"}.get(cnt, str(cnt))
        parts.append(f"{sign} к {cnt_str} другим характеристикам на выбор")

    return ", ".join(parts)


def _format_size(size: str | None) -> str | None:
    if not size:
        return None
    return SIZE_RU.get(size.lower(), size)


def _format_speed(speed: int | None) -> str | None:
    if speed is None:
        return None
    meters = round(speed * 0.3, 1)
    if meters.is_integer():
        m_str = f"{int(meters)} м"
    else:
        m_str = f"{meters} м"
    return f"{speed} футов ({m_str})"


def _translate_origin_feature(feat: dict[str, Any]) -> dict[str, Any]:
    key = str(feat.get("key") or "").lower()
    name = str(feat.get("name") or "").strip()

    trans_entry = None
    if key in SRD_FEATURE_TRANSLATIONS:
        trans_entry = SRD_FEATURE_TRANSLATIONS[key]
    elif name.lower() in ENGLISH_FEATURE_NAMES_TO_KEYS:
        k = ENGLISH_FEATURE_NAMES_TO_KEYS[name.lower()]
        trans_entry = SRD_FEATURE_TRANSLATIONS.get(k)

    if trans_entry:
        return {
            **feat,
            "name": trans_entry["name"],
            "description": trans_entry["description"],
        }
    return feat


class OriginItem(BaseModel):
    id: str
    name: str
    epithet: str | None = None
    badge: str | None = None
    summary: str | None = None
    description: str
    ability_bonuses: list[dict[str, Any]] = Field(default_factory=list)
    formatted_bonuses: str | None = None
    highlights: list[str] = Field(default_factory=list)
    features: list[dict[str, Any]] = Field(default_factory=list)
    speed: int | None = None
    speed_display: str | None = None
    size: str | None = None
    size_display: str | None = None


class ClassItem(BaseModel):
    id: str
    name: str
    epithet: str | None = None
    badge: str | None = None
    summary: str | None = None
    description: str
    hit_die: str | None = None
    spell_source: str | None = None
    world_role: str | None = None
    highlights: list[str] = Field(default_factory=list)
    subclasses: list[dict[str, str]] = Field(default_factory=list)


class ScaleItem(BaseModel):
    id: str
    name: str
    description: str
    widget_type: str | None = None
    min: int | None = None
    max: int | None = None
    tags: list[str] = Field(default_factory=list)


class ClockItem(BaseModel):
    id: str
    name: str
    description: str
    scope: str | None = None
    min: int = 0
    max: int = 6
    moves_up: list[str] = Field(default_factory=list)
    moves_down: list[str] = Field(default_factory=list)
    thresholds: list[dict[str, Any]] = Field(default_factory=list)


class CreatureItem(BaseModel):
    id: str
    name: str
    description: str | None = None
    cr: str | float | int | None = None
    kind: str | None = None
    tags: list[str] = Field(default_factory=list)


class WorldDetail(BaseModel):
    id: str
    name: str
    version: str
    category: str
    summary: str
    description: str
    ruleset: str
    ruleset_base: str | None = None
    level_cap: int = 20
    license: str | None = None
    badges: list[str] = Field(default_factory=list)
    status_badge: str
    is_base: bool = False
    counts: dict[str, int] = Field(default_factory=dict)
    lore_topics: list[LoreTopicGroup] = Field(default_factory=list)
    factions: list[FactionItem] = Field(default_factory=list)
    locations: list[LocationItem] = Field(default_factory=list)
    origins: list[OriginItem] = Field(default_factory=list)
    classes: list[ClassItem] = Field(default_factory=list)
    scales: list[ScaleItem] = Field(default_factory=list)
    clocks: list[ClockItem] = Field(default_factory=list)
    bestiary: list[CreatureItem] = Field(default_factory=list)


CONTENT_DIR = Path(__file__).resolve().parents[2] / "content"


def _is_base_pack(pack_id: str, manifest: dict[str, Any]) -> bool:
    return pack_id == BASE_PACK_ID or manifest.get("provides") == BASE_RULES


def _world_category(pack_id: str, manifest: dict[str, Any]) -> str:
    if manifest.get("category"):
        return str(manifest["category"])
    if pack_id in DEFAULT_WORLD_CATEGORIES:
        return DEFAULT_WORLD_CATEGORIES[pack_id]
    if _is_base_pack(pack_id, manifest):
        return "КЛАССИЧЕСКИЙ НАБОР ПРАВИЛ"
    return "СЕТТИНГ"


def _world_summary(pack_id: str, manifest: dict[str, Any]) -> str:
    if manifest.get("summary"):
        return str(manifest["summary"])
    if pack_id in DEFAULT_WORLD_SUMMARIES:
        return DEFAULT_WORLD_SUMMARIES[pack_id]
    if manifest.get("description"):
        return str(manifest["description"]).split(".")[0] + "."
    return "Пакет правил и игрового контента."


def _world_description(pack_id: str, manifest: dict[str, Any]) -> str:
    if manifest.get("description"):
        return str(manifest["description"])
    if pack_id in DEFAULT_WORLD_DESCRIPTIONS:
        return DEFAULT_WORLD_DESCRIPTIONS[pack_id]
    return _world_summary(pack_id, manifest)


def _world_badges(pack_id: str, manifest: dict[str, Any], counts: dict[str, int]) -> list[str]:
    if manifest.get("badges"):
        return [str(b) for b in manifest["badges"]]
    if pack_id in DEFAULT_WORLD_BADGES:
        return list(DEFAULT_WORLD_BADGES[pack_id])
    badges = []
    lvl = manifest.get("level_cap")
    if lvl:
        badges.append(f"Уровни: 1–{lvl}")
    if counts.get("class"):
        badges.append(f"{counts['class']} классов")
    if counts.get("origin"):
        badges.append(f"{counts['origin']} происхождений")
    ruleset = manifest.get("ruleset", "dnd5e")
    base = manifest.get("ruleset_base")
    badges.append(f"Система: {base or ruleset}")
    return badges


def _world_status_badge(pack_id: str, manifest: dict[str, Any]) -> str:
    if manifest.get("status_badge"):
        return str(manifest["status_badge"])
    if pack_id in DEFAULT_STATUS_BADGES:
        return DEFAULT_STATUS_BADGES[pack_id]
    if _is_base_pack(pack_id, manifest):
        return "БАЗОВЫЙ ПАКЕТ"
    return "АКТИВЕН В СИСТЕМЕ"


async def list_worlds(session: AsyncSession) -> list[WorldSummary]:
    """Возвращает список всех зарегистрированных миров и наборов правил."""
    db_packs = (await session.scalars(select(ContentPack))).all()
    latest_by_id: dict[str, ContentPack] = {}

    for p in db_packs:
        # Модули приключений не являются отдельными мирами
        if (p.manifest or {}).get("kind") == "module":
            continue
        if p.id not in latest_by_id or version_tuple(p.version) > version_tuple(latest_by_id[p.id].version):
            latest_by_id[p.id] = p

    # Если в базе данных ещё нет пакетов (например, свежая БД без импорта), читаем с диска
    if not latest_by_id and CONTENT_DIR.exists():
        for d in CONTENT_DIR.iterdir():
            p_yaml = d / "pack.yaml"
            if d.is_dir() and p_yaml.is_file():
                try:
                    data = load_file(p_yaml)
                    pid = data.get("id", d.name)
                    latest_by_id[pid] = ContentPack(
                        id=pid,
                        version=data.get("version", "1.0.0"),
                        name=data.get("name", pid),
                        manifest=data,
                        checksum="",
                        import_report={},
                    )
                except Exception:
                    pass

    summaries: list[WorldSummary] = []
    for pid, pack in latest_by_id.items():
        manifest = pack.manifest or {}
        counts = (pack.import_report or {}).get("counts", {})
        if not counts:
            # Считаем из записей БД, если отчет пуст
            recs = (
                await session.scalars(
                    select(ContentRecord.kind).where(
                        ContentRecord.pack_id == pid, ContentRecord.pack_version == pack.version
                    )
                )
            ).all()
            for k in recs:
                counts[k] = counts.get(k, 0) + 1

        is_base = _is_base_pack(pid, manifest)
        summaries.append(
            WorldSummary(
                id=pid,
                name=pack.name,
                version=pack.version,
                category=_world_category(pid, manifest),
                summary=_world_summary(pid, manifest),
                description=_world_description(pid, manifest),
                ruleset=manifest.get("ruleset", "dnd5e"),
                ruleset_base=manifest.get("ruleset_base"),
                level_cap=int(manifest.get("level_cap", 20)),
                license=manifest.get("license"),
                badges=_world_badges(pid, manifest, counts),
                status_badge=_world_status_badge(pid, manifest),
                is_base=is_base,
                counts=counts,
            )
        )

    # Приоритет сортировки: основной сеттинг (echo-leviathans) -> другие сеттинги -> базовый пакет (srd) в конце
    def _sort_key(w: WorldSummary) -> tuple[int, str]:
        if w.id == "echo-leviathans":
            return (0, w.name)
        if not w.is_base:
            return (1, w.name)
        return (2, w.name)

    return sorted(summaries, key=_sort_key)


async def get_world_detail(session: AsyncSession, world_id: str) -> WorldDetail:
    """Возвращает полную детализацию мира: лор, фракции, локации, происхождения, классы, шкалы, бестиарий."""
    # Ищем последнюю версию пакета в БД
    rows = (await session.scalars(select(ContentPack).where(ContentPack.id == world_id))).all()
    pack: ContentPack | None = None
    if rows:
        pack = max(rows, key=lambda p: version_tuple(p.version))
    else:
        # Проверяем файловую систему
        p_dir = CONTENT_DIR / world_id
        p_yaml = p_dir / "pack.yaml"
        if p_yaml.is_file():
            data = load_file(p_yaml)
            pack = ContentPack(
                id=world_id,
                version=data.get("version", "1.0.0"),
                name=data.get("name", world_id),
                manifest=data,
                checksum="",
                import_report={},
            )

    if pack is None:
        raise NotFound(f"мир «{world_id}» не найден")

    manifest = pack.manifest or {}
    counts: dict[str, int] = dict((pack.import_report or {}).get("counts", {}))

    # Загружаем записи из БД
    records = (
        await session.scalars(
            select(ContentRecord).where(ContentRecord.pack_id == world_id, ContentRecord.pack_version == pack.version)
        )
    ).all()

    by_kind: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        by_kind.setdefault(r.kind, []).append(r.data)
        counts[r.kind] = counts.get(r.kind, 0) + 1

    if not records and (CONTENT_DIR / world_id / "data").is_dir():
        for yfile in (CONTENT_DIR / world_id / "data").glob("*.yaml"):
            try:
                ydata = load_file(yfile)
                k = ydata.get("kind")
                if k and "items" in ydata:
                    for item in ydata["items"]:
                        by_kind.setdefault(k, []).append(item)
                        counts[k] = counts.get(k, 0) + 1
            except Exception:
                pass

    # Лор-факты (исключаем закрытые тайны мастера knowledge: hidden)
    raw_lore = by_kind.get("lore_fact", [])
    topics_map: dict[str, list[LoreFactItem]] = {}
    for lf in raw_lore:
        if lf.get("knowledge") == "hidden":
            continue
        topic = lf.get("topic") or "general"
        topics_map.setdefault(topic, []).append(
            LoreFactItem(
                id=lf.get("id", ""),
                name=lf.get("name", "Факт"),
                text=lf.get("text", ""),
                tags=lf.get("tags") or [],
                doc=lf.get("doc"),
            )
        )

    lore_topics: list[LoreTopicGroup] = []
    for topic_key, facts in topics_map.items():
        title = TOPIC_TITLES.get(topic_key, topic_key.replace("_", " ").capitalize())
        lore_topics.append(LoreTopicGroup(topic=topic_key, title=title, facts=facts))

    # Сортируем темы: cosmology и leviathans первыми, прочие по названию
    def _topic_sort(t: LoreTopicGroup) -> int:
        keys = list(TOPIC_TITLES.keys())
        return keys.index(t.topic) if t.topic in keys else 999

    lore_topics.sort(key=_topic_sort)

    # Фракции
    factions: list[FactionItem] = []
    for f in by_kind.get("faction", []):
        factions.append(
            FactionItem(
                id=f.get("id", ""),
                name=f.get("name", ""),
                description=f.get("description", ""),
                goal=f.get("goal"),
                resources=f.get("resources") or [],
                seat_ref=f.get("seat_ref"),
                leader_ref=f.get("leader_ref"),
                relations=f.get("relations") or [],
            )
        )

    # Локации (опорные города, великие туши, ключевые регионы)
    locations: list[LocationItem] = []
    for loc in by_kind.get("location_template", []):
        l_type = loc.get("location_type")
        tags = loc.get("tags") or []
        is_key = (
            l_type in ("hulk", "city", "settlement", "belt", "landmark")
            or "atlas" in tags
            or bool(loc.get("districts"))
        )
        if is_key or len(locations) < 20:
            districts = [
                LocationDistrict(name=d.get("name", ""), text=d.get("text")) for d in loc.get("districts") or []
            ]
            locations.append(
                LocationItem(
                    id=loc.get("id", ""),
                    name=loc.get("name", ""),
                    description=loc.get("description", ""),
                    location_type=l_type,
                    population=loc.get("population"),
                    ruler=loc.get("ruler"),
                    belt=loc.get("belt"),
                    districts=districts,
                    tags=tags,
                )
            )

    # Происхождения / расы
    origins: list[OriginItem] = []
    for o in by_kind.get("origin", []):
        raw_b = o.get("ability_bonuses") or o.get("ability_score_increase") or []
        if isinstance(raw_b, dict):
            b_list = [{"ability": k, "value": v} for k, v in raw_b.items()]
        elif isinstance(raw_b, list):
            b_list = raw_b
        else:
            b_list = []
        raw_f = o.get("features") or o.get("traits") or []
        translated_features = [_translate_origin_feature(f) for f in raw_f]

        speed = o.get("speed")
        size = o.get("size")
        ability_choose = o.get("ability_choose")
        formatted_b = _format_ability_bonuses(raw_b, ability_choose)
        speed_disp = _format_speed(speed)
        size_disp = _format_size(size)
        highlights = o.get("highlights") or []

        origins.append(
            OriginItem(
                id=o.get("id", ""),
                name=o.get("name", ""),
                epithet=o.get("epithet"),
                badge=o.get("badge"),
                summary=o.get("summary"),
                description=o.get("description", ""),
                ability_bonuses=b_list,
                formatted_bonuses=formatted_b,
                highlights=highlights,
                features=translated_features,
                speed=speed,
                speed_display=speed_disp,
                size=size,
                size_display=size_disp,
            )
        )

    # Подклассы для связывания
    subclasses_by_parent: dict[str, list[dict[str, str]]] = {}
    for sub in by_kind.get("subclass", []):
        c_ref = sub.get("class_ref")
        if c_ref:
            subclasses_by_parent.setdefault(c_ref, []).append(
                {"id": sub.get("id", ""), "name": sub.get("name", ""), "summary": sub.get("summary", "")}
            )

    # Классы
    classes: list[ClassItem] = []
    for c in by_kind.get("class", []):
        cid = c.get("id", "")
        scs = subclasses_by_parent.get(cid, [])
        classes.append(
            ClassItem(
                id=cid,
                name=c.get("name", ""),
                epithet=c.get("epithet"),
                badge=c.get("badge"),
                summary=c.get("summary"),
                description=c.get("description", ""),
                hit_die=str(c.get("hit_die", "")),
                spell_source=c.get("spell_source"),
                world_role=c.get("world_role"),
                highlights=c.get("highlights") or [],
                subclasses=scs,
            )
        )

    # Шкалы и характеристики мира (Скверна, Перемена, ресурсы)
    scales: list[ScaleItem] = []
    for st in by_kind.get("stat_definition", []):
        tags = set(st.get("tags") or [])
        # Интересны уникальные шкалы сеттинга
        if tags & {"corruption", "alteration", "echo", "resource", "derived"}:
            scales.append(
                ScaleItem(
                    id=st.get("id", ""),
                    name=st.get("name", ""),
                    description=st.get("description", ""),
                    widget_type=st.get("widget_type"),
                    min=st.get("min"),
                    max=st.get("max"),
                    tags=list(tags),
                )
            )

    # Часы мира (Резонанс, Пробуждение туш, Цветение)
    clocks: list[ClockItem] = []
    for cl in by_kind.get("clock", []):
        moves = cl.get("moves") or {}
        clocks.append(
            ClockItem(
                id=cl.get("id", ""),
                name=cl.get("name", ""),
                description=cl.get("description", ""),
                scope=cl.get("scope"),
                min=cl.get("min", 0),
                max=cl.get("max", 6),
                moves_up=moves.get("up") or [],
                moves_down=moves.get("down") or [],
                thresholds=cl.get("thresholds") or [],
            )
        )

    # Выборка характерных существ бестиария (до 20 образцов)
    bestiary: list[CreatureItem] = []
    for cr in by_kind.get("creature_template", [])[:20]:
        bestiary.append(
            CreatureItem(
                id=cr.get("id", ""),
                name=cr.get("name", ""),
                description=cr.get("description"),
                cr=cr.get("challenge_rating") or cr.get("cr"),
                kind=cr.get("creature_type") or cr.get("type"),
                tags=cr.get("tags") or [],
            )
        )

    is_base = _is_base_pack(world_id, manifest)

    return WorldDetail(
        id=world_id,
        name=pack.name,
        version=pack.version,
        category=_world_category(world_id, manifest),
        summary=_world_summary(world_id, manifest),
        description=_world_description(world_id, manifest),
        ruleset=manifest.get("ruleset", "dnd5e"),
        ruleset_base=manifest.get("ruleset_base"),
        level_cap=int(manifest.get("level_cap", 20)),
        license=manifest.get("license"),
        badges=_world_badges(world_id, manifest, counts),
        status_badge=_world_status_badge(world_id, manifest),
        is_base=is_base,
        counts=counts,
        lore_topics=lore_topics,
        factions=factions,
        locations=locations,
        origins=origins,
        classes=classes,
        scales=scales,
        clocks=clocks,
        bestiary=bestiary,
    )
