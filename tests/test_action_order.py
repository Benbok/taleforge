from app.agents import intent as intents
from app.core.resolution.contracts import ActionProgress, ResolutionResult
from app.db.models import Character, Message
from app.tools.resolution.requests import bind_message_actions, set_action_progress
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


def test_old_intent_without_fields_is_valid():
    a = intents.IntentAction(verb="search", target_id="desk")
    assert a.summary == ""
    assert a.depends_on == []
    raw = {"verb": "interact", "target_id": "door"}
    validated = intents.IntentAction.model_validate(raw)
    assert validated.summary == ""
    assert validated.depends_on == []


def test_cycle_and_missing_part_rejected():
    world = None  # mock
    ch = Character(id="c1", name="Бран", campaign_id="camp1", seat_id="s1")
    raw_cycle = {
        "kind": "action",
        "confidence": 0.95,
        "actions": [
            {"verb": "interact", "target_id": "torch", "depends_on": [{"part": 1, "requires": "applied"}]},
            {"verb": "search", "target_id": "room", "depends_on": [{"part": 0, "requires": "applied"}]},
        ],
    }
    from app.agents.intent import check

    res_cycle = check(raw_cycle, world, ch)
    assert res_cycle.reject is not None or (res_cycle.intent and res_cycle.intent.get("problem") == "unclear")

    raw_missing = {
        "kind": "action",
        "confidence": 0.95,
        "actions": [
            {"verb": "search", "target_id": "room", "depends_on": [{"part": 5, "requires": "applied"}]},
        ],
    }
    res_missing = check(raw_missing, world, ch)
    assert res_missing.reject is not None or (res_missing.intent and res_missing.intent.get("problem") == "unclear")


def test_nine_actions_are_not_silently_truncated():
    world = None
    ch = Character(id="c1", name="Бран", campaign_id="camp1", seat_id="s1")
    raw_nine = {
        "kind": "action",
        "confidence": 0.95,
        "actions": [{"verb": "interact", "target_id": f"obj_{i}"} for i in range(9)],
    }
    from app.agents.intent import check

    res = check(raw_nine, world, ch)
    assert res.reject is not None or (res.intent and res.intent.get("problem") == "unclear")
    if res.intent:
        # Array must NOT be silently sliced to 8 or 4
        assert res.intent.get("actions") is None or res.intent.get("problem") == "unclear"


def test_lighting_dependency_reorders_search(game):
    from app.agents.master.action_order import blocked_dependencies, ready_action_refs

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=501,
            content="зажигаю факел чтобы осмотреть комнату",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "interact", "summary": "зажечь факел", "target_id": "torch"},
                    {
                        "verb": "search",
                        "summary": "осмотреть комнату",
                        "target_id": ch.location_id,
                        "depends_on": [{"part": 0, "requires": "applied"}],
                    },
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Before part 0 is resolved: part 0 is ready, part 1 is blocked by part 0
        ready = ready_action_refs(ctx)
        assert [r.part for r in ready] == [0]
        assert blocked_dependencies(ctx, refs[1]) == [0]

        # Part 0 completes
        res0 = ResolutionResult(execution="applied", game_outcome="success")
        await set_action_progress(ctx, refs[0], ActionProgress(status="completed", result=res0))

        # Now part 1 is unblocked and ready
        ready_after = ready_action_refs(ctx)
        assert [r.part for r in ready_after] == [1]
        assert blocked_dependencies(ctx, refs[1]) == []

    play(settings, campaign_id, [], scenario)


def test_plain_and_does_not_imply_success_dependency(game):
    from app.agents.master.action_order import blocked_dependencies, ready_action_refs

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=502,
            content="бью мечом и осматриваюсь",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "attack", "summary": "ударить мечом", "target_id": "target1"},
                    {"verb": "search", "summary": "осмотреться", "target_id": ch.location_id},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Both parts are ready independently
        ready = ready_action_refs(ctx)
        assert set(r.part for r in ready) == {0, 1}
        assert blocked_dependencies(ctx, refs[0]) == []
        assert blocked_dependencies(ctx, refs[1]) == []

    play(settings, campaign_id, [], scenario)


def test_independent_action_after_denial_is_ready(game):
    from app.agents.master.action_order import blocked_dependencies, ready_action_refs

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=503,
            content="действие 1 и действие 2",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "interact", "summary": "действие 1"},
                    {"verb": "search", "summary": "действие 2"},
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0 is denied
        await set_action_progress(ctx, refs[0], ActionProgress(status="denied"))

        # Part 1 is independent, so it is still ready
        ready = ready_action_refs(ctx)
        assert [r.part for r in ready] == [1]
        assert blocked_dependencies(ctx, refs[1]) == []

    play(settings, campaign_id, [], scenario)


def test_dependent_action_after_denial_is_blocked(game):
    from app.agents.master.action_order import blocked_dependencies, ready_action_refs

    settings, campaign_id, hero = game

    async def scenario(ctx):
        ch = ctx.world.characters[hero]
        msg = Message(
            campaign_id=campaign_id,
            seat_id=ch.seat_id,
            kind="action",
            seq=504,
            content="зажигаю факел чтобы осмотреть комнату",
            intent={
                "confidence": 0.9,
                "actions": [
                    {"verb": "interact", "summary": "зажечь факел"},
                    {
                        "verb": "search",
                        "summary": "осмотреть комнату",
                        "depends_on": [{"part": 0, "requires": "applied"}],
                    },
                ],
            },
        )
        ctx.session.add(msg)
        await ctx.session.flush()
        refs = bind_message_actions(msg, hero)
        ctx.required_actions = list(refs)

        # Part 0 is denied
        await set_action_progress(ctx, refs[0], ActionProgress(status="denied"))

        # Part 1 is blocked because part 0 was denied, not applied
        ready = ready_action_refs(ctx)
        assert ready == []
        assert blocked_dependencies(ctx, refs[1]) == [0]

    play(settings, campaign_id, [], scenario)
