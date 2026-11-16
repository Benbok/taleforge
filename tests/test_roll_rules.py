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


# --- tool and method discount ---


def deed(**extra):
    return IntentV2(
        source="mundane",
        player_request="ordinary",
        resolution="check",
        attribute="dex",
        difficulty=extra.pop("difficulty", 14),
        check_outcomes=CheckNarration(**OUTCOMES),
        effects=[{"kind": "move", "travel_scope": "within_scene"}],
        **extra,
    )


def discounted(tmp_path, intent, owner="hero", tool_id="pick"):
    from app.core.universal.inventory import create_item
    from app.rules.universal.items import ItemProfile

    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await prepare(maker)
            async with maker() as s:
                row = await create_item(s, "c", owner, ItemProfile(name="Отмычка", kind="weapon"), "pick")
                await s.commit()
                tool = row.id if tool_id == "pick" else tool_id
            async with maker() as s:
                ctx = ResolutionContext(s, "c", **SCOPE, dice=None)
                update = {"tool_item_id": tool} if tool_id else {}
                review = IntentReview(verdict="pass", covered_requirements=[])
                public = dict(source_message_id="source", source_text="Invent a vine sight")
                return await compile_exploration(ctx, intent.model_copy(update=update), review, public)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_a_real_tool_and_a_concrete_method_lower_the_difficulty(tmp_path):
    action = discounted(tmp_path, deed(concrete_method=True))
    assert action.difficulty == 10 and action.tool_item_id


def test_a_tool_alone_lowers_by_two(tmp_path):
    assert discounted(tmp_path, deed()).difficulty == 12


def test_the_difficulty_never_drops_below_five(tmp_path):
    assert discounted(tmp_path, deed(difficulty=6, concrete_method=True)).difficulty == 5


def test_a_foreign_or_unknown_tool_gives_no_discount(tmp_path):
    for name in ("foreign", "ghost"):
        (tmp_path / name).mkdir()
    foreign = discounted(tmp_path / "foreign", deed(), owner="target")
    assert foreign.difficulty == 14 and foreign.tool_item_id is None
    ghost = discounted(tmp_path / "ghost", deed(), tool_id="ghost")
    assert ghost.difficulty == 14 and ghost.tool_item_id is None


def test_a_concrete_method_always_goes_to_the_meaning_review():
    from app.core.universal.interpretation import is_plain_action

    assert is_plain_action(deed())
    assert not is_plain_action(deed(concrete_method=True))


# --- the mishap on a natural 1 ---

from app.core.universal.inventory import create_item, owned_items  # noqa: E402
from app.rules.universal.exploration import EffectIntentV2, FumbleIntent  # noqa: E402
from app.rules.universal.items import ItemProfile  # noqa: E402
from tests.test_universal_mundane_feats import attempt  # noqa: E402

CLIMB = EffectIntentV2(kind="move", travel_scope="within_scene")


def fumbled(tmp_path, fumble, *, effect=CLIMB, hp=None, tool=False, creature=False):
    """A natural one on a feat; returns (hp before, outcome, session facts) after the mishap."""

    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await place(maker)
            async with maker() as s:
                hero = await s.get(Character, "hero")
                if hp is not None:
                    hero.resources = {**hero.resources, "hp": str(hp)}
                if creature:
                    s.add(
                        Entity(
                            id="guard", campaign_id="c", kind="creature", name="Страж", location_id="gorge", state={}
                        )
                    )
                item = (
                    await create_item(s, "c", "hero", ItemProfile(name="Отмычка", kind="weapon"), "pick")
                    if tool
                    else None
                )
                await s.commit()
                before = int(hero.resources["hp"])
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1]))
                told = await attempt(
                    s, ctx, "dex", "лезу по стене", effect, 5, fumble=fumble, tool=item.id if item else None
                )
                after = int((await s.get(Character, "hero")).resources["hp"])
                owned = [row.id for row in await owned_items(s, "c", "hero")]
                guard = await s.get(Entity, "guard") if creature else None
                return before, after, told, owned, (guard.state if guard else None)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_harm_costs_the_chosen_hp(tmp_path):
    before, after, told, _, _ = fumbled(tmp_path, FumbleIntent(kind="harm", amount=2), hp=20)
    assert (before, after) == (20, 18)
    assert [c.data["amount"] for c in told.changes if c.kind == "damage"] == ["2"]


def test_harm_never_drops_below_one_hp(tmp_path):
    before, after, told, _, _ = fumbled(tmp_path, FumbleIntent(kind="harm", amount=3), hp=1)
    assert (before, after) == (1, 1)
    assert not [c for c in told.changes if c.kind == "damage"]


def test_a_broken_tool_leaves_the_inventory(tmp_path):
    _, _, told, owned, _ = fumbled(tmp_path, FumbleIntent(kind="break_tool"), tool=True)
    assert owned == [] and any(c.kind == "tool_broken" for c in told.changes)


def test_breaking_a_tool_that_was_not_used_breaks_nothing(tmp_path):
    _, _, told, _, _ = fumbled(tmp_path, FumbleIntent(kind="break_tool"))
    assert not any(c.kind == "tool_broken" for c in told.changes)


def test_an_alerted_creature_is_marked_and_spots_a_sneaking_hero_more_easily(tmp_path):
    _, _, told, _, state = fumbled(tmp_path, FumbleIntent(kind="alert", creature_id="guard"), creature=True)
    assert state["alerted"] is True and any(c.kind == "alert" for c in told.changes)


def test_words_never_wound(tmp_path):
    before, after, _, _, _ = fumbled(
        tmp_path, FumbleIntent(kind="harm", amount=3), effect=EffectIntentV2(kind="speak"), hp=20
    )
    assert before == after


def test_no_fumble_given_means_no_mishap(tmp_path):
    before, after, _, _, _ = fumbled(tmp_path, None, hp=20)
    assert before == after
