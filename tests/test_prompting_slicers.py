import asyncio
import json
from copy import deepcopy
from types import SimpleNamespace

from app.agents.llm import LLMReply, ScriptedLLM
from app.agents.master.exploration import obtain_exploration_action
from app.agents.master.prompting.slicers import requested_lore, slice_context
from app.db.models import Campaign, MasterTurn
from tests.test_universal_resolution import setup


def context():
    return {
        "source": "осматриваюсь",
        "world": {},
        "world_rules": {"laws": "Тепло сохраняется.\n\nДвери заперты."},
        "hero": {"abilities": {"wis": 12}, "description": {"identity": "Анна", "past": "x" * 1000}},
        "scene": {"location": {"id": "hall"}, "entities": []},
        "known_exits": [],
        "active_effects": [],
        "resources": {"hp": "20"},
        "objects": [
            {"id": "door", "name": "Дверь", "description": "Первая строка\nПодробности"},
            {"id": "table", "name": "Стол", "description": "Верхняя строка\nПодробности"},
        ],
        "inventory": [],
        "history": [str(i) * 1000 for i in range(8)],
        "established_evidence": "",
    }


def test_slicing_keeps_the_present_whole():
    original = context()
    saved = deepcopy(original)
    sliced = slice_context(original, original["source"])
    for key in ("scene", "known_exits", "source", "active_effects", "resources"):
        assert sliced[key] == original[key]
    assert original == saved
    assert len(sliced["history"]) == 6
    assert all(len(line) <= 400 for line in sliced["history"])


def test_objects_are_trimmed_except_the_named_ones():
    sliced = slice_context(context(), "иду к двери")
    assert "\n" in sliced["objects"][0]["description"]
    assert sliced["objects"][1]["description"] == "Верхняя строка"


def test_lore_index_is_always_present_even_when_no_block_is_relevant():
    sliced = slice_context(context(), "слушаю музыку")
    assert len(sliced["world_rules"]["lore_index"]) == 2
    assert sliced["world_rules"]["lore"] == []


def test_unknown_lore_ids_are_ignored():
    assert requested_lore({"need_lore": ["unknown", "laws:1"]}, context()) == ["laws:1"]
    assert requested_lore({"need_lore": "laws:1"}, context()) == []
    assert requested_lore({"need_lore": [None, {}]}, context()) == []


def test_empty_world_slices_without_error():
    assert slice_context({}, "жду")["world_rules"] == {"lore_index": [], "lore": []}


def test_need_lore_adds_the_requested_blocks_within_the_attempt_budget(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                session.add(MasterTurn(id="t", campaign_id="c", status="running", trace={}))
                await session.commit()
                campaign = await session.get(Campaign, "c")
            llm = ScriptedLLM(
                [
                    LLMReply(text=json.dumps({"need_lore": ["laws:1"]})),
                    LLMReply(
                        text=json.dumps(
                            {
                                "source": "mundane",
                                "player_request": "ordinary",
                                "resolution": "automatic",
                                "effects": [{"kind": "wait"}],
                            }
                        )
                    ),
                ]
            )

            async def ask(purpose, messages):
                return (await llm.complete(messages, model="test")).text

            trace = {}
            result = await obtain_exploration_action(
                SimpleNamespace(maker=maker),
                campaign,
                "t",
                "m",
                trace,
                context(),
                {"user_id": "u", "seat_id": "seat", "actor_id": "hero", "allowed_target_ids": frozenset({"hero"})},
                ask,
            )
            assert result.proposal is not None
            assert len(llm.requests) == 2
            second = json.loads(llm.requests[1]["messages"][-1]["content"])
            assert second["world_rules"]["lore"][0]["id"] == "laws:1"
            assert trace["proposal_attempts"]["m"] == 2
            assert "need_lore" not in result.proposal.model_dump()
        finally:
            await engine.dispose()

    asyncio.run(run())
