"""Карточки бросков в чате (документ «Дизайн фронтенда», раздел о чате).

Каждое открытое событие журнала с кубиками становится сообщением ``kind="roll"``: короткая строка в ``content``
(для истории и прежнего клиента) и данные карточки в ``data`` — что проверялось, кубик, итог против сложности,
успех или провал и разбор. Скрытые броски карточки не получают: игрок видит только последствия в повествовании.
Числа существ, которых игроки не знают (КБ, хиты), в карточку не попадают.
"""

from __future__ import annotations

from typing import Any

from app.db.models import Event

ABILITY_RU = {
    "str": "Сила",
    "dex": "Ловкость",
    "con": "Телосложение",
    "int": "Интеллект",
    "wis": "Мудрость",
    "cha": "Харизма",
}
SKILL_RU = {
    "acrobatics": "Акробатика",
    "animal_handling": "Уход за животными",
    "arcana": "Магия",
    "athletics": "Атлетика",
    "deception": "Обман",
    "history": "История",
    "insight": "Проницательность",
    "intimidation": "Запугивание",
    "investigation": "Анализ",
    "medicine": "Медицина",
    "nature": "Природа",
    "perception": "Внимательность",
    "performance": "Выступление",
    "persuasion": "Убеждение",
    "religion": "Религия",
    "sleight_of_hand": "Ловкость рук",
    "stealth": "Скрытность",
    "survival": "Выживание",
}
DAMAGE_RU = {
    "acid": "кислотой",
    "bludgeoning": "дробящий",
    "cold": "холодом",
    "fire": "огнём",
    "force": "силовым полем",
    "lightning": "электричеством",
    "necrotic": "некротический",
    "piercing": "колющий",
    "poison": "ядом",
    "psychic": "психический",
    "radiant": "излучением",
    "slashing": "рубящий",
    "thunder": "звуком",
}
MODE_RU = {"advantage": "с преимуществом", "disadvantage": "с помехой"}


def _d20(dice: list[dict]) -> dict[str, Any] | None:
    d = next((x for x in dice if "d20" in x), None)
    if d is None:
        return None
    return {
        "d20": d.get("d20"),
        "natural": d.get("natural"),
        "modifier": d.get("modifier"),
        "mode": d.get("mode") if d.get("mode") in MODE_RU else None,
        "total": d.get("total"),
    }


def _dmg(dice: list[dict]) -> list[dict[str, Any]]:
    return [{"expr": x.get("expr"), "rolls": x.get("rolls"), "total": x.get("total")} for x in dice if "expr" in x]


def card(ev: Event, hero_ids: set[str]) -> dict[str, Any] | None:
    """Данные карточки для события или None, если карточки у события нет."""
    if ev.hidden or (not ev.dice and ev.tool != "cast_spell"):
        return None
    p = ev.payload or {}
    dice = ev.dice or []
    if ev.tool == "cast_spell":
        return _spell_card(ev, p, dice, hero_ids)
    if ev.tool == "roll_check":
        label = SKILL_RU.get(p.get("stat"), ABILITY_RU.get(p.get("stat"), p.get("stat")))
        return {
            "tool": ev.tool,
            "title": f"{'Спасбросок' if p.get('kind') == 'save' else 'Проверка'}: {label}",
            "who": p.get("who"),
            "reason": p.get("reason"),
            "roll": _d20(dice),
            "against": {"label": "Сл", "value": p.get("dc")},
            "outcome": "success" if p.get("success") else "fail",
            "notes": list(p.get("reasons") or []) + ([p["auto_fail"]] if p.get("auto_fail") else []),
        }
    if ev.tool == "resolve_attack":
        outcome = "crit" if p.get("critical") else "hit" if p.get("hit") else "miss"
        out: dict[str, Any] = {
            "tool": ev.tool,
            "title": f"Атака: {p.get('attack')}",
            "who": p.get("attacker"),
            "target": p.get("target"),
            "roll": _d20(dice),
            # КБ героя игроки знают, КБ существа — нет
            "against": {"label": "КБ", "value": p.get("target_ac")} if ev.target_id in hero_ids else None,
            "outcome": outcome,
            "notes": list(p.get("reasons") or []),
        }
        if p.get("hit"):
            out["damage"] = {
                "amount": p.get("damage"),
                "type": DAMAGE_RU.get(p.get("damage_type"), p.get("damage_type")),
                "dice": _dmg(dice),
            }
            if p.get("killed"):
                out["notes"].append(f"{p.get('target')} повержен")
        return out
    if ev.tool == "death_save":
        return {
            "tool": ev.tool,
            "title": "Спасбросок от смерти",
            "who": p.get("who"),
            "roll": _d20(dice),
            "against": {"label": "Сл", "value": 10},
            "outcome": "success" if (p.get("natural") or 0) >= 10 else "fail",
            "track": {"successes": p.get("successes"), "failures": p.get("failures")},
            "notes": ["стабилен"] * bool(p.get("stable")) + ["погиб"] * bool(p.get("dead")),
        }
    if ev.tool == "set_scene_mode":
        return {
            "tool": ev.tool,
            "title": "Инициатива",
            "order": [{"id": x.get("id"), "initiative": x.get("initiative")} for x in p.get("order") or []],
            "outcome": "info",
        }
    title = {"apply_hazard": f"Опасность: {p.get('hazard')}", "use_item": f"Предмет: {p.get('item')}"}.get(
        ev.tool, "Бросок"
    )
    return {
        "tool": ev.tool,
        "title": title,
        "who": p.get("user"),
        "target": p.get("target"),
        "dice": _dmg(dice),
        "outcome": "info",
    }


def _spell_card(ev: Event, p: dict, dice: list[dict], hero_ids: set[str]) -> dict[str, Any]:
    """Заклинание: ячейка, бросок атаки заклинанием или спасброски целей, урон и лечение по целям."""
    rows = [r for r in p.get("outcomes") or [] if r.get("target")]
    slot = p.get("slot") or {}
    title = f"Заклинание: {p.get('spell')}"
    notes: list[str] = []
    if p.get("source"):
        notes.append(f"со свитка «{p['source']}»: без ячейки")
    sc = p.get("scroll_check") or {}
    if sc:
        notes.append(
            f"проверка свитка {sc.get('total')} против Сл {sc.get('dc')} — "
            + ("прочитан" if sc.get("success") else "не удалась, свиток пропал")
        )
    if p.get("ritual"):
        notes.append("ритуал: без ячейки, на 10 минут дольше")
    elif slot:
        notes.append(f"{'ячейка договора' if slot.get('kind') == 'pact' else 'ячейка'} {slot.get('level')}-го круга")
    for r in rows:
        bits = [str(r["target"])]
        if "save" in r:
            bits.append(
                f"спасбросок {ABILITY_RU.get(r['save'], r['save'])} {r.get('total')} против Сл {r.get('dc')} — "
                + ("успех" if r.get("success") else "провал")
            )
        elif "attack_roll" in r and len(rows) > 1:
            bits.append("попадание" if r.get("hit") else "промах")
        if r.get("damage"):
            types = ", ".join(DAMAGE_RU.get(t, t) for t in r.get("damage_types") or [])
            bits.append(f"урон {r['damage']}" + (f" ({types})" if types else ""))
        if r.get("healed") is not None:
            bits.append(f"лечение {r['healed']}")
        if r.get("temp_hp"):
            bits.append(f"временные хиты {r['temp_hp']}")
        if r.get("killed"):
            bits.append("повержен")
        conc = r.get("concentration_check")
        if conc and not conc.get("kept", True):
            bits.append(f"концентрация на «{conc.get('concentration')}» сорвана")
        if len(bits) > 1:
            notes.append(f"{bits[0]}: {', '.join(bits[1:])}")
    if (p.get("concentration_ended") or {}).get("spell"):
        notes.append(f"концентрация на «{p['concentration_ended']['spell']}» прервана")
    out: dict[str, Any] = {"tool": ev.tool, "title": title, "who": p.get("caster"), "outcome": "info", "notes": notes}
    attacks = [r for r in rows if "attack_roll" in r]
    if len(attacks) == 1:
        a = attacks[0]
        out["target"] = a["target"]
        out["roll"] = _d20(dice)
        out["outcome"] = "crit" if a.get("critical") else "hit" if a.get("hit") else "miss"
        if a.get("target_id") in hero_ids:
            out["against"] = {"label": "КБ", "value": a.get("target_ac")}
    elif len(rows) == 1:
        out["target"] = rows[0]["target"]
    total = sum(int(r.get("damage") or 0) for r in rows)
    if total:
        types = sorted({t for r in rows for t in r.get("damage_types") or []})
        out["damage"] = {
            "amount": total,
            "type": ", ".join(DAMAGE_RU.get(t, t) for t in types),
            "dice": _dmg(dice),
        }
    elif dice:
        out["dice"] = _dmg(dice)
    return out


def line(c: dict[str, Any], names: dict[str, str] | None = None) -> str:
    """Карточка одной строкой — для истории чата и прежнего клиента."""
    parts = [c["title"]]
    if c.get("who"):
        parts.append(str(c["who"]))
    if c.get("target"):
        parts.append(f"→ {c['target']}")
    roll = c.get("roll") or {}
    if roll.get("total") is not None:
        against = c.get("against")
        parts.append(f"{roll['total']}" + (f" против {against['label']} {against['value']}" if against else ""))
    word = {"success": "успех", "fail": "провал", "hit": "попадание", "miss": "промах", "crit": "критическое попадание"}
    if c.get("outcome") in word:
        parts.append(word[c["outcome"]])
    if c.get("damage"):
        parts.append(f"урон {c['damage']['amount']}")
    if c.get("order"):
        names = names or {}
        parts.append(", ".join(f"{names.get(x['id'], x['id'])} {x['initiative']}" for x in c["order"]))
    if c.get("dice") and not roll:
        parts.append(", ".join(str(d["total"]) for d in c["dice"]))
    return " · ".join(parts)
