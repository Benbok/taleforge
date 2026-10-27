"""Ordinary deeds on any ability score go through one generic path: the model names the ability, the difficulty and
the outcome words; the code rolls, never special-cases a kind of feat and never charges energy."""

import asyncio

import pytest

from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.interpretation import compile_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Message
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2, RequirementV2
from app.rules.universal.profiles import CheckNarration
from tests.test_universal_resolution import setup

# (ability, what the player said, the effect that carries it, modifier of the test sheet)
FEATS = [
    ("dex", "перепрыгиваю через провал", EffectIntentV2(kind="move", travel_scope="within_scene"), 0),
    (
        "str",
        "выбиваю дверь плечом",
        EffectIntentV2(kind="free_effect", label="Выбитая дверь", appearance="Створка слетела"),
        -1,
    ),
    ("cha", "убеждаю стражника пропустить нас", EffectIntentV2(kind="speak"), 2),
    ("int", "разбираюсь, как устроен механизм", EffectIntentV2(kind="observe"), 1),
]


async def attempt(s, ctx, ability, said, effect, difficulty, keep=None):
    s.add(Message(id="m", campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content=said))
    await s.flush()
    effect = effect.model_copy(update={"required_by": ["req_1"]})
    intent = IntentV2(
        name="Подвиг",
        source="mundane",
        player_request="ordinary",
        resolution="check",
        attribute=ability,
        difficulty=difficulty,
        requirements=[RequirementV2(id="req_1", quote=said, effect=effect.kind)],
        effects=[effect],
        check_outcomes=CheckNarration(
            success="Получилось.", failure="Не вышло.", critical_success="Блестяще.", critical_failure="Катастрофа."
        ),
    )
    action = await compile_exploration(
        ctx,
        intent,
        IntentReview(verdict="pass", covered_requirements=["req_1"]),
        dict(source_message_id="m", source_text=said, evidence=""),
    )
    if keep is not None:
        keep.append(action)
    return await resolve_exploration(ctx, action, "m")


@pytest.mark.parametrize("ability,said,effect,modifier", FEATS)
def test_a_feat_is_rolled_on_the_ability_the_model_named_against_its_difficulty(
    tmp_path, ability, said, effect, modifier
):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            before = (await s.get(Character, "hero")).resources
            won = await attempt(
                s, ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15])), ability, said, effect, 15 + modifier
            )
            assert won.success and won.cost == 0
            proof = won.checks[0]
            assert proof.attribute == ability and proof.modifier == modifier and proof.difficulty == 15 + modifier
            assert (await s.get(Character, "hero")).resources["energies"] == before["energies"]  # no energy for a deed
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("ability,said,effect,modifier", FEATS)
def test_a_failed_feat_changes_nothing_and_is_told_in_the_models_words(tmp_path, ability, said, effect, modifier):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            lost = await attempt(
                s, ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([5])), ability, said, effect, 20
            )
            assert not lost.success and lost.description == "Не вышло."
            assert lost.checks[0].attribute == ability
        await engine.dispose()

    asyncio.run(run())


def test_the_models_words_for_a_successful_feat_lead_the_result_even_when_the_world_changed(tmp_path):
    """The narrator is told what the hero did from the result, so it must not lose the feat to a bare change."""

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            feat = EffectIntentV2(kind="move", travel_scope="within_scene")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15]))
            result = await attempt(s, ctx, "dex", "перепрыгиваю через провал", feat, 12)
            assert result.success and result.changes  # the walk-in-place change is there ...
            assert result.description.startswith("Получилось.")  # ... but the feat comes first
            assert "в пределах текущего места" in result.description
        await engine.dispose()

    asyncio.run(run())


def test_the_models_words_survive_when_it_marked_the_feat_automatic(tmp_path):
    """A model that wrote outcomes but skipped the roll still told what happened; the narrator must get it."""

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            s.add(
                Message(
                    id="m",
                    campaign_id="c",
                    seq=1,
                    seat_id="seat",
                    author_user_id="u",
                    kind="action",
                    content="делаю кульбит",
                )
            )
            await s.flush()
            effect = EffectIntentV2(kind="move", travel_scope="within_scene", required_by=["req_1"])
            intent = IntentV2(
                name="Кульбит",
                source="mundane",
                player_request="ordinary",
                resolution="automatic",
                attribute="dex",
                requirements=[RequirementV2(id="req_1", quote="делаю кульбит", effect="move")],
                effects=[effect],
                check_outcomes=CheckNarration(
                    success="Кульбит вышел чисто.",
                    failure="Оступился.",
                    critical_success="Блестяще.",
                    critical_failure="Упал.",
                ),
            )
            review = IntentReview(verdict="pass", covered_requirements=["req_1"])
            action = await compile_exploration(
                ctx, intent, review, dict(source_message_id="m", source_text="делаю кульбит", evidence="")
            )
            result = await resolve_exploration(ctx, action, "m")
            assert result.success and result.description.startswith("Кульбит вышел чисто.")
        await engine.dispose()

    asyncio.run(run())


def test_a_feat_may_name_the_heros_own_weapon_as_what_it_is_done_with(tmp_path):
    """Driving my cleaver into the rock is a deed with the weapon, not a use of equipment as raw material."""
    from app.core.universal.inventory import create_item
    from app.rules.universal.items import ItemProfile

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            blade = await create_item(s, "c", "hero", ItemProfile(name="Тесак", kind="weapon"), "blade")
            effect = EffectIntentV2(kind="free_effect", label="Тесак вбит в скалу", object_id=blade.id)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18]))
            result = await attempt(s, ctx, "str", "вгоняю тесак в скалу", effect, 15)
            assert result.success and result.checks[0].attribute == "str"
        await engine.dispose()

    asyncio.run(run())


def test_drawing_ones_own_weapon_for_a_feat_is_allowed_and_leaves_the_inventory_alone(tmp_path):
    from sqlalchemy import select

    from app.core.universal.inventory import create_item
    from app.db.models import Entity
    from app.rules.universal.items import ItemProfile

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            blade = await create_item(s, "c", "hero", ItemProfile(name="Тесак", kind="weapon"), "blade")
            said = "вытаскиваю свой тесак и вгоняю его в скалу"
            s.add(
                Message(id="m", campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content=said)
            )
            await s.flush()
            draw = EffectIntentV2(kind="take", object_id=blade.id, required_by=["req_1"])
            drive = EffectIntentV2(kind="free_effect", label="Тесак в скале", object_id=blade.id, required_by=["req_2"])
            intent = IntentV2(
                name="Тесак в скале",
                source="mundane",
                player_request="ordinary",
                resolution="check",
                attribute="str",
                difficulty=15,
                requirements=[
                    RequirementV2(id="req_1", quote="вытаскиваю свой тесак", effect="take"),
                    RequirementV2(id="req_2", quote="вгоняю его в скалу", effect="free_effect"),
                ],
                effects=[draw, drive],
                check_outcomes=CheckNarration(
                    success="Вошёл.", failure="Отскочил.", critical_success="Глубоко.", critical_failure="Выпал."
                ),
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18]))
            review = IntentReview(verdict="pass", covered_requirements=["req_1", "req_2"])
            action = await compile_exploration(
                ctx, intent, review, dict(source_message_id="m", source_text=said, evidence="")
            )
            result = await resolve_exploration(ctx, action, "m")
            assert result.success and result.status == "applied"
            item = (await s.scalar(select(Entity).where(Entity.id == blade.id))).state["universal_item"]
            assert item["owner_id"] == "hero"  # still the hero's, whatever the story says about the rock
        await engine.dispose()

    asyncio.run(run())


def test_a_natural_one_on_a_feat_costs_the_hero_health_once_and_the_story_is_the_models(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hp = int((await s.get(Character, "hero")).resources["hp"])
            effect = EffectIntentV2(kind="move", travel_scope="within_scene")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1]))
            made = []
            lost = await attempt(s, ctx, "dex", "перепрыгиваю через провал", effect, 5, made)
            assert lost.critical_failure and not lost.success  # even a trivial deed fails on a natural one
            assert lost.description.startswith("Катастрофа.")  # the models words lead
            harm = [c for c in lost.changes if c.kind == "damage"]
            assert len(harm) == 1 and harm[0].subject_id == "hero" and harm[0].data["amount"] == "1"
            assert int((await s.get(Character, "hero")).resources["hp"]) == hp - 1
            again = await resolve_exploration(ctx, made[0], "m")
            assert again.status == "repeated"
            assert int((await s.get(Character, "hero")).resources["hp"]) == hp - 1  # a replay does not hurt twice
        await engine.dispose()

    asyncio.run(run())


def test_an_ordinary_failure_or_a_success_leaves_health_alone(tmp_path):
    async def run():
        for dice in ([5], [18]):
            folder = tmp_path / f"d{dice[0]}"
            folder.mkdir()
            engine, maker = await setup(folder)
            async with maker() as s:
                hp = (await s.get(Character, "hero")).resources["hp"]
                effect = EffectIntentV2(kind="move", travel_scope="within_scene")
                await attempt(
                    s, ResolutionContext(s, "c", "u", "seat", "hero", FixedDice(dice)), "dex", "прыгаю", effect, 12
                )
                assert (await s.get(Character, "hero")).resources["hp"] == hp
            await engine.dispose()

    asyncio.run(run())
