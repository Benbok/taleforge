"""Dry run of the action-parsing step against the real technical model, with no database and no dice.

    docker exec -i -e REPEAT=2 taleforge-app-1 python - < tools/eval_exploration.py

Each case is a player's phrase in a given game state. The model answers with the same tool schema and system
prompt the game uses; the answer is checked for the contract the server enforces (valid schema, unique requirement
ids, resolvable references) and for the meaning the phrase should have. "gap" cases show what the engine does not
support yet; they only fail when the answer is unusable. Costs a few cents per run.
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, "/srv")

import litellm  # noqa: E402

from app.agents.master.exploration import SYSTEM  # noqa: E402
from app.agents.master.universal import STRUCTURED_MAX_TOKENS, provider_schema  # noqa: E402
from app.rules.universal.exploration import (  # noqa: E402
    MAGIC_KINDS,
    IntentV2,
    clean_model_intent,
    exploration_capabilities,
)

ACTOR = "ch_hero"
SCENE = {
    "location": {
        "id": "loc1",
        "name": "Слепые Пропасти",
        "description": "Сырой провал, сизый туман, вдали стук костей.",
    },
    "entities": [{"id": "en_bones", "name": "Костяные силуэты в тоннеле"}],
}
FREE = {"form": None, "can_move": True, "can_speak": True, "can_manipulate": True, "can_dismiss": True}
IN_FORM = {"form": "plant_bush", "can_move": False, "can_speak": False, "can_manipulate": False, "can_dismiss": True}
BUSH = {
    "name": "Превращение в куст и наблюдение",
    "profile_id": "ability2-891868717c5dea784f393f0b",
    "revision": "1",
}
CUP = {
    "id": "ob_cup",
    "name": "Кружка",
    "template": "vessel",
    "owner_id": ACTOR,
    "capacity_ml": "300",
    "contents_ml": "0",
}
SPRING = {
    "id": "ob_spring",
    "name": "Родник",
    "template": "water_source",
    "owner_id": None,
    "capacity_ml": "5000",
    "contents_ml": "5000",
}
EFFECTS = [
    {"id": "ue_form", "kind": "change_form", "label": "Форма куста", "remaining_seconds": "12"},
    {"id": "ue_camo", "kind": "camouflage", "label": "Маскировка", "remaining_seconds": "12"},
]
BRIDGE = {
    "id": "ob_bridge",
    "name": "Каменный мост",
    "template": "structure",
    "owner_id": None,
    "scale": "large",
    "sturdiness": "ordinary",
    "leads_to": "Дальний край пропасти",
    "leads_view": "Тёмный уступ за туманом.",
}
STATES = {
    "base": dict(constraints=FREE, active_effects=[], objects=[]),
    "cup": dict(constraints=FREE, active_effects=[], objects=[CUP, SPRING]),
    "form": dict(constraints=IN_FORM, active_effects=EFFECTS, objects=[]),
    "bridge": dict(constraints=FREE, active_effects=[], objects=[BRIDGE]),
}


def case(
    state,
    text,
    *,
    gap=False,
    source=None,
    request=None,
    any_of=None,
    only=None,
    none_of=None,
    dismiss=None,
    automatic=False,
    scale_in=None,
    leads=False,
    over=None,
):
    return dict(
        state=state,
        text=text,
        gap=gap,
        source=source,
        request=request,
        any_of=any_of,
        only=only,
        none_of=none_of,
        dismiss=dismiss,
        automatic=automatic,
        scale_in=scale_in,
        leads=leads,
        over=over,
    )


CASES = [
    # Ordinary actions are free and are not magic.
    case(
        "base",
        "я иду к выходу",
        source="mundane",
        request={"ordinary"},
        any_of={"move"},
        none_of=MAGIC_KINDS,
        automatic=True,
    ),
    case("base", "осматриваюсь по сторонам", source="mundane", request={"ordinary"}, any_of={"observe"}),
    case("base", "молча жду и слушаю", source="mundane", request={"ordinary"}, any_of={"observe", "wait"}),
    case("base", "говорю вполголоса: «Кто здесь?»", source="mundane", request={"ordinary"}, any_of={"speak"}),
    case("base", "ищу тайный проход в стене", source="mundane", request={"ordinary"}, any_of={"observe"}),
    case("base", "не буду колдовать, просто тихо пройду мимо", source="mundane", none_of=MAGIC_KINDS),
    case("base", "делаю вид, что колдую", source="mundane", request={"pretend", "ordinary"}, none_of=MAGIC_KINDS),
    case("base", "делаю вид, что ищу кружку", source="mundane", none_of=MAGIC_KINDS),
    # Magic is paid and must be recognised as magic.
    case("base", "кастую свет на ладони", source="supernatural", request={"supernatural"}, any_of={"illumination"}),
    case("base", "освещаю тоннель светлячками", source="supernatural", any_of={"illumination"}),
    case("base", "колдую искры, чтобы развлечься", source="supernatural", any_of={"cosmetic", "illumination"}),
    case("base", "превращаюсь в куст, чтобы меня не заметили", source="supernatural", any_of={"change_form"}),
    case("base", "создаю деревянную кружку магией", source="supernatural", any_of={"create_object"}),
    # Free creation: anything, priced by the model's own sense of size.
    case(
        "base",
        "создаю длинную лиану, чтобы взобраться по стене",
        source="supernatural",
        any_of={"create_object"},
        scale_in={"small", "medium"},
    ),
    case(
        "base",
        "выращиваю из земли каменный мост через пропасть",
        source="supernatural",
        any_of={"create_object"},
        scale_in={"large", "huge"},
        leads=True,
    ),
    case(
        "base",
        "строю магией каменную стену, чтобы укрыться от скелетов",
        source="supernatural",
        any_of={"create_object"},
        scale_in={"medium", "large"},
    ),
    case(
        "base",
        "выращиваю деревянную кружку из веточки",
        source="supernatural",
        any_of={"create_object"},
        scale_in={"tiny", "small"},
    ),
    case("bridge", "перехожу по мосту на ту сторону", source="mundane", any_of={"move"}, over="ob_bridge"),
    case("base", "создаю огромный замок за одну секунду", gap=True),
    case("base", "создаю машину времени, чтобы вернуться в прошлое", gap=True),
    # Objects.
    case("cup", "наливаю воду из родника в кружку", source="mundane", any_of={"fill"}),
    case("cup", "беру кружку", source="mundane", any_of={"take"}),
    case("cup", "ставлю кружку на землю", source="mundane", any_of={"place"}),
    case("cup", "выпиваю воду из кружки", source="mundane", any_of={"consume"}),
    # Inside the bush form.
    case("form", "снимаю форму куста", source="mundane", request={"ordinary"}, any_of={"dismiss"}, dismiss={"ue_form"}),
    case("form", "выхожу из куста", source="mundane", request={"ordinary"}, any_of={"dismiss"}, dismiss={"ue_form"}),
    case("form", "гашу маскировку", source="mundane", any_of={"dismiss"}, dismiss={"ue_camo"}),
    case(
        "form",
        "продолжаю делать вид, что я просто куст, буду наблюдать",
        source="mundane",
        request={"ordinary"},
        only={"observe", "wait"},
    ),
    case("form", "молча жду и слушаю", source="mundane", only={"observe", "wait"}),
    case("form", "иду к выходу", source="mundane", any_of={"move"}),
    case("form", "громко кричу «Эй, я здесь!»", source="mundane", any_of={"speak"}),
    case("form", "снова превращаюсь в куст, чтобы продлить маскировку", source="supernatural", any_of={"change_form"}),
    case("form", "я не могу ходить по комнате?", source="mundane", only={"observe", "wait", "move"}),
    # Gaps: what the engine does not support yet. These show the model's behaviour and never fail on meaning.
    case("base", "лечу над провалом", gap=True),
    case("base", "атакую костяной силуэт мечом", gap=True),
    case("base", "залечиваю свои раны заклинанием", gap=True),
    case("base", "становлюсь невидимым", gap=True),
    case("base", "пускаю корень в сторону шума, чтобы почувствовать существ", gap=True),
    case("base", "приказываю скелетам остановиться", gap=True),
    case("base", "читаю заклинание огня и поджигаю факел", gap=True),
    case("base", "мне бы хотелось стать кустом", gap=True),
    case("form", "светлячки, освети мне путь", gap=True),
]


def context_of(c):
    state = STATES[c["state"]]
    return {
        "world": {},
        "world_laws": "Нет путешествий во времени и воскрешения из мёртвых.",
        "hero": {"id": ACTOR, "name": "Пупкинатор", "level": 1},
        "resources": {"energies": {"wis": "24", "int": "18"}},
        "scene": SCENE,
        "history": [],
        "source": c["text"],
        "established_evidence": "",
        "objects": state["objects"],
        "constraints": state["constraints"],
        "active_effects": state["active_effects"],
        "known_abilities": [BUSH],
        "actor_id": ACTOR,
        "allowed_target_ids": sorted([ACTOR, "en_bones"]),
        "capabilities": exploration_capabilities(),
        "repair": None,
    }


def known_ids(c):
    state = STATES[c["state"]]
    return {ACTOR, "en_bones"} | {o["id"] for o in state["objects"]} | {e["id"] for e in state["active_effects"]}


def contract_problems(raw, c):
    """What the server would reject before any meaning is considered."""
    try:
        intent = IntentV2.model_validate(clean_model_intent(raw))
    except Exception as exc:  # noqa: BLE001
        err = exc.errors()[0] if hasattr(exc, "errors") else {"loc": (), "msg": str(exc)}
        where = ".".join(str(x) for x in err["loc"])
        return None, [f"схема: {where}: {err['msg'][:70]}"]
    problems = []
    ids = [r.id for r in intent.requirements]
    if len(set(ids)) != len(ids):
        problems.append("повтор id требований")
    covered = {x for e in intent.effects for x in e.required_by}
    if covered - set(ids):
        problems.append("required_by ссылается на несуществующее требование")
    if set(ids) - covered:
        problems.append("требование не покрыто эффектом")
    allowed = known_ids(c)
    refs = [getattr(e, f) for e in intent.effects for f in ("object_id", "source_id", "recipient_id", "target_id")]
    refs += [e.effect_id for e in intent.effects if e.kind == "dismiss"]
    for ref in filter(None, refs):
        if ref not in allowed and not ref.startswith(("intro:", "created:")):
            problems.append(f"неизвестная ссылка {ref}")
    if intent.known_profile_id and intent.known_profile_id != BUSH["profile_id"]:
        problems.append("выдуманный known_profile_id")
    return intent, problems


def meaning_problems(intent, c):
    if c["gap"]:
        return []
    kinds = {e.kind for e in intent.effects}
    out = []
    if c["source"] and intent.source != c["source"]:
        out.append(f"источник {intent.source}, нужен {c['source']}")
    if c["request"] and intent.player_request not in c["request"]:
        out.append(f"player_request {intent.player_request}")
    if c["any_of"] and not (kinds & c["any_of"]):
        out.append(f"нет вида из {sorted(c['any_of'])}: {sorted(kinds)}")
    if c["only"] and not kinds <= c["only"]:
        out.append(f"лишние виды {sorted(kinds - c['only'])}")
    if c["none_of"] and kinds & c["none_of"]:
        out.append(f"магический вид {sorted(kinds & c['none_of'])}")
    if c["automatic"] and intent.resolution != "automatic":
        out.append("нужен resolution=automatic: бросок для обычного действия")
    made = [e for e in intent.effects if e.kind == "create_object"]
    if c["scale_in"] and not any(e.scale in c["scale_in"] for e in made):
        out.append(f"размер {[e.scale for e in made]}, нужен один из {sorted(c['scale_in'])}")
    if c["leads"] and not any(e.leads_to for e in made):
        out.append("постройка должна вести в новое место (leads_to пуст)")
    if c["over"] and not any(e.kind == "move" and e.object_id == c["over"] for e in intent.effects):
        out.append(f"нужен переход по {c['over']}")
    if c["dismiss"]:
        shown = {e.effect_id for e in intent.effects if e.kind == "dismiss"}
        if not c["dismiss"] <= shown:
            out.append(f"dismiss не тех эффектов: {sorted(shown)}")
    return out


MODEL = "gemini/" + os.environ["GEMINI_TECHNICAL_MODEL"]
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "submit_action",
            "description": "Semantic intent for server validation",
            "parameters": provider_schema(IntentV2),
        },
    }
]


def run_once(c):
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(context_of(c), ensure_ascii=False)},
    ]
    try:
        r = litellm.completion(
            model=MODEL,
            messages=messages,
            tools=TOOLS,
            max_tokens=STRUCTURED_MAX_TOKENS,
            tool_choice={"type": "function", "function": {"name": "submit_action"}},
        )
    except Exception as exc:  # noqa: BLE001
        return dict(verdict="FAIL", why=[f"вызов: {type(exc).__name__}"], cost=0.0, out=0)
    cost = litellm.completion_cost(completion_response=r) or 0.0
    calls = r.choices[0].message.tool_calls
    if not calls:
        return dict(
            verdict="FAIL", why=["пустой ответ без вызова инструмента"], cost=cost, out=r.usage.completion_tokens
        )
    raw = json.loads(calls[0].function.arguments)
    intent, why = contract_problems(raw, c)
    if intent is not None:
        why += meaning_problems(intent, c)
    shape = ""
    if intent is not None:
        shape = f"{intent.source}/{intent.player_request}: {','.join(e.kind for e in intent.effects)}"
    verdict = "FAIL" if why else ("INFO" if c["gap"] else "PASS")
    return dict(verdict=verdict, why=why, shape=shape, cost=cost, out=r.usage.completion_tokens)


def main():
    repeat = int(os.environ.get("REPEAT", "1"))
    jobs = [(i, c) for i, c in enumerate(CASES) for _ in range(repeat)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda job: (job[0], run_once(job[1])), jobs))
    by_case = {}
    for i, res in results:
        by_case.setdefault(i, []).append(res)
    print(f"модель: {MODEL}, повторов: {repeat}\n")
    failed = 0
    total_cost = 0.0
    for i, runs in sorted(by_case.items()):
        c = CASES[i]
        total_cost += sum(r["cost"] for r in runs)
        verdicts = [r["verdict"] for r in runs]
        mark = "FAIL" if "FAIL" in verdicts else verdicts[0]
        failed += mark == "FAIL"
        flaky = " (нестабильно)" if len(set(verdicts)) > 1 else ""
        print(f"[{mark}]{flaky} {c['state']:<4} «{c['text']}»")
        for r in runs:
            line = r.get("shape", "")
            if r["why"]:
                line += "  !! " + "; ".join(r["why"])
            print(f"        {line}")
    print(f"\nпровалов: {failed} из {len(CASES)}; стоимость прогона ≈ ${total_cost:.3f}")


if __name__ == "__main__":
    main()
