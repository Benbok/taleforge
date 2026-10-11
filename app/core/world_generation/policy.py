"""Детерминированный резерв и план подготовки (§4.4, §4.5).

Резерв фиксируется при создании цели и потом не меняется: seed, версия policy и PRNG, путь стабильных слотов,
профиль, цепочка пакетов кампании, бюджет, лимиты и глубина. План строится из резерва и профиля заново при каждой
попытке и выходит тем же. Для любого узла ``стоимость прямых находок + резервы детей <= резерв узла``: дочерний
контейнер получает долю, а не новый бюджет. Seed потомка — хеш от seed родителя и слота: дата, уровень героев,
модель и порядок исследования в него не входят.
"""

from __future__ import annotations

import hashlib
import random
from typing import Any

from app.core.world_generation.contracts import POLICY_VERSION, PRNG, Blocked, Plan, Slot
from app.core.world_generation.profiles import SceneProfile

DECOR_MAX = 2  # обстановки на виду не больше: остальное место — находкам и контейнерам


def _seed(*parts: str) -> int:
    return int(hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest()[:8], 16) & 0x7FFFFFFF


def root_seed(campaign_id: str, target_id: str, phase: str) -> int:
    return _seed(POLICY_VERSION, campaign_id, target_id, phase)


def child_seed(seed: int, slot_ref: str) -> int:
    return _seed(POLICY_VERSION, str(seed), slot_ref)


def anchor_cost(profile: SceneProfile, template_id: str | None) -> int | None:
    """Записка без механики стоит 0; предмет — по профилю места; иначе стоимость неизвестна."""
    from app.core.plot_anchors import NOTE

    if template_id in (None, NOTE):
        return 0
    return profile.cost_of(template_id)


def root_reservation(
    campaign: Any,
    target_id: str,
    profile: SceneProfile,
    authored: list[str | None],
    anchors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Корень места. Авторская добыча (шаблоны предметов, уже лежащих в месте) и сюжетные носители учитываются
    первыми; неизвестная стоимость обнуляет случайный остаток с диагностикой, но обязательное не отбрасывается."""
    diagnostics: list[str] = []
    fixed = [
        dict(a, cost=anchor_cost(profile, a.get("template_id")))
        for a in sorted(anchors or [], key=lambda a: a["anchor_id"])
    ]
    costs = [profile.cost_of(t) for t in authored]
    if any(c is None for c in costs):
        diagnostics.append("unknown_authored_cost")
    if any(a["cost"] is None for a in fixed):
        diagnostics.append("unknown_anchor_cost")
    used = sum(c for c in costs if c is not None) + sum(a["cost"] or 0 for a in fixed)
    if diagnostics:
        budget = 0
    else:
        budget = max(0, profile.budget - used)
        if used > profile.budget:
            diagnostics.append("authored_over_budget")
    lim = profile.limits
    return {
        "schema_version": 1,
        "policy_version": POLICY_VERSION,
        "prng": PRNG,
        "phase": "location_initial",
        "seed": root_seed(campaign.id, target_id, "location_initial"),
        "path": "root",
        "profile_ref": profile.ref,
        "content_chain": list(campaign.content_chain or []),
        "budget": budget,
        "limits": {"entities": lim.entities, "item_units": lim.item_units, "containers": lim.containers},
        "depth": lim.depth,
        "authored_cost": used,  # известная часть; неизвестная — в diagnostics
        "anchors": fixed,
        "diagnostics": diagnostics,
    }


def check_reservation(reservation: dict[str, Any], campaign: Any) -> None:
    if reservation.get("schema_version") != 1 or reservation.get("policy_version") != POLICY_VERSION:
        raise Blocked("unsupported_source", f"policy {reservation.get('policy_version')} не поддерживается")
    if reservation.get("prng") != PRNG:
        raise Blocked("unsupported_source", f"PRNG {reservation.get('prng')} не поддерживается")
    if list(reservation.get("content_chain") or []) != list(campaign.content_chain or []):
        raise Blocked("unsupported_source", "цепочка пакетов кампании изменилась после резерва")


def build_plan(reservation: dict[str, Any], profile: SceneProfile, target_id: str) -> Plan:
    rng = random.Random(int(reservation["seed"]))
    phase = reservation["phase"]
    root = phase == "location_initial"
    budget = int(reservation["budget"])
    limits = reservation["limits"]
    entities, units, max_cont = int(limits["entities"]), int(limits["item_units"]), int(limits["containers"])
    depth = int(reservation["depth"])
    plan = Plan(phase=phase, target_id=target_id, reservation=reservation)
    zones = ("near", "far")

    pool = profile.containers if root else profile.inner
    n_cont = min(max_cont, len(pool), entities) if depth > 0 else 0
    chosen = sorted(rng.sample(list(pool), n_cont), key=lambda f: f.slot) if n_cont else []
    entities -= n_cont
    if root:
        for f in profile.decor[: min(DECOR_MAX, entities)]:
            plan.slots.append(
                Slot(f"decor:{f.slot}", "prop", f.name, f.description, zone=rng.choice(zones), visual_key=f.visual_key)
            )
            entities -= 1

    share = profile.visible_share
    direct_budget = budget if not n_cont else budget * share // 100
    direct_units = units if not n_cont else units * share // 100
    direct_entities = entities if not n_cont else entities * share // 100
    candidates = list(profile.items)
    rng.shuffle(candidates)
    left_budget, left_units, left_entities = direct_budget, direct_units, direct_entities
    picked = 0
    for rule in candidates:
        if left_units <= 0 or left_entities <= 0:
            break
        if rule.cost > left_budget:
            continue
        plan.slots.append(Slot(f"item:{picked}", "item", "", template_id=rule.template, cost=rule.cost,
                               zone=rng.choice(zones)))  # fmt: skip
        picked += 1
        left_budget -= rule.cost
        left_units -= 1
        left_entities -= 1
        plan.spent += rule.cost

    if n_cont:
        child_budget = (budget - direct_budget) // n_cont
        child_units = (units - direct_units) // n_cont
        child_entities = (entities - direct_entities) // n_cont
        child_containers = (max_cont - n_cont) // n_cont
        prefix = "container" if root else "inner"
        for f in chosen:
            ref = f"{prefix}:{f.slot}"
            plan.slots.append(Slot(ref, "container", f.name, f.description, zone=rng.choice(zones),
                                   visual_key=f.visual_key or "item:chest"))  # fmt: skip
            plan.children[ref] = {
                **{k: reservation[k] for k in ("schema_version", "policy_version", "prng", "profile_ref")},
                "content_chain": list(reservation.get("content_chain") or []),
                "phase": "container_contents",
                "seed": child_seed(int(reservation["seed"]), ref),
                "path": f"{reservation['path']}/{ref}",
                "budget": child_budget,
                "limits": {"entities": child_entities, "item_units": child_units, "containers": child_containers},
                "depth": depth - 1,
                "diagnostics": [],
            }
    _place_anchors(plan, reservation, chosen_refs=list(plan.children) if root else None)
    assert plan.spent + sum(int(c["budget"]) for c in plan.children.values()) <= budget  # инвариант §4.5
    return plan


def _place_anchors(plan: Plan, reservation: dict[str, Any], chosen_refs: list[str] | None) -> None:
    """Сюжетные носители (§8.1): обязательны, вне случайного бюджета (их стоимость уже вычтена в корне) и вне
    лимитов. Скрытый носитель уходит в резерв одного из контейнеров плана; выбор — отдельный генератор от seed и
    id зацепки, поэтому добыча и seed контейнеров от носителей не меняются. В фазе контейнера (``chosen_refs`` —
    None) носители его резерва ложатся в него самого."""
    seed = int(reservation["seed"])
    for a in reservation.get("anchors") or []:
        if a.get("hidden") and chosen_refs:
            pick = random.Random(child_seed(seed, f"anchor:{a['anchor_id']}")).randrange(len(chosen_refs))
            plan.children[chosen_refs[pick]].setdefault("anchors", []).append(a)
            continue
        if a.get("hidden") and chosen_refs is not None:
            plan.notes.append(f"anchor_visible_no_container:{a['anchor_id']}")
        zone = random.Random(child_seed(seed, f"zone:{a['anchor_id']}")).choice(("near", "far"))
        plan.slots.append(
            Slot(
                f"anchor:{a['anchor_id']}",
                "item",
                a["name"],
                a.get("description") or "",
                template_id=a.get("template_id"),
                zone=zone,
                anchor_id=a["anchor_id"],
            )
        )
