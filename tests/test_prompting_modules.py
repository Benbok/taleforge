import re
from pathlib import Path

from app.agents.master.prompting.modules import CORE, MODULES, compose_system, select_modules


def empty_world():
    return {
        "source": "жду",
        "known_exits": [],
        "objects": [],
        "inventory": [],
        "world_rules": {"powers": ""},
        "scene": {"entities": [], "mode": "free"},
        "history": [],
        "active_effects": [],
        "known_abilities": [],
    }


def test_no_sentence_of_the_old_prompt_is_lost():
    old = Path("tests/data/old_exploration_system.txt").read_text(encoding="utf-8").strip()
    rules = Path("docs/prompt-rules.md").read_text(encoding="utf-8").replace("\\|", "|")
    removed = "\n".join(line for line in rules.splitlines() if "убрано" in line)
    retained = CORE + " " + " ".join(module.text for module in MODULES)
    for sentence in re.split(r"(?<=[.!?])\s+", old):
        assert sentence in retained or sentence in removed, sentence


def test_modules_follow_the_state():
    context = empty_world()
    assert select_modules(context) == []
    assert compose_system(context) == CORE
    context["known_exits"] = [{"id": "hall"}]
    assert [module.name for module in select_modules(context)] == ["travel"]


def test_ambiguous_state_includes_the_module():
    context = empty_world()
    del context["objects"]
    assert "objects" in {module.name for module in select_modules(context)}


def test_order_is_fixed():
    assert [module.name for module in select_modules({})] == [
        "travel",
        "objects",
        "magic",
        "speech",
        "combat",
        "rewards",
    ]


def test_explicit_requests_and_active_effects_keep_their_rules():
    context = empty_world()
    context["source"] = "атакую техника"
    assert "combat" in {module.name for module in select_modules(context)}
    context["source"] = "выхожу из формы"
    context["active_effects"] = [{"id": "form"}]
    assert "magic" in {module.name for module in select_modules(context)}
