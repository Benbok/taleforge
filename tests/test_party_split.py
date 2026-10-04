# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Разделение отряда (design/party-split.md): мастер видит существ там, где стоит каждый герой, а игрок видит
окружение своего места."""

from app.db.models import Campaign
from app.tools.registry import execute
from app.tools.runtime import scene_views
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run
from tests.test_map import _ok, _play
from tests.test_ws import connect


def _split_party(client, admin, settings):
    """Два героя на площади, второй уходит в доки; в доках гоблин, на площади фонтан."""
    import_base(settings)
    c, (p1, p2), h1 = party(client, admin, players=2)
    cid = c["id"]
    h2 = ok(client.post(f"/api/campaigns/{cid}/characters", json={**FIGHTER, "name": "Гимли"}, headers=p2), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{h2['id']}/submit", headers=p2))

    async def build(ctx):
        square = (await _ok(ctx, "create_location", {"name": "Площадь", "make_current": True}))["location_id"]
        docks = (await _ok(ctx, "create_location", {"name": "Доки", "link_to": [square]}))["location_id"]
        fountain = (await _ok(ctx, "add_landmark", {"name": "Фонтан"}))["landmark_id"]
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": docks})
        assert ctx.world.split
        lost = await execute(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        assert not lost["ok"] and "отряд разделён" in lost["error"]
        gob = await _ok(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "location_id": docks}
        )
        return {"square": square, "docks": docks, "fountain": fountain, "gob": gob["spawned"][0]["id"]}

    ids = _play(settings, cid, build)
    return cid, (p1, p2), (h1, h2), ids


def test_master_sees_every_place_of_split_party(client, admin, settings):
    cid, _, (h1, h2), ids = _split_party(client, admin, settings)

    async def check(ctx):
        w = ctx.world
        table = w.scene_table()
        assert "отряд разделён" in table
        assert f"МЕСТО {ids['docks']} Доки: здесь Гимли" in table and f"МЕСТО {ids['square']} Площадь" in table
        # гоблин в доках — допустимая цель, хотя сцена осталась на площади
        assert ids["gob"] in w.valid_ids()["entities"] and w.scene.location_id == ids["square"]
        far = await execute(
            ctx, "resolve_attack", {"attacker_id": h1["id"], "target_id": ids["gob"], "attack": "unarmed"}
        )
        assert not far["ok"] and "в разных местах" in far["error"]
        # бой по умолчанию — только там, где враги
        await _ok(ctx, "set_scene_mode", {"mode": "combat"})
        return {x["id"] for x in w.scene.turn_order}

    assert _play(settings, cid, check) == {h2["id"], ids["gob"]}


def test_each_hero_sees_own_place(client, admin, settings):
    cid, (p1, p2), (h1, h2), ids = _split_party(client, admin, settings)

    with connect(client, p1, cid) as (_, snap):
        scene = snap["payload"]["scene"]
        assert scene["location"]["id"] == ids["square"]
        assert {e["id"] for e in scene["entities"]} == {ids["fountain"]}
    with connect(client, p2, cid) as (_, snap):
        scene = snap["payload"]["scene"]
        assert scene["location"]["id"] == ids["docks"]
        assert {e["id"] for e in scene["entities"]} == {ids["gob"]}
    with connect(client, admin, cid) as (_, snap):  # владелец без героя видит оба места
        assert {e["id"] for e in snap["payload"]["scene"]["entities"]} == {ids["fountain"], ids["gob"]}

    async def views(s):
        from app.tools.runtime import open_context

        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id="t_views", seat_id=None)
        return [(seats, v["location"]["id"], {e["id"] for e in v["entities"]}) for seats, v in scene_views(ctx.world)]

    out = run(settings, views)
    by_place = {loc: (seats, ents) for seats, loc, ents in out}
    assert by_place[ids["docks"]] == ([h2["seat_id"]], {ids["gob"]})
    # мастер и место без героя здесь получают общую сцену; места героев — свою
    assert any(h1["seat_id"] in seats for seats, loc, _ in out if loc == ids["square"])

    # герой вернулся: отряд снова вместе, одна сцена всем
    async def back(ctx):
        await _ok(ctx, "move", {"character_ids": [h2["id"]], "location_id": ids["square"]})
        return ctx.world.split, scene_views(ctx.world)

    split, views_ = _play(settings, cid, back)
    assert not split and len(views_) == 1 and views_[0][0] is None
