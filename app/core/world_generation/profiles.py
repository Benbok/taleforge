"""Профили наполнения ``scene_profile`` (§4.1). Читаются из каталога кампании и строго проверяются: неизвестное
поле, неположительная стоимость, неизвестный или неподходящий шаблон отклоняют профиль, а не молча пропускаются.
Без профиля работает версионированный ``minimal``: без добычи и контейнеров."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.content.catalog import CatalogView, Entry

MINIMAL_REF = "minimal"
_ALLOWED_CATEGORIES = frozenset({"gear", "tool", "weapon", "armor", "ammo", "consumable", "trade_good"})
_COMMON = {"id", "name", "status", "description", "doc", "tags", "epithet", "badge", "summary", "highlights"}
_FIELDS = _COMMON | {
    "schema_version",
    "theme_tags",
    "loot_budget",
    "visible_share",
    "limits",
    "items",
    "containers",
    "inner_containers",
    "decor",
}
_LIMITS = ("max_generated_entities", "max_item_units", "max_containers", "max_depth")


class ProfileError(Exception):
    pass


@dataclass(frozen=True)
class ItemRule:
    template: str
    cost: int


@dataclass(frozen=True)
class Furnishing:
    slot: str
    name: str
    visual_key: str | None = None
    description: str = ""


@dataclass(frozen=True)
class Limits:
    entities: int
    item_units: int
    containers: int
    depth: int


@dataclass(frozen=True)
class SceneProfile:
    ref: str
    source: str  # пакет-источник или версия minimal
    budget: int
    visible_share: int
    limits: Limits
    items: tuple[ItemRule, ...] = ()
    containers: tuple[Furnishing, ...] = ()
    inner: tuple[Furnishing, ...] = ()
    decor: tuple[Furnishing, ...] = ()
    themes: tuple[str, ...] = ()

    def cost_of(self, template_id: str | None) -> int | None:
        return next((r.cost for r in self.items if r.template == template_id), None)


MINIMAL = SceneProfile(MINIMAL_REF, "minimal-v1", 0, 0, Limits(0, 0, 0, 0))


def freeze_profile(profile: SceneProfile) -> dict[str, Any]:
    return asdict(profile)


def restore_profile(raw: dict[str, Any]) -> SceneProfile:
    return SceneProfile(
        ref=raw["ref"],
        source=raw["source"],
        budget=raw["budget"],
        visible_share=raw["visible_share"],
        limits=Limits(**raw["limits"]),
        items=tuple(ItemRule(**x) for x in raw.get("items", [])),
        containers=tuple(Furnishing(**x) for x in raw.get("containers", [])),
        inner=tuple(Furnishing(**x) for x in raw.get("inner", [])),
        decor=tuple(Furnishing(**x) for x in raw.get("decor", [])),
        themes=tuple(raw.get("themes", [])),
    )


def _has_custom_op(value: Any) -> bool:
    if isinstance(value, list):
        return any(_has_custom_op(v) for v in value)
    if isinstance(value, dict):
        return value.get("op") == "custom" or any(_has_custom_op(v) for v in value.values())
    return False


def eligible(entry: Entry) -> bool:
    """Случайной наградой может быть только обычная вещь: без услуг, реликвий, уникальных и сюжетных вещей
    и без неисполняемых эффектов."""
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
    )


def _int(data: dict, key: str, *, minimum: int = 0, maximum: int | None = None, default: int | None = None) -> int:
    value = data.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ProfileError(f"{key}: нужно целое число не меньше {minimum}")
    if maximum is not None and value > maximum:
        raise ProfileError(f"{key}: не больше {maximum}")
    return value


def _furnishings(raw: Any, what: str) -> tuple[Furnishing, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ProfileError(f"{what}: нужен список")
    out = []
    for x in raw:
        if not isinstance(x, dict) or set(x) - {"slot", "name", "visual_key", "description"}:
            raise ProfileError(f"{what}: допустимы только slot, name, visual_key, description")
        slot, name = x.get("slot"), x.get("name")
        if not isinstance(slot, str) or not slot or not isinstance(name, str) or not name:
            raise ProfileError(f"{what}: нужны slot и name")
        out.append(Furnishing(slot, name, x.get("visual_key"), str(x.get("description") or "")))
    if len({f.slot for f in out}) != len(out):
        raise ProfileError(f"{what}: slot повторяется")
    return tuple(sorted(out, key=lambda f: f.slot))


def parse_profile(entry: Entry, catalog: CatalogView) -> SceneProfile:
    data = entry.data
    extra = set(data) - _FIELDS
    if extra:
        raise ProfileError(f"неизвестные поля: {', '.join(sorted(extra))}")
    if data.get("schema_version") != 1:
        raise ProfileError("поддерживается только schema_version 1")
    limits = data.get("limits")
    if not isinstance(limits, dict) or set(limits) != set(_LIMITS):
        raise ProfileError(f"limits: нужны ровно {', '.join(_LIMITS)}")
    items = []
    for rule in data.get("items") or []:
        if not isinstance(rule, dict) or set(rule) != {"template", "generation_cost"}:
            raise ProfileError("items: нужны ровно template и generation_cost")
        cost = _int(rule, "generation_cost", minimum=1)
        rec = catalog.find(str(rule["template"]), "item_template")
        if rec is None or not eligible(rec):
            raise ProfileError(f"шаблон {rule['template']} недоступен для случайной добычи")
        items.append(ItemRule(rec.id, cost))
    return SceneProfile(
        ref=entry.id,
        source=entry.pack_id,
        budget=_int(data, "loot_budget"),
        visible_share=_int(data, "visible_share", maximum=100, default=30),
        limits=Limits(*(_int(limits, k) for k in _LIMITS)),
        items=tuple(sorted(items, key=lambda r: r.template)),
        containers=_furnishings(data.get("containers"), "containers"),
        inner=_furnishings(data.get("inner_containers"), "inner_containers"),
        decor=_furnishings(data.get("decor"), "decor"),
        themes=tuple(str(t) for t in data.get("theme_tags") or [] if isinstance(t, str)),
    )


def load_profile(catalog: CatalogView, ref: str | None) -> SceneProfile:
    if not ref or ref == MINIMAL_REF:
        return MINIMAL
    entry = catalog.find(ref, "scene_profile")
    if entry is None:
        raise ProfileError(f"профиля {ref} нет в каталоге кампании")
    return parse_profile(entry, catalog)


def profile_ref_for(location: Any, catalog: CatalogView) -> str:
    """Назначенный ведущим профиль важнее шаблона места; без обоих — minimal."""
    st = location.state if isinstance(location.state, dict) else {}
    if isinstance(st.get("scene_profile"), str):
        return st["scene_profile"]
    roles = {
        "warehouse": "warehouse",
        "storage": "warehouse",
        "store": "warehouse",
        "cellar": "warehouse",
        "pantry": "warehouse",
        "market": "workshop",
        "shop": "workshop",
        "workshop": "workshop",
        "smithy": "workshop",
        "pier": "warehouse",
        "cargo_pier": "warehouse",
        "quay": "warehouse",
        "dock": "warehouse",
        "cache": "cave",
        "cave": "cave",
        "grotto": "cave",
        "cavern": "cave",
        "tavern": "tavern",
        "common_room": "tavern",
        "dining": "tavern",
        "dining_room": "tavern",
        "bedroom": "house",
        "guest_room": "house",
        "guest_rooms": "house",
        "kitchen": "house",
        "house": "house",
        "barracks": "barracks",
        "dormitory": "barracks",
        "guardroom": "barracks",
        "laboratory": "laboratory",
        "crypt": "crypt",
        "tomb": "crypt",
    }
    role_ref = roles.get(st.get("role"))
    if role_ref and catalog.find(f"scene_profile.{role_ref}", "scene_profile") is not None:
        return f"scene_profile.{role_ref}"
    template = catalog.find(location.template_id, "location_template") if location.template_id else None
    ref = template.data.get("scene_profile") if template is not None else None
    return ref if isinstance(ref, str) else MINIMAL_REF
