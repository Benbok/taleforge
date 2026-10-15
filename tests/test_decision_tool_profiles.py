# ruff: noqa: F811 -- shared integration fixtures
from types import SimpleNamespace as NS

import pytest

from app.agents.master.common import decision_tools
from app.agents.master.tool_profiles import profile_tool_names, select_tool_profile
from app.db.models import Campaign, Event, MasterTurn
from app.tools.registry import REGISTRY
from tests.game import party, run
from tests.test_master import act, admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_tools import game, play  # noqa: F401


def context(mode="exploration"):
    return NS(
        world=NS(scene=NS(mode=mode), plot={}),
        campaign=NS(settings={}, pack_id=None, pack_version=None, content_chain=[]),
        session=NS(info={}),
        saved_sfx=[],
    )


def message(verbs, **kw):
    return NS(
        intent={"kind": "action", "confidence": 1, "problem": "none", "actions": [{"verb": v} for v in verbs], **kw}
    )


@pytest.mark.parametrize(
    ("verbs", "expected"),
    [
        (["attack"], "combat"),
        (["search"], "exploration"),
        (["persuade"], "social"),
        (["search", "persuade"], "general"),
        (["custom"], "general"),
        ([], "general"),
    ],
)
def test_select_profile_from_existing_intent(verbs, expected):
    assert select_tool_profile(context(), [message(verbs)]) == expected


@pytest.mark.parametrize(
    "bad", [None, {"confidence": 0.2}, {"confidence": "bad"}, {"actions": "invalid"}, {"problem": "unclear"}]
)
def test_uncertain_or_invalid_intent_is_general(bad):
    m = message(["attack"])
    if bad is None:
        m.intent = None
    else:
        m.intent.update(bad)
    assert select_tool_profile(context("combat"), [m]) == "general"


def test_all_profiles_intersect_existing_permissions():
    ctx = context()
    general = set(decision_tools(ctx))
    for profile in ["combat", "exploration", "social", "general", "unknown"]:
        names = profile_tool_names(ctx, profile)
        assert names == sorted(names)
        assert set(names) <= general | {"expand_decision_tools"}
        assert {"get_scene", "get_character", "lookup_template", "cancel_action", "expand_decision_tools"} <= set(names)
        assert not any(REGISTRY[n].internal for n in names if n in REGISTRY)
    assert set(profile_tool_names(ctx, "general")) == general | {"expand_decision_tools"}
    assert profile_tool_names(ctx, "unknown") == profile_tool_names(ctx, "general")


def test_stable_schemas_ignore_world_ids_but_legacy_remains_dynamic():
    from app.tools.registry import tool_specs

    a = NS(valid_ids=lambda: {"characters": ["hero_a"]})
    b = NS(valid_ids=lambda: {"characters": ["hero_b"]})
    names = ["get_character", "cancel_action"]
    assert tool_specs(a, names, dynamic_ids=False) == tool_specs(b, names, dynamic_ids=False)
    assert tool_specs(a, names) != tool_specs(b, names)


def test_expand_is_read_only_and_does_not_close_actions():
    definition = REGISTRY["expand_decision_tools"]
    assert not definition.mutating
    assert not definition.closes_actions
    assert not definition.internal


def test_legacy_decision_tools_excludes_expansion():
    assert "expand_decision_tools" not in decision_tools(context())


def test_native_batch_checks_live_profile_before_and_after_expansion(game_client, admin_g, llm, settings):
    campaign, (player,), hero = party(game_client, admin_g)
    cid = campaign["id"]

    async def enable(s):
        c = await s.get(Campaign, cid)
        c.settings = {**c.settings, "llm_optimization": {"tool_profiles": True}}
        await s.commit()

    run(settings, enable)
    time_args = {"amount": 1, "unit": "minute", "reason": "conversation"}
    llm.replies += [
        {"tool_calls": [("submit_intent", {"confidence": 1, "actions": [{"verb": "talk"}]})]},
        {
            "tool_calls": [
                ("advance_time", time_args),
                ("expand_decision_tools", {"profile": "combat"}),
                ("advance_time", time_args),
                ("expand_decision_tools", {}),
                ("advance_time", time_args),
                ("prepare_location", {}),
                ("apply_narrative_fact", {}),
            ]
        },
        {"tool_calls": [("advance_time", time_args)]},
        {"text": "готово"},
        {"text": "Ты беседуешь."},
        {"text": "Ты беседуешь."},
    ]
    act(game_client, player, cid, "Говорю с собеседником")
    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done", turn.error
    advances = [c["result"] for c in turn.trace["calls"] if c["tool"] == "advance_time"]
    assert len(advances) == 4
    assert not advances[0]["ok"] and not advances[1]["ok"]
    assert advances[2]["ok"] and advances[3]["ok"]
    host = next(c for c in turn.trace["calls"] if c["tool"] == "prepare_location")
    assert not host["result"]["ok"]
    internal = next(c for c in turn.trace["calls"] if c["tool"] == "apply_narrative_fact")
    assert not internal["result"]["ok"]
    decide = [
        r
        for r in llm.requests
        if r.get("tools") and any(t["function"]["name"] == "expand_decision_tools" for t in r["tools"])
    ]
    assert len(decide) >= 3
    assert "advance_time" not in {t["function"]["name"] for t in decide[0]["tools"]}
    assert "advance_time" in {t["function"]["name"] for t in decide[1]["tools"]}
    assert not rows(settings, Event, Event.campaign_id == cid, Event.tool == "expand_decision_tools")


def test_compact_schema_does_not_disable_server_id_validation(game):
    from app.tools.registry import execute, tool_specs

    settings, cid, hero = game

    async def check(ctx):
        assert tool_specs(ctx.world, ["get_character"], dynamic_ids=False)
        result = await execute(ctx, "get_character", {"character_id": "missing_character"})
        assert not result["ok"]

    play(settings, cid, [], check)


def test_dynamic_ids_move_to_deduplicated_context():
    from app.agents.master.tool_profiles import profile_id_context

    ctx = context()
    ctx.world.valid_ids = lambda: {"characters": ["hero_a"]}
    first = profile_id_context(ctx, ["get_character", "cancel_action"])
    assert first == {"characters": ["hero_a"]}
    ctx.world.valid_ids = lambda: {"characters": ["hero_b"]}
    assert profile_id_context(ctx, ["get_character"]) == {"characters": ["hero_b"]}


def test_profile_context_keeps_every_schema_id_namespace(monkeypatch):
    from app.agents.master.tool_profiles import profile_id_context

    names = [name for name, definition in REGISTRY.items() if not definition.internal]
    keys = {key for name in names for key in REGISTRY[name].id_fields.values()}
    assert "dc" in keys
    assert any(k.startswith("templates:") for k in keys)
    assert any(k.startswith("plot:") for k in keys)
    assert any(k.startswith("audio:") for k in keys)
    monkeypatch.setattr("app.tools.registry._enum_values", lambda world, key: [key + "_id"])
    assert profile_id_context(context(), names) == {key: [key + "_id"] for key in sorted(keys)}


def test_narrow_stable_schema_size_is_measured(game):
    from app.core.llm_diagnostics import prompt_sizes
    from app.tools.registry import tool_specs

    settings, cid, hero = game

    async def check(ctx):
        legacy = prompt_sizes({}, tool_specs(ctx.world, decision_tools(ctx)))
        narrow = prompt_sizes({}, tool_specs(ctx.world, profile_tool_names(ctx, "social"), dynamic_ids=False))
        assert narrow["estimate_method"] == "chars/4-ceil"
        assert narrow["tools"]["utf8_bytes"] < legacy["tools"]["utf8_bytes"]
        print("Task3 social/legacy schema sizes:", narrow["tools"], legacy["tools"])

    play(settings, cid, [], check)
