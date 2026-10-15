"""Поставка 1 генерации сцен: footprint, клетки взаимодействия, снятие связи и общая policy видимости и памяти
(docs/world-objects-delivery1.md; спецификация 2026-10-11, §5, §8.2, §10)."""

import json

from app.core import positions as grid
from app.core import reach
from app.db.models import Message
from app.tools.registry import execute
from tests.game import FIGHTER, import_base, ok, party, run
from tests.test_map import _map, _ok, _play
from tests.test_ws import connect, next_of


def _inspect(client, head, cid, eid):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "entity.inspect", "payload": {"entity_id": eid}})
        return next_of(ws, "entity.card")["payload"]


def _room(cols=8, rows=6, party_cell=(1, 1), features=(), exits=()):
    return {
        "shape": "room",
        "cols": cols,
        "rows": rows,
        "party": list(party_cell),
        "walls": [],
        "exits": list(exits),
        "features": list(features),
    }


def _feature_id(ctx, name):
    sk = ctx.world.entities[ctx.world.home()].state["sketch"]
    return next(f["id"] for f in sk["features"] if f["name"] == name)


def test_cabinet_is_one_entity_one_footprint_and_distance_follows_it(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def build(ctx):
        await _ok(ctx, "create_location", {"name": "Лаборатория", "make_current": True})
        box = (await _ok(ctx, "create_container", {"name": "Шкаф"}))["container_id"]
        cabinet = ctx.world.entities[box]
        cabinet.state = {**cabinet.state, "cell": [3, 3]}  # старая точечная позиция токена
        await _ok(ctx, "sketch_place", _room(features=[{"name": "Шкаф", "kind": "furniture", "cells": [[5, 1, 5, 2]]}]))
        fid = _feature_id(ctx, "Шкаф")
        await _ok(ctx, "bind_sketch_feature", {"feature_id": fid, "entity_id": box, "expected_revision": 1})
        assert "cell" not in ctx.world.entities[box].state  # одна позиция — footprint
        assert reach.object_distance(ctx.world, hid, cabinet) == 20  # от строя (1, 1) до ближайшей клетки (5, 1)
        place = ctx.world.entities[ctx.world.home()]
        assert place.state["placement_rev"] == 1
        return box, fid

    box, fid = _play(settings, cid, build)
    view = _map(client, player, cid)
    assert [f["entity_id"] for f in view["sketch"]["features"]] == [box]
    assert box not in {t["id"] for t in view["scene_view"]}  # один визуальный объект
    item = next(x for x in view["around"] if x["id"] == box)
    assert item["cell"] is None and item["zone"] == "near"
    assert view["sketch"]["placement_rev"] == 1

    async def move_party_and_furniture(ctx):
        cabinet = ctx.world.entities[box]
        data = _room(
            party_cell=(4, 4),
            features=[{"id": fid, "entity_id": box, "name": "Шкаф", "kind": "furniture", "cells": [[5, 1, 5, 2]]}],
        )
        await _ok(ctx, "sketch_place", {**data, "expected_revision": 2})
        assert reach.object_distance(ctx.world, hid, cabinet) == 10  # строй сдвинулся, мебель — нет
        data["features"][0]["cells"] = [[1, 4, 1, 4]]
        await _ok(ctx, "sketch_place", {**data, "expected_revision": 3})
        assert reach.object_distance(ctx.world, hid, cabinet) == 15  # перенос пересчитывает footprint
        assert ctx.world.entities[ctx.world.home()].state["placement_rev"] == 2

        chest = (await _ok(ctx, "create_container", {"name": "Сундук"}))["container_id"]
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        await _ok(ctx, "store_object", {"character_id": hid, "container_id": chest, "object_id": box})
        sk = ctx.world.entities[ctx.world.home()].state["sketch"]
        assert sk["features"] == []  # вложение убирает связь и footprint в той же транзакции
        assert reach.object_cells(ctx.world, cabinet) is None
        assert ctx.world.entities[ctx.world.home()].state["placement_rev"] == 3

    _play(settings, cid, move_party_and_furniture)


def test_manual_feature_removal_unlinks_and_keeps_the_entity(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)

    async def exercise(ctx):
        await _ok(ctx, "create_location", {"name": "Кладовая", "make_current": True})
        box = (await _ok(ctx, "create_container", {"name": "Ларь"}))["container_id"]
        await _ok(ctx, "sketch_place", _room(features=[{"name": "Ларь", "cells": [[4, 2, 4, 2]], "entity_id": box}]))
        moved = await execute(ctx, "update_entity", {"entity_id": box, "zone": "far"})
        assert not moved["ok"] and "деталью эскиза" in moved["error"]  # одна позиция: двигают деталь
        await _ok(ctx, "edit_sketch", {"action": "remove", "target": "Ларь", "expected_revision": 1})
        entity = ctx.world.entities[box]
        assert entity.location_id == ctx.world.home()  # вещь осталась в мире несвязанной
        assert grid.pos_of(ctx.world, box).cell == (3, 1)  # на прежнем месте, от строя (1, 1)

    _play(settings, campaign["id"], exercise)


def test_big_table_far_edge_cabinet_back_wall_and_exits(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    hid = hero["id"]

    async def exercise(ctx):
        await _ok(ctx, "create_location", {"name": "Трапезная", "make_current": True})
        table = (await _ok(ctx, "create_container", {"name": "Стол"}))["container_id"]
        cabinet = (await _ok(ctx, "create_container", {"name": "Шкаф"}))["container_id"]
        exit_e = {"name": "Дверь", "side": "e", "at": 5, "kind": "door"}
        features = [
            {"name": "Стол", "kind": "furniture", "cells": [[2, 2, 5, 3]], "entity_id": table},
            {"name": "Шкаф", "kind": "furniture", "cells": [[1, 5, 1, 5]], "entity_id": cabinet, "access_sides": ["e"]},
        ]
        await _ok(ctx, "sketch_place", _room(cols=8, rows=7, party_cell=(0, 0), features=features, exits=[exit_e]))
        w = ctx.world

        # стол 4×2: герой у дальнего от якоря края стоит в 5 футах от ближайшей части и дотягивается в бою
        grid.set_cell(w, hid, (6, 3))
        assert reach.object_distance(w, hid, w.entities[table]) == 5
        assert reach.approach_route(w, hid, w.entities[table], fighting=True) == (None, [])

        # шкаф открывается только с востока: сверху (через заднюю стенку) в бою не дотянуться
        grid.set_cell(w, hid, (1, 4))
        problem, _ = reach.approach_route(w, hid, w.entities[cabinet], fighting=True)
        assert problem and "с доступной стороны" in problem
        # вне боя герой обходит шкаф и открывает его спереди
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": cabinet})
        assert grid.pos_of(w, hid).cell == (2, 5)

        # связанный объект не может загородить выход, к которому можно было пройти
        crate = (await _ok(ctx, "create_container", {"name": "Ящик"}))["container_id"]
        blocked = await execute(
            ctx,
            "edit_sketch",
            {
                "action": "add_feature",
                "feature": {"name": "Ящик", "cells": [[7, 5, 7, 5]], "entity_id": crate},
                "expected_revision": 1,
            },
        )
        assert not blocked["ok"] and "загораживает выход «Дверь»" in blocked["error"]

    _play(settings, campaign["id"], exercise)


def _second_hero(client, cid, head):
    gimli = ok(client.post(f"/api/campaigns/{cid}/characters", json=FIGHTER | {"name": "Гимли"}, headers=head), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{gimli['id']}/submit", headers=head))
    return gimli


def test_hidden_linked_entity_absent_for_another_viewer(client, admin, settings):
    import_base(settings)
    campaign, (p1, p2), hero = party(client, admin, players=2, start=False)
    cid = campaign["id"]
    gimli = _second_hero(client, cid, p2)
    ok(client.post(f"/api/campaigns/{cid}/session/start", headers=admin))

    async def build(ctx):
        await _ok(ctx, "create_location", {"name": "Склеп", "make_current": True})
        stash = (await _ok(ctx, "create_container", {"name": "Тайник за плитой"}))["container_id"]
        feature = {"name": "Тайник за плитой", "cells": [[6, 4, 6, 4]], "entity_id": stash, "hidden": True}
        await _ok(ctx, "sketch_place", _room(features=[feature]))
        assert grid.cell_problem(ctx.world, ctx.world.home(), (5, 3)) == "клетка [6, 4] занята"  # имя не выдаём
        await _ok(
            ctx, "reveal_knowledge", {"character_id": hero["id"], "entity_id": stash, "level": 0, "discovered": True}
        )
        return stash

    stash = _play(settings, cid, build)
    mine, theirs = _map(client, p1, cid), _map(client, p2, cid)
    assert stash in {f.get("entity_id") for f in mine["sketch"]["features"]}
    assert stash in {x["id"] for x in mine["around"]}
    dumped = json.dumps(theirs, ensure_ascii=False)
    assert stash not in dumped and "Тайник" not in dumped  # ни в одном поле ответа
    assert _inspect(client, p2, cid, stash) == {"id": stash, "error": "такого в мире нет"}
    assert _inspect(client, p1, cid, stash)["name"] == "Тайник за плитой"

    async def gimli_tries(ctx):
        r = await execute(ctx, "open_container", {"character_id": gimli["id"], "container_id": stash})
        assert not r["ok"] and "скрыт" in r["error"]

    _play(settings, cid, gimli_tries)


def test_known_item_in_closed_cabinet_is_memory_and_rumour_reveals_nothing(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def build(ctx):
        await _ok(ctx, "create_location", {"name": "Аптека", "make_current": True})
        box = (await _ok(ctx, "create_container", {"name": "Шкаф"}))["container_id"]
        vial = (await _ok(ctx, "place_item", {"item_template_id": "item.dagger", "reason": "на полке"}))["entity_id"]
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": box})
        await _ok(ctx, "store_object", {"character_id": hid, "container_id": box, "object_id": vial})
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": box, "opened": False})
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": box})  # видел внутри
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": box, "opened": False})
        hidden = (await _ok(ctx, "create_container", {"name": "Потайной ящик"}))["container_id"]
        ctx.world.entities[hidden].state = {**ctx.world.entities[hidden].state, "hidden": True}
        ctx.world.entities[vial].description = "Клинок покрылся ржавчиной"  # изменилось уже после наблюдения
        return vial, hidden

    vial, hidden = _play(settings, cid, build)
    card = _inspect(client, player, cid, vial)
    assert card["memory"] is True and card["description"] != "Клинок покрылся ржавчиной"
    assert "condition" not in card and "stats" not in card

    async def rumour(s):
        from app.core.chat import next_seq

        s.add(Message(campaign_id=cid, seq=await next_seq(s, cid), kind="narration",
                      content=f"Говорят, в аптеке есть [[{hidden}|потайной ящик]]."))  # fmt: skip
        await s.commit()

    run(settings, rumour)
    heard = _inspect(client, player, cid, hidden)
    assert heard["memory"] is True and heard["description"] is None  # слух — память, не обнаружение
    view = _map(client, player, cid)
    assert hidden not in json.dumps(view, ensure_ascii=False)
