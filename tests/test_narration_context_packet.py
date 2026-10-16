import asyncio

from app.agents.master.context_selection import ContextFact
from app.agents.master.prompt_context import collect_narration_facts, public_narration_notes


def test_public_plot_note_requires_explicit_audience():
    notes = [
        {"text": "NPC remembers the promise", "audience": ["party"]},
        {"text": "SECRET ANTAGONIST PLAN", "audience": ["master"]},
        "unclassified internal clock note",
    ]
    assert public_narration_notes(notes) == ["NPC remembers the promise"]


def test_private_plot_note_is_not_leaked_to_public_narration():
    assert public_narration_notes([{"text": "private", "audience": ["hero-a"]}], audience={"party"}) == []


def test_narration_fact_packet_applies_audience_boundary():
    facts = (
        ContextFact("public", "npc", "PUBLIC_MOTIVE", frozenset({"npc"}), frozenset(), frozenset({"party"})),
        ContextFact("secret", "npc", "PRIVATE_MOTIVE", frozenset({"npc"}), frozenset(), frozenset({"master"})),
    )
    result = asyncio.run(collect_narration_facts(None, None, {"context_facts": facts, "subjects": {"npc"}}))
    assert [item.key for item in result] == ["public"]
