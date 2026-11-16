import asyncio

from app.agents.master.prompting.modules import CORE
from app.core.universal.contracts import ResolutionContext
from app.core.universal.interpretation import compile_exploration
from app.db.models import Entity
from app.rules.universal.exploration import CheckNarration, IntentReview, IntentV2
from tests.test_universal_master import prepare
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
