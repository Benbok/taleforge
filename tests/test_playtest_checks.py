# ruff: noqa: F811
"""Search results and NPC reactions must follow recorded checks, not narration."""

import pytest

from app.agents.master.searches import unresolved_searches
from app.db.models import Event, KnownFact, MasterTurn
from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_tools import call, game, play  # noqa: F401


async def npc(ctx, name="Стражник"):
    result = await call(
        ctx,
        "spawn_entity",
        {
            "creature_template_id": "creature.commoner",
            "name": name,
            "attitude": "neutral",
        },
    )
    assert result["ok"], result
    return result["result"]["spawned"][0]["id"]


@pytest.mark.parametrize("natural,expected", [(2, False), (19, True)])
def test_npc_attitude_follows_targeted_social_check(game, natural, expected):
    settings, cid, hero = game

    async def fn(ctx):
        target = await npc(ctx)
        check = await call(
            ctx,
            "roll_check",
            {
                "character_id": hero,
                "target_id": target,
                "stat": "persuasion",
                "difficulty": "dc.medium",
                "reason": "просьба о помощи",
            },
        )
        assert check["ok"], check
        assert check["result"]["success"] is expected
        update = await call(ctx, "update_entity", {"entity_id": target, "attitude": "friendly"})
        return update, ctx.world.entities[target].state["attitude"]

    update, attitude = play(settings, cid, [natural], fn)
    assert update["ok"] is expected, update
    assert attitude == ("friendly" if expected else "neutral")


def test_social_check_on_other_npc_cannot_change_attitude(game):
    settings, cid, hero = game

    async def fn(ctx):
        first, other = await npc(ctx), await npc(ctx, "Другой стражник")
        check = await call(
            ctx,
            "roll_check",
            {
                "character_id": hero,
                "target_id": first,
                "stat": "persuasion",
                "difficulty": "dc.easy",
                "reason": "просьба",
            },
        )
        assert check["ok"] and check["result"]["success"], check
        return await call(ctx, "update_entity", {"entity_id": other, "attitude": "friendly"})

    assert not play(settings, cid, [19], fn)["ok"]


def test_attitude_change_without_ground_does_not_block_mood(game):
    settings, cid, _ = game

    async def fn(ctx):
        target = await npc(ctx)
        bad = await call(ctx, "update_entity", {"entity_id": target, "attitude": "friendly"})
        good = await call(ctx, "update_entity", {"entity_id": target, "mood": "усталый"})
        return bad, good

    bad, good = play(settings, cid, [], fn)
    assert not bad["ok"]
    assert good["ok"]


@pytest.mark.parametrize("fact_timing", ["before", "other_target", "after"])
def test_search_result_must_follow_check_and_belong_to_target(game, fact_timing):
    settings, cid, hero = game

    async def fn(ctx):
        target, other = await npc(ctx), await npc(ctx, "Другой NPC")
        fact = {"character_ids": [hero], "subject_id": target, "fact": "У стражника порван рукав."}
        if fact_timing == "before":
            assert (await call(ctx, "learn_fact", fact))["ok"]
        assert (
            await call(
                ctx,
                "roll_check",
                {
                    "character_id": hero,
                    "target_id": target,
                    "stat": "perception",
                    "difficulty": "dc.easy",
                    "reason": "осмотр одежды",
                },
            )
        )["ok"]
        if fact_timing == "other_target":
            assert (await call(ctx, "learn_fact", {**fact, "subject_id": other}))["ok"]
        elif fact_timing == "after":
            assert (await call(ctx, "learn_fact", fact))["ok"]
        return unresolved_searches(ctx)

    assert play(settings, cid, [19], fn) == ([] if fact_timing == "after" else [hero])


def test_repeated_knowledge_without_new_discovery_does_not_close_search(game):
    settings, cid, hero = game

    async def fn(ctx):
        target = await npc(ctx)
        knowledge = {"character_id": hero, "entity_id": target, "level": 3}
        assert (await call(ctx, "reveal_knowledge", knowledge))["ok"]
        assert (
            await call(
                ctx,
                "roll_check",
                {
                    "character_id": hero,
                    "target_id": target,
                    "stat": "perception",
                    "difficulty": "dc.easy",
                    "reason": "новые следы",
                },
            )
        )["ok"]
        assert (await call(ctx, "reveal_knowledge", knowledge))["ok"]
        return unresolved_searches(ctx)

    assert play(settings, cid, [19], fn) == [hero]


def test_unrelated_placed_item_cannot_close_targeted_search(game):
    settings, cid, hero = game

    async def fn(ctx):
        target = await npc(ctx)
        assert (
            await call(
                ctx,
                "roll_check",
                {
                    "character_id": hero,
                    "target_id": target,
                    "stat": "investigation",
                    "difficulty": "dc.easy",
                    "reason": "проверяю одежду NPC",
                },
            )
        )["ok"]
        assert (
            await call(
                ctx,
                "place_item",
                {
                    "item_template_id": "item.dagger",
                    "reason": "другая находка в комнате",
                },
            )
        )["ok"]
        return unresolved_searches(ctx)

    assert play(settings, cid, [19], fn) == [hero]


def test_search_success_returns_to_decider_until_fact_recorded(game_client, admin_g, llm, dice, settings):
    c, (player,), hero = party(game_client, admin_g)
    dice += [19]

    def record_result(messages, _tools):
        assert "Результат исследования" in messages[-1]["content"]
        return {
            "tool_calls": [
                (
                    "learn_fact",
                    {
                        "character_ids": [hero["id"]],
                        "subject_id": hero["id"],
                        "fact": "На двери видны свежие царапины от взлома.",
                    },
                )
            ]
        }

    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "investigation",
                        "difficulty": "dc.easy",
                        "reason": "осмотр",
                    },
                )
            ]
        },
        DONE,
        record_result,
        DONE,
        {"text": "На двери видны свежие царапины от взлома."},
    ]
    result = act(game_client, player, c["id"], "Осматриваю дверь в поисках следов")
    assert "царапины" in result["content"]
    facts = rows(settings, KnownFact, KnownFact.character_id == hero["id"])
    assert any("царапины" in fact.text for fact in facts)
    assert not rows(settings, Event, Event.tool == "cancel_action")


def test_unresolved_search_is_not_allowed_to_invent_keys(game_client, admin_g, llm, dice, settings):
    c, (player,), hero = party(game_client, admin_g)
    dice += [19]
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "investigation",
                        "difficulty": "dc.easy",
                        "reason": "поиск ключа",
                    },
                )
            ]
        },
        DONE,
        DONE,
        {"text": "Вы находите связку ключей и открываете тайник."},
    ]
    result = act(game_client, player, c["id"], "Ищу ключи")
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace.get("unresolved_searches")
    assert rows(settings, Event, Event.tool == "cancel_action")
    assert "находите связку" not in result["content"]
