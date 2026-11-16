import asyncio

from sqlalchemy import func, select

from app.agents.master.prompting.modules import CORE
from app.agents.master.service import MasterService
from app.core.universal.contracts import ResolutionContext
from app.core.universal.interpretation import compile_exploration
from app.db.models import AttemptLock, Character, Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import CheckNarration, IntentReview, IntentV2
from tests.test_exploration_master import narrate_prompt
from tests.test_universal_location_knowledge import place
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup

OUTCOMES = dict(
    success="Получилось.",
    failure="Не вышло.",
    critical_success="Блестяще.",
    critical_failure="Совсем плохо.",
)
SCOPE = dict(user_id="u", seat_id="seat", actor_id="hero", allowed_target_ids=frozenset({"hero"}))


def look():
    return IntentV2(
        source="mundane",
        player_request="ordinary",
        resolution="check",
        attribute="wis",
        difficulty=10,
        check_outcomes=CheckNarration(**OUTCOMES),
        effects=[{"kind": "observe"}],
    )


async def compiled(tmp_path, intent, prepare_scene=None):
    engine, maker = await setup(tmp_path)
    try:
        await prepare(maker)
        if prepare_scene:
            async with maker() as s:
                await prepare_scene(s)
                await s.commit()
        async with maker() as s:
            ctx = ResolutionContext(s, "c", **SCOPE, dice=None)
            review = IntentReview(verdict="pass", covered_requirements=[])
            return await compile_exploration(
                ctx, intent, review, dict(source_message_id="source", source_text="Invent a vine sight")
            )
    finally:
        await engine.dispose()


def test_core_no_longer_demands_a_check_for_every_step():
    assert "обычный шаг, слово" not in CORE
    assert "У каждого действия героя в мире есть проверка" not in CORE
    assert "препятств" in CORE


def test_looking_at_what_is_in_plain_sight_is_not_rolled(tmp_path):
    action = asyncio.run(compiled(tmp_path, look()))
    assert action.resolution == "automatic"


def test_searching_where_something_is_hidden_is_rolled(tmp_path):
    async def hide(s):
        from app.db.models import Character

        s.add(Entity(id="hall", campaign_id="c", kind="location", name="Зал"))
        (await s.get(Character, "hero")).location_id = "hall"
        s.add(
            Entity(
                id="lurker", campaign_id="c", kind="creature", name="Тень", location_id="hall", state={"hidden": True}
            )
        )

    action = asyncio.run(compiled(tmp_path, look(), hide))
    assert action.resolution == "check"


# --- one attempt per approach ---


def sneak(attribute="dex", target="guard", **extra):
    """An ordinary deed with a roll aimed at a creature in the hero's place."""
    return dict(
        schema_version=2,
        source="mundane",
        player_request="ordinary",
        resolution="check",
        attribute=attribute,
        difficulty=12,
        check_target=target,
        check_outcomes=OUTCOMES,
        effects=[{"kind": "move", "travel_scope": "within_scene"}],
        **extra,
    )


async def stage(maker, hidden=False):
    await prepare(maker)
    await place(maker)
    async with maker() as s:
        s.add(Entity(id="guard", campaign_id="c", kind="creature", name="Стражник", location_id="gorge"))
        if hidden:
            s.add(
                Entity(
                    id="lurker",
                    campaign_id="c",
                    kind="creature",
                    name="Тень",
                    location_id="gorge",
                    state={"hidden": True},
                )
            )
        await s.commit()


def turn(tmp_path, replies, *, roll, seed=None, hidden=False):
    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await stage(maker, hidden)
            if seed:
                async with maker() as s:
                    s.add(
                        AttemptLock(
                            campaign_id="c", target_id=seed[0], attribute=seed[1], actor_id=seed[2], event_id="old"
                        )
                    )
                    await s.commit()
            async with maker() as s:
                before = dict((await s.get(Character, "hero")).resources["energies"])
            provider = Provider(replies)
            tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([roll])).run_turn("c")
            async with maker() as s:
                locks = [(x.target_id, x.attribute) for x in await s.scalars(select(AttemptLock))]
                events = await s.scalar(select(func.count()).select_from(Event))
                energy = (await s.get(Character, "hero")).resources["energies"]
            return provider, locks, events, energy, before
        finally:
            await engine.dispose()

    return asyncio.run(go())


STORY = ["История.", {"verdict": "pass"}]


def test_a_failed_lockpick_closes_that_approach(tmp_path):
    _, locks, events, _, _ = turn(tmp_path, [sneak(), *STORY], roll=2)
    assert locks == [("guard", "dex")] and events == 1


def test_the_same_approach_is_refused_without_dice_or_cost(tmp_path):
    provider, locks, events, energy, before = turn(tmp_path, [sneak(), *STORY], roll=18, seed=("guard", "dex", "hero"))
    assert events == 0 and locks == [("guard", "dex")]
    assert energy == before
    assert "уже не сработает" in narrate_prompt(provider)


def test_another_ability_on_the_same_target_is_still_open(tmp_path):
    _, _, events, _, _ = turn(tmp_path, [sneak("str"), *STORY], roll=18, seed=("guard", "dex", "hero"))
    assert events == 1


def test_a_closed_approach_is_closed_for_the_whole_party(tmp_path):
    _, _, events, _, _ = turn(tmp_path, [sneak(), *STORY], roll=18, seed=("guard", "dex", "ally"))
    assert events == 0


def test_a_failed_climb_in_the_room_does_not_lock_the_room(tmp_path):
    _, locks, _, _, _ = turn(tmp_path, [sneak("str", target="gorge"), *STORY], roll=2)
    assert locks == []


def test_a_failed_search_of_the_place_locks_the_place(tmp_path):
    search = dict(sneak("wis", target="gorge"), effects=[{"kind": "observe"}])
    _, locks, _, _, _ = turn(tmp_path, [search, *STORY], roll=2, hidden=True)
    assert locks == [("gorge", "wis")]


def test_an_unknown_check_target_is_a_format_error(tmp_path):
    intent = IntentV2.model_validate(sneak(target="nowhere"))

    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await stage(maker)
            async with maker() as s:
                ctx = ResolutionContext(s, "c", **SCOPE, dice=None)
                review = IntentReview(verdict="pass", covered_requirements=[])
                try:
                    await compile_exploration(ctx, intent, review, dict(source_message_id="source", source_text="x"))
                except ValueError as exc:
                    return str(exc)
        finally:
            await engine.dispose()

    assert "check_target" in asyncio.run(go())


def test_the_decision_sees_closed_approaches(tmp_path):
    from app.agents.master.prompting.context import build_decide_context
    from app.db.models import Campaign, Seat

    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await stage(maker)
            async with maker() as s:
                s.add(AttemptLock(campaign_id="c", target_id="guard", attribute="dex", actor_id="hero", event_id="old"))
                await s.commit()
            async with maker() as s:
                context = await build_decide_context(
                    s, await s.get(Campaign, "c"), await s.get(Character, "hero"), await s.get(Seat, "seat"), "x"
                )
                return context["closed_approaches"]
        finally:
            await engine.dispose()

    assert asyncio.run(go()) == [{"target_id": "guard", "attribute": "dex"}]
