# ruff: noqa: F811 — shared integration fixtures
"""The first scene exists before the narrator introduces its participants."""

import copy

from app.agents import prelude
from app.db.models import Entity, Event, Scene
from tests.game import party
from tests.test_lead import checked, set_plan
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401


def opening_plan():
    plan = checked()
    plan["acts"][0]["nodes"][0]["npc_ids"] = ["npc_warden"]
    return plan


def test_first_scene_prepares_only_its_npcs_once(game_client, admin_g, llm, settings):  # noqa: F811
    c, _, _ = party(game_client, admin_g)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    plan = opening_plan()
    set_plan(settings, c["id"], plan)
    master = game_client.app.state.master
    where = copy.deepcopy(plan["locations"][0])
    game_client.portal.call(prelude._open_first_place, master, c["id"], where)
    game_client.portal.call(prelude._open_first_place, master, c["id"], where)
    places = rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "location")
    actors = rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "creature")
    assert len(places) == 1
    assert [a.name for a in actors] == ["Бертольд"]
    assert actors[0].location_id == places[0].id
    assert actors[0].state["attitude"] == "neutral"
    assert "Служит культу" not in actors[0].description
    assert len(rows(settings, Event, Event.campaign_id == c["id"], Event.tool == "spawn_entity")) == 1


def test_invalid_opening_npc_rolls_back_scene(game_client, admin_g, llm, settings):  # noqa: F811
    c, _, _ = party(game_client, admin_g)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    plan = opening_plan()
    plan["npcs"][0]["template_id"] = "creature.missing"
    set_plan(settings, c["id"], plan)
    master = game_client.app.state.master
    opened = game_client.portal.call(prelude._open_first_place, master, c["id"], plan["locations"][0])
    assert opened is False
    assert not rows(settings, Entity, Entity.campaign_id == c["id"])


def test_opening_waits_for_committed_scene_preparation(game_client, admin_g, llm, settings, monkeypatch):  # noqa: F811
    from app.db.models import Campaign, WorldGenerationState
    from tests.game import run

    c, _, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, c["id"])
    plan = opening_plan()
    set_plan(settings, c["id"], plan)

    async def enable(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {**campaign.settings, "scene_generation": True}
        await s.commit()

    run(settings, enable)
    settled = []

    async def settle(cid, refs):
        from sqlalchemy import select

        # A fresh session can see the operation only after the opening commit.
        async with master.maker() as s:
            prepared = list(
                await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid))
            )
        assert refs and all(ref in {row.id for row in prepared} for ref in refs)
        settled.extend(refs)
        return []

    monkeypatch.setattr(master, "_settle_preparation", settle)
    assert game_client.portal.call(prelude._open_first_place, master, c["id"], plan["locations"][0])
    assert settled


def test_background_intro_shares_start_lock_and_reuses_prepared_text(
    game_client,
    admin_g,
    llm,
    settings,
    monkeypatch,  # noqa: F811
):
    c, _, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, c["id"])
    set_plan(settings, c["id"], opening_plan())
    calls = []

    async def write(svc, campaign, *_args, **_kwargs):
        calls.append(svc.intro_lock(campaign.id).locked())
        return "Вы ждёте у причала."

    monkeypatch.setattr(prelude, "_intro_text", write)
    assert game_client.portal.call(prelude.prepare_campaign_intro, master, c["id"])
    assert not game_client.portal.call(prelude.prepare_campaign_intro, master, c["id"])
    assert calls == [True]


def test_module_opening_npc_is_registered_in_entered_room(game_client, admin_g, llm, settings):  # noqa: F811
    from app.db.models import CampaignSecret
    from tests.game import run
    from tests.test_adventure import publish_sample

    module_id = publish_sample(settings)
    c, _, _ = party(game_client, admin_g, module_id=module_id, module_hook="board")
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, None)

    async def add_opening_participant(s):
        secret = await s.get(CampaignSecret, c["id"])
        plan = copy.deepcopy(secret.plot)
        node, where = prelude._first_scene(plan)
        node["npc_ids"] = ["noble"]
        secret.plot = plan
        await s.commit()
        return where

    where = run(settings, add_opening_participant)
    opened = game_client.portal.call(prelude._open_first_place, master, c["id"], where)
    assert opened is True
    (scene,) = rows(settings, Scene, Scene.campaign_id == c["id"])
    (actor,) = rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "creature")
    assert actor.location_id == scene.location_id
    assert actor.location_id != where["entity_id"]


def test_hero_intro_receives_registered_scene_and_previous_intro(game_client, admin_g, llm, settings):  # noqa: F811
    from app.db.models import Message
    from tests.game import run

    c, _, _ = party(game_client, admin_g)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    plan = opening_plan()
    set_plan(settings, c["id"], plan)

    async def seed(s):
        s.add(Message(campaign_id=c["id"], seq=100, kind="narration", content="Вы ждёте Бертольда у причала."))
        await s.commit()

    run(settings, seed)
    llm.replies += [{"text": "Герои стоят у причала."}]
    game_client.portal.call(prelude.introduce, game_client.app.state.master, c["id"])
    request = llm.requests[-1]["messages"][1]["content"]
    assert "СЦЕНА: Солёная бухта" in request
    assert "Вы ждёте Бертольда у причала." in request
    (actor,) = rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "creature")
    assert actor.id in request
    (scene,) = rows(settings, Scene, Scene.campaign_id == c["id"])
    assert scene.location_id == actor.location_id
