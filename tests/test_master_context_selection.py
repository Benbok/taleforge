import asyncio

from app.agents.master.context_selection import ContextFact, collect_decision_facts, select_context
from app.agents.master.prompt_context import without_action_context, without_context_block


def f(key, section="scene", text=None, subjects=(), deps=(), audience=("party",), mandatory=False):
    return ContextFact(
        key=key,
        section=section,
        text=text or key,
        subjects=frozenset(subjects),
        dependencies=frozenset(deps),
        audience=frozenset(audience),
        mandatory=mandatory,
    )


def test_dependency_closure_preserves_resources():
    facts = (
        f("action", subjects=("hero",), deps=("resource",), mandatory=True),
        f("resource", section="rules", subjects=("hero",)),
        f("other", subjects=("else",)),
    )
    result = select_context(facts, role="decide", subjects=frozenset({"hero"}), audience=frozenset({"master"}))
    assert [item.key for item in result.facts] == ["action", "resource"]


def test_uncertain_request_keeps_all_parts():
    facts = (f("part-a", subjects=("hero",), mandatory=True), f("part-b", subjects=("npc",)))
    result = select_context(
        facts, role="decide", subjects=frozenset({"hero", "npc"}), audience=frozenset({"master"}), uncertain=True
    )
    assert {item.key for item in result.facts} == {"part-a", "part-b"}
    assert "uncertain_request" in result.expansion_reasons


def test_old_promise_is_mandatory():
    facts = (f("promise", subjects=("npc",), mandatory=True), f("unrelated", subjects=("other",)))
    result = select_context(facts, role="decide", subjects=frozenset({"npc"}), audience=frozenset({"master"}))
    assert [item.key for item in result.facts] == ["promise"]


def test_unknown_dependency_expands_section():
    facts = (f("action", deps=("missing",), mandatory=True), f("rule", section="rules"))
    result = select_context(facts, role="decide", subjects=frozenset(), audience=frozenset({"master"}))
    assert {item.key for item in result.facts} == {"action", "rule"}
    assert "unknown_dependency:missing" in result.expansion_reasons


def test_unrelated_fact_is_omitted():
    facts = (f("current", subjects=("hero",)), f("elsewhere", subjects=("other",)))
    result = select_context(facts, role="decide", subjects=frozenset({"hero"}), audience=frozenset({"master"}))
    assert [item.key for item in result.facts] == ["current"]


def test_private_fact_is_not_visible_to_narrator():
    facts = (f("private", subjects=("hero",), audience=("master",)), f("public", subjects=("hero",)))
    result = select_context(facts, role="narrate", subjects=frozenset({"hero"}), audience=frozenset({"party"}))
    assert [item.key for item in result.facts] == ["public"]


def test_decision_request_does_not_duplicate_action_refs():
    text = "scene\nТекущие части заявок (используй точный action_ref):\n[{\"ref\": \"a\"}]\ncreative"
    assert without_action_context(text) == "scene\ncreative"


def test_decision_request_does_not_duplicate_resolution_block():
    block = "\nRESOLUTION_BLOCK"
    assert without_context_block("scene" + block + "\ncreative", block) == "scene\ncreative"


def test_decision_fact_adapter_always_retains_player_request():
    result = asyncio.run(collect_decision_facts(None, None, {"request": "PLAYER_REQUEST", "context_facts": ()}))
    assert [item.key for item in result] == ["request"]
    assert result[0].mandatory
