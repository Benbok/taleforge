"""Последствия поступков (просьба Arty 2026-09-29): отношение NPC, фракций и мест к отряду и их ответ.

Мастер не назначает отношение числом: он только называет поступок (помог или навредил), его вес и тайный ли он.
Очки, ступени отношения, круги по связанным фракциям и срок ответа считает этот модуль. Когда отношение уходит
на новую ступень от нуля, мир готовит ответ: благодарность или месть. Ответ созревает (фракции — через несколько
игровых дней, NPC и местные — сразу) и попадает мастеру в фазу решения вместе со способами, которые есть у этой
стороны: строки ``standing_table`` пакета, иначе ресурсы фракции и общая лестница ниже.

Всё хранится в ``scene.state["standing"]``: одна запись на кампанию, её снимок — обратная дельта события.
Вдохновение SRD 5.1 (Inspiration) — личная награда героя за яркую игру: есть или нет, тратится на преимущество.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from app.rules.base import RollMode

# ступени отношения: как у отношений между фракциями в пакете (attitude −3…+3)
TIER_RU = {
    -3: "кровные враги",
    -2: "враждебны",
    -1: "настороже",
    0: "безразличны",
    1: "благосклонны",
    2: "союзники",
    3: "преданы",
}
THRESHOLDS = (2, 5, 10)  # очков для ступеней 1, 2, 3
POINTS_CAP = 15
WEIGHT = {"minor": 1, "major": 3, "critical": 6}
WEIGHT_RU = {"minor": "мелочь", "major": "серьёзно", "critical": "судьбоносно"}
FACTION_DELAY = "1d4"  # дней до ответа фракции: слухи доходят, решение принимают, люди собираются
RIPPLE_MIN_ATTITUDE = 2  # круги расходятся только к тем, кому фракция небезразлична (|attitude| ≥ 2)
DEEDS_KEPT = 6
MOOD_RU = {"gratitude": "благодарность", "revenge": "месть"}

# Способы по умолчанию: кто угодно может ответить так, не выходя из своей роли. Механика — только инструментами.
GENERIC_MEANS: dict[str, dict[int, list[str]]] = {
    "gratitude": {
        1: ["доброе слово и слух о героях", "скидка, ночлег, место у огня", "полезная подсказка или сплетня"],
        2: [
            "услуга: проводник, укрытие, рекомендательное письмо",
            "подарок из того, что у них есть (give_item по шаблону)",
            "заступничество перед стражей или своими",
        ],
        3: [
            "рискнёт ради героев: встанет рядом в бою (spawn_entity attitude=friendly)",
            "отдаст ценное или откроет тайну (learn_fact, reveal_knowledge)",
            "позовёт своих на помощь героям",
        ],
    },
    "revenge": {
        1: ["холод: отказ, цены выше, дурная молва", "не пускают, не отвечают, следят"],
        2: [
            "вред исподтишка: донос, кража, ложный след",
            "подстава перед властями или другой фракцией",
            "наёмные громилы с предупреждением (spawn_entity, бюджет встречи)",
        ],
        3: [
            "открытая месть: засада или нападение с подручными (spawn_entity, бюджет встречи)",
            "награда за головы виновных",
            "удар по тому, что героям дорого: союзнику, дому, имени",
        ],
    },
}


class StandingError(Exception):
    """Неверный поступок или ответ; текст уходит мастеру."""


def tier_of(points: int) -> int:
    n = sum(1 for t in THRESHOLDS if abs(points) >= t)
    return n if points >= 0 else -n


def tier_label(t: int) -> str:
    return f"{TIER_RU[t]} ({t:+d})" if t else TIER_RU[0]


def book(state: dict | None) -> dict:
    """Копия раздела отношений из состояния сцены, с пустыми разделами по умолчанию."""
    b = copy.deepcopy((state or {}).get("standing") or {})
    b.setdefault("subjects", {})
    b.setdefault("responses", [])
    b.setdefault("hidden", [])
    b.setdefault("seq", 0)
    return b


def _next_id(b: dict, prefix: str) -> str:
    b["seq"] = int(b.get("seq") or 0) + 1
    return f"{prefix}{b['seq']}"


def points_of(b: dict, subject_id: str) -> int:
    return int((b["subjects"].get(subject_id) or {}).get("points") or 0)


def ripple(catalog, subject_id: str, kind: str, points: int, template_id: str | None = None) -> list[tuple]:
    """Кого ещё задел поступок: фракция NPC; для фракции — её родительская фракция и те, кому она союзник или враг.

    Возвращает ``[(faction_id, name, points, why)]``. Вторых кругов нет: слух расходится на один шаг."""
    out: list[tuple] = []
    if kind == "npc":
        rec = catalog.find(template_id or "") if template_id else None
        fid = (rec.data if rec else {}).get("faction_ref")
        fac = catalog.find(fid, "faction") if fid else None
        share = int(points / 2)
        if fac is not None and share:
            out.append((fac.id, fac.name, share, "свой человек"))
        return out
    rec = catalog.find(subject_id, "faction") if kind == "faction" else None
    if rec is None:
        return out
    parent = catalog.find(rec.data.get("parent_ref") or "", "faction")
    half = int(points / 2)
    if parent is not None and half:
        out.append((parent.id, parent.name, half, f"часть их: {rec.name}"))
    for other in catalog.by_kind("faction"):
        if other.id == subject_id:
            continue
        for r in other.data.get("relations") or []:
            att = int(r.get("attitude") or 0) if isinstance(r, dict) else 0
            if r.get("faction_ref") != subject_id or abs(att) < RIPPLE_MIN_ATTITUDE:
                continue
            share = int(points * att / 6)
            if share:
                why = f"{'союзники' if att > 0 else 'враги'} {rec.name}"
                out.append((other.id, other.name, share, why))
    return out


def _deed_line(text: str, pts: int, by: list[str]) -> str:
    return f"{'помощь' if pts > 0 else 'вред'} {pts:+d}: {text}" + (f" ({', '.join(by)})" if by else "")


def shift(
    b: dict,
    subject_id: str,
    kind: str,
    name: str,
    pts: int,
    text: str,
    by: list[str],
    by_ids: list[str],
    now: int,
    delay: Callable[[], int] | None = None,
) -> dict:
    """Сдвигает отношение стороны и ведёт её ответ. ``delay`` — через сколько секунд созреет новый ответ
    (бросается, только если ответ появился). Возвращает сводку изменения для мастера."""
    subj = b["subjects"].setdefault(subject_id, {"kind": kind, "name": name, "points": 0, "deeds": []})
    subj["name"] = name
    before = int(subj.get("points") or 0)
    after = max(-POINTS_CAP, min(POINTS_CAP, before + pts))
    subj["points"] = after
    subj["deeds"] = [*subj.get("deeds", []), {"text": _deed_line(text, pts, by), "at": now}][-DEEDS_KEPT:]
    t0, t1 = tier_of(before), tier_of(after)
    change: dict[str, Any] = {"subject": name, "points": pts, "tier": tier_label(t1)}
    if t1 != t0:
        change["was"] = tier_label(t0)
    resp = next((r for r in b["responses"] if r["subject_id"] == subject_id and r["status"] != "done"), None)
    mood = "gratitude" if t1 > 0 else "revenge"
    if resp is not None and (t1 == 0 or resp["mood"] != mood):
        b["responses"].remove(resp)  # искупили или переменились: прежний ответ отменён
        change["response_cancelled"] = MOOD_RU[resp["mood"]]
        resp = None
    if resp is not None:
        resp["tier"] = t1
        for i, n in zip(by_ids, by, strict=False):
            if i not in resp["target_ids"]:
                resp["target_ids"].append(i)
                resp["targets"].append(n)
    elif t1 and abs(t1) > abs(t0) and (t0 == 0 or (t0 > 0) == (t1 > 0)):
        wait = delay() if delay else 0
        resp = {
            "id": _next_id(b, "resp"),
            "subject_id": subject_id,
            "kind": kind,
            "name": name,
            "mood": mood,
            "tier": t1,
            "due_at": now + wait,
            "status": "pending",
            "targets": list(by),
            "target_ids": list(by_ids),
            "reason": text,
        }
        b["responses"].append(resp)
        change["response"] = {"id": resp["id"], "mood": MOOD_RU[mood], "due_in_hours": wait // 3600}
    return change


def means(catalog, resp: dict) -> list[str]:
    """Чем эта сторона может ответить на своей ступени: строки пакета, иначе ресурсы фракции и общая лестница."""
    mood, tier = resp["mood"], abs(int(resp["tier"]))
    out: list[str] = []
    if resp["kind"] == "faction":
        fac = catalog.find(resp["subject_id"], "faction")
        for fid in (resp["subject_id"], (fac.data.get("parent_ref") if fac else None)):
            for rec in catalog.by_kind("standing_table"):
                if not fid or rec.data.get("faction_ref") != fid:
                    continue
                for row in rec.data.get(mood) or []:
                    if int(row.get("tier") or 1) <= tier:
                        line = str(row.get("text") or "")
                        refs = [r for k in ("creature_refs", "item_refs", "effect_refs") for r in row.get(k) or []]
                        out.append(line + (f" [{', '.join(refs)}]" if refs else ""))
            if out:
                return out  # своя таблица, иначе таблица родительской фракции
        res = (fac.data.get("resources") if fac else None) or []
        if res:
            out.append("их средства: " + "; ".join(map(str, res)))
    for t in range(1, tier + 1):
        out += GENERIC_MEANS[mood][t]
    return out


def ripen(b: dict, now: int) -> list[dict]:
    """Ответы, чей срок пришёл: становятся готовыми. Возвращает только что созревшие."""
    fresh = []
    for r in b["responses"]:
        if r["status"] == "pending" and int(r["due_at"]) <= now:
            r["status"] = "ready"
            fresh.append(r)
    return fresh


def ready_note(b: dict, catalog, here: set[str]) -> str:
    """Блок для фазы решения мастера: созревшие ответы и тайные поступки, которые ещё могут всплыть."""
    lines = []
    for r in b["responses"]:
        if r["status"] != "ready":
            continue
        where = ""
        if r["kind"] == "npc":
            away = " — не в сцене: ответит при встрече или через своих"
            where = " — сейчас в сцене" if r["subject_id"] in here else away
        who = ", ".join(r["targets"]) or "отряд"
        lines.append(
            f"- {r['id']}: {r['name']} ({tier_label(int(r['tier']))}) хочет — {MOOD_RU[r['mood']]} для: {who}{where}. "
            f"За что: {r['reason']}. Чем могут: {'; '.join(means(catalog, r))}"
        )
    if not lines:
        return ""
    return (
        "Созревшие ответы мира на поступки героев (введи хотя бы один, когда это правдоподобно в сцене, своими "
        "инструментами, затем resolve_response с тем, как это случилось):\n" + "\n".join(lines) + "\n\n"
    )


def standing_summary(b: dict) -> list[dict]:
    out = []
    for sid, s in b["subjects"].items():
        t = tier_of(int(s.get("points") or 0))
        out.append(
            {
                "id": sid,
                "name": s.get("name"),
                "kind": s.get("kind"),
                "tier": t,
                "label": tier_label(t),
                "points": s.get("points"),
                "deeds": [d["text"] for d in s.get("deeds", [])],
            }
        )
    out.sort(key=lambda x: (-abs(x["tier"]), x["name"] or ""))
    return out


# --- вдохновение (SRD 5.1, Inspiration) ---


def has_inspiration(resources: dict | None) -> bool:
    return bool((resources or {}).get("inspiration"))


def spend_inspiration(obj, mode: RollMode, reasons: list[str]) -> tuple[RollMode, list[str], list[dict]]:
    """Герой тратит вдохновение: преимущество на эту атаку, проверку или спасбросок (SRD). Помеху оно гасит."""
    res = dict(obj.resources or {})
    if not res.get("inspiration"):
        raise StandingError(f"у {obj.name} нет вдохновения")
    if mode == RollMode.ADVANTAGE:
        raise StandingError(f"у {obj.name} и так преимущество: вдохновение сохранится до другого броска")
    inverse = [{"table": "characters", "id": obj.id, "field": "resources", "before": copy.deepcopy(obj.resources)}]
    res["inspiration"] = False
    obj.resources = res
    new = RollMode.combine(True, mode == RollMode.DISADVANTAGE)
    return new, [*reasons, "преимущество: вдохновение"], inverse
