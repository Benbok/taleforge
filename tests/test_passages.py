import asyncio

import pytest

from app.agents.master.prompting.modules import CORE
from app.core.universal.map import exit_details
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_mundane_feats import attempt
from tests.test_universal_resolution import setup


def door(state="locked"):
    return {
        "to": "cellar",
        "label": "Дверь в подвал",
        "kind": "door",
        "state": state,
        "hidden": False,
        "universal_passage": "p1",
    }


async def stage(maker, state="locked", far_side=True):
    async with maker() as s:
        s.add(Entity(id="hall", campaign_id="c", kind="location", name="Зал", state={"links": [door(state)]}))
        if far_side:
            back = {**door(state), "to": "hall", "label": "Назад: Дверь в подвал"}
            s.add(Entity(id="cellar", campaign_id="c", kind="location", name="Подвал", state={"links": [back]}))
        (await s.get(Character, "hero")).location_id = "hall"
        await s.commit()


def unlock(tmp_path, *, roll=15, state="locked", to="closed", far_side=True, resolution_override=None):
    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await stage(maker, state, far_side)
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([roll]))
                effect = EffectIntentV2(kind="passage", passage_id="p1", to_state=to)
                told = await attempt(s, ctx, "dex", "вскрываю замок", effect, 10)
                await s.commit()
            async with maker() as s:
                near = (await s.get(Entity, "hall")).state["links"][0]["state"]
                far = (await s.get(Entity, "cellar")).state["links"][0]["state"] if far_side else None
                return told, near, far
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_an_unlocked_door_changes_both_sides(tmp_path):
    told, near, far = unlock(tmp_path)
    assert (near, far) == ("closed", "closed")
    assert any(c.kind == "passage" and c.subject_id == "p1" for c in told.changes)


def test_a_failed_check_leaves_the_door_locked(tmp_path):
    _, near, far = unlock(tmp_path, roll=2)
    assert (near, far) == ("locked", "locked")


def test_breaking_a_blocked_way_opens_it(tmp_path):
    _, near, far = unlock(tmp_path, state="blocked", to="open")
    assert (near, far) == ("open", "open")


def test_a_forbidden_transition_is_a_format_error(tmp_path):
    with pytest.raises(ValueError, match="passage"):
        unlock(tmp_path, state="open", to="closed")


def test_passage_with_missing_far_side_still_opens_here(tmp_path):
    _, near, far = unlock(tmp_path, far_side=False)
    assert near == "closed" and far is None


def test_core_names_passage_not_free_effect_for_a_broken_door():
    assert "выбитая дверь" not in CORE
    assert "passage" in CORE


def test_known_exits_carry_the_passage_id_and_state():
    place = Entity(id="hall", campaign_id="c", kind="location", name="Зал", state={"links": [door()]})
    details = exit_details(place, "cellar")
    assert details["passage_id"] == "p1" and details["state"] == "locked"


def test_a_passage_without_a_roll_is_refused(tmp_path):
    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await stage(maker)
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15]))
                effect = EffectIntentV2(kind="passage", passage_id="p1", to_state="closed")
                with pytest.raises(ValueError, match="resolution=check"):
                    await attempt(s, ctx, "dex", "вскрываю замок", effect, 10, resolution="automatic")
        finally:
            await engine.dispose()

    asyncio.run(go())
