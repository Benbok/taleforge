"""Детерминированные механические правила наполнения мира.

Никаких вызовов LLM, автозапуска при просмотре карты, парсинга названий и
необратимой перегенерации. Контент берётся только из CatalogView кампании.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from app.content.catalog import CatalogView, Entry

GENERATOR_VERSION = "world-loot-v1"
_ALLOWED_CATEGORIES = frozenset({"gear", "tool", "weapon", "armor", "ammo", "consumable", "trade_good"})
_COIN_COPPER = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}


@dataclass(frozen=True)
class LocationProfile:
    """Кураторские архетипы: не меняют свойства item_template."""

    containers: tuple[tuple[str, str], ...]
    item_ids: tuple[str, ...]
    budget_cp: int
    floor_items: int
    container_items: int


PROFILES: dict[str, LocationProfile] = {
    "таверна": LocationProfile(
        (("Шкаф припасов", "item:container"), ("Ящик под стойкой", "item:container"), ("Сундук хозяина", "item:chest")),
        ("item.rations", "item.waterskin", "item.torch", "item.club", "item.rope_hempen"),
        600,
        1,
        2,
    ),
    "дом": LocationProfile(
        (("Домашний сундук", "item:chest"), ("Платяной шкаф", "item:container"), ("Ящик в кладовой", "item:container")),
        ("item.bedroll", "item.rations", "item.waterskin", "item.torch", "item.backpack"),
        700,
        1,
        2,
    ),
    "склад": LocationProfile(
        (("Товарный ящик", "item:container"), ("Большой сундук", "item:chest"), ("Закрытый ларь", "item:chest")),
        ("item.rope_hempen", "item.torch", "item.rations", "item.backpack", "item.crowbar"),
        900,
        1,
        2,
    ),
    "лаборатория": LocationProfile(
        (
            ("Шкаф реактивов", "item:container"),
            ("Запертый ящик", "item:chest"),
            ("Стол с отделениями", "item:container"),
        ),
        ("item.potion_of_healing", "item.healers_kit", "item.torch", "item.waterskin"),
        5500,
        1,
        1,
    ),
    "склеп": LocationProfile(
        (
            ("Погребальный ларец", "item:chest"),
            ("Каменный саркофаг", "item:container"),
            ("Ниша с крышкой", "item:container"),
        ),
        ("item.torch", "item.dagger", "item.club", "item.rope_hempen"),
        500,
        1,
        1,
    ),
    "пещера": LocationProfile(
        (
            ("Потерянный ранец", "item:container"),
            ("Ящик экспедиции", "item:container"),
            ("Старый тайник", "item:chest"),
        ),
        ("item.torch", "item.rope_hempen", "item.rations", "item.bedroll", "item.waterskin"),
        600,
        1,
        1,
    ),
    "мастерская": LocationProfile(
        (("Ящик инструментов", "item:container"), ("Шкаф мастера", "item:container"), ("Сундук заказов", "item:chest")),
        ("item.crowbar", "item.rope_hempen", "item.torch", "item.light_hammer", "item.dagger"),
        900,
        1,
        2,
    ),
    "казарма": LocationProfile(
        (("Оружейный сундук", "item:chest"), ("Шкаф амуниции", "item:container"), ("Ящик пайков", "item:container")),
        ("item.spear", "item.dagger", "item.club", "item.rations", "item.bedroll", "item.torch"),
        1000,
        1,
        2,
    ),
}


def digest(data: Any) -> str:
    return hashlib.sha256(
        json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def stable_seed(campaign_id: str, target_id: str, phase: str, profile: str) -> int:
    key = f"{GENERATOR_VERSION}:{campaign_id}:{target_id}:{phase}:{profile}"
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def item_price_cp(entry: Entry) -> int | None:
    """Консервативная нормализация цены: незнакомая валюта или формула запрещает автодобычу."""
    price = entry.data.get("price")
    if not isinstance(price, dict) or not price or any(k not in _COIN_COPPER for k in price):
        return None
    try:
        value = sum(Decimal(str(v)) * _COIN_COPPER[k] for k, v in price.items())
    except (InvalidOperation, TypeError, ValueError):
        return None
    return int(value) if value >= 0 and value == int(value) else None


def _has_custom_op(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_custom_op(v) for v in value)
    if isinstance(value, dict):
        return value.get("op") == "custom" or any(_has_custom_op(v) for v in value.values())
    return False


def eligible(entry: Entry) -> bool:
    """Никаких услуг, реликвий, уникальных/сюжетных вещей и неисполняемых эффектов."""
    data = entry.data
    return (
        entry.kind == "item_template"
        and entry.status == "canon"
        and data.get("category") in _ALLOWED_CATEGORIES
        and data.get("rarity") in (None, "common")
        and not data.get("unique")
        and data.get("spawnable") is not False
        and not any(data.get(k) for k in ("not_loot", "story_gate", "by_scenario", "plot_anchor", "lead_item_ref"))
        and not _has_custom_op(data.get("modifiers"))
        and not _has_custom_op(data.get("effects"))
        and item_price_cp(entry) is not None
    )


def permitted_pool(catalog: CatalogView, profile: LocationProfile) -> list[Entry]:
    """CatalogView фильтрует пропущенные или неразрешённые записи, даже в тестовых кампаниях."""
    return [
        entry
        for item_id in profile.item_ids
        if (entry := catalog.find(item_id, "item_template")) is not None and eligible(entry)
    ]


def source_snapshot(entries: list[Entry], profile: str, phase: str) -> tuple[list[str], str]:
    """Хешируем реальную доступную механику, а не только название или текущий уровень героев."""
    versions = sorted({e.pack_id for e in entries})
    snapshot = [
        (e.id, e.pack_id, e.status, e.data.get("category"), e.data.get("rarity"), e.data.get("price")) for e in entries
    ]
    return versions, digest((GENERATOR_VERSION, phase, profile, snapshot))


def choose_loot(entries: list[Entry], seed: int, budget_cp: int, limit: int) -> list[Entry]:
    """Выбор воспроизводим, сортировка кандидатов не зависит от порядка импортов каталога."""
    rng = random.Random(seed)
    pool = sorted(entries, key=lambda e: e.id)
    rng.shuffle(pool)
    out: list[Entry] = []
    remaining = budget_cp
    for entry in pool:
        price = item_price_cp(entry)
        if price is not None and price <= remaining:
            out.append(entry)
            remaining -= price
        if len(out) == limit:
            break
    return out
