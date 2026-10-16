# The fixture imported from test_tools intentionally shares its name with test args.
# ruff: noqa: F811

import asyncio

from app.agents.master.context_selection import ContextFact
from app.agents.master.prompt_context import collect_narration_facts, public_narration_notes
from tests.test_tools import game, play  # noqa: F401


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


def test_real_narrate_bundle_keeps_public_facts_and_excludes_private_motive(game):
    from app.agents.master.prompt_context import build_prompt_bundle
    from app.db.models import AgentConfig

    settings, cid, hero = game

    async def check(ctx):
        facts = (
            ContextFact(
                "outcome", "outcomes", "PUBLIC_OUTCOME_MARKER", frozenset({"npc"}), frozenset(), frozenset({"party"})
            ),
            ContextFact(
                "relationship",
                "relationships",
                "PUBLIC_RELATIONSHIP_MARKER",
                frozenset({"npc"}),
                frozenset(),
                frozenset({"party"}),
            ),
            ContextFact(
                "promise", "promises", "PUBLIC_PROMISE_MARKER", frozenset({"npc"}), frozenset(), frozenset({"party"})
            ),
            ContextFact(
                "motive", "motives", "PRIVATE_MOTIVE_MARKER", frozenset({"npc"}), frozenset(), frozenset({"master"})
            ),
        )
        bundle = await build_prompt_bundle(
            ctx,
            AgentConfig(persona="STYLE_MARKER", settings={}),
            role="narrate",
            inputs={
                "request": "PLAYER_NEWS",
                "context_facts": facts,
                "subjects": {"npc"},
                "audience": {"party"},
                "history": "HISTORY_BLOCK",
                "packet": "CONFIRMED_OUTCOME_PACKET",
            },
        )
        rendered = str(bundle.messages)
        assert all(
            marker in rendered
            for marker in ("PUBLIC_OUTCOME_MARKER", "PUBLIC_RELATIONSHIP_MARKER", "PUBLIC_PROMISE_MARKER")
        )
        assert "PRIVATE_MOTIVE_MARKER" not in rendered
        assert "STYLE_MARKER" in rendered
        assert "HISTORY_BLOCK" in rendered and "CONFIRMED_OUTCOME_PACKET" in rendered
        assert bundle.version == "context-v2"

    play(settings, cid, [], check)


def test_real_db_snapshot_projects_visible_npc_state_for_narration(game):
    from app.agents.master.context_snapshot import collect_context_snapshot
    from app.tools.registry import execute

    settings, cid, hero = game

    async def check(ctx):
        result = await execute(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.goblin", "name": "Смотритель", "zone": "near"},
        )
        npc_id = result["result"]["spawned"][0]["id"]
        npc = ctx.world.entities[npc_id]
        npc.state = {
            **(npc.state or {}),
            "hp": 10,
            "hp_max": 10,
            "attitude": "neutral",
            "private_state": "PRIVATE_NPC_STATE",
        }
        ctx.narration_viewer_ids = {hero}
        facts = collect_context_snapshot(ctx, None, messages=(), memory="", history="")
        public = next(item.text for item in facts if item.key == f"target:{npc_id}")
        assert "Смотритель" in public
        assert "невредим" in public
        assert "PRIVATE_NPC_STATE" not in public

    play(settings, cid, [], check)
