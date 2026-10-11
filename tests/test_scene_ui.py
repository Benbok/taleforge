# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Интерфейс исследования и включение генерации, поставка 6 (docs/world-objects-delivery6.md, §3): состояние
контейнера на карте и в карточке, явное включение в настройках и фиксация посещённых мест."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.world_generation import storage
from app.db.models import WorldGenerationState
from tests.game import import_base, ok, party, quiet, run
from tests.test_map import _map, _ok, _play
from tests.test_world_generation import _prepare, _room, _row
from tests.test_ws import connect, next_of

WGS = WorldGenerationState


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    monkeypatch.setattr(storage, "RETRY_AFTER", timedelta(0))


def _card(client, head, cid, eid):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "entity.inspect", "payload": {"entity_id": eid}})
        return next_of(ws, "entity.card")["payload"]


def test_container_state_on_map_and_card(client, admin, settings):
    import_base(settings)
    campaign, (p1,), hero = party(client, admin)
    quiet(client)
    cid, hid = campaign["id"], hero["id"]
    room, ref = _room(settings, cid)

    async def move_in(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": room})

    _play(settings, cid, move_in)
    assert _prepare(settings, cid, ref) == "ready"
    chest = next(o["id"] for o in _row(settings, ref).result_manifest["objects"] if o["slot_ref"].startswith("cont"))

    def box():
        thing = next(x for x in _map(client, p1, cid)["around"] if x["id"] == chest)
        card = _card(client, p1, cid, chest)
        assert card["container"] == thing["container"]  # карта и карточка говорят одно
        return thing["container"]

    first = box()
    assert first["contents"] == "unexamined" and first["open"] is False

    async def search(ctx):
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        return (await _ok(ctx, "search_container", {"character_id": hid, "container_id": chest}))["operation_ref"]

    child = _play(settings, cid, search)
    assert box() == {"open": True, "locked": False, "contents": "pending"}
    assert _prepare(settings, cid, child) == "ready"
    assert box()["contents"] == "ready"


def test_enabling_preserves_visited_places_only(client, admin, settings):
    import_base(settings)
    campaign, (p1,), hero = party(client, admin)
    quiet(client)
    cid, hid = campaign["id"], hero["id"]

    async def build(ctx):
        seen = (await _ok(ctx, "create_location", {"name": "Таверна", "make_current": True}))["location_id"]
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": seen})
        fresh = (await _ok(ctx, "create_location", {"name": "Крипта"}))["location_id"]
        return seen, fresh

    seen, fresh = _play(settings, cid, build)

    # не владелец включить не может
    assert client.patch(f"/api/campaigns/{cid}", json={"scene_generation": True}, headers=p1).status_code == 403
    out = ok(client.patch(f"/api/campaigns/{cid}", json={"scene_generation": True}, headers=admin))
    assert out["settings"]["scene_generation"] is True

    def roots():
        found = run(settings, lambda s: s.scalars(select(WGS).where(WGS.campaign_id == cid)))
        return {r.target_entity_id: r for r in found if r.phase == "location_initial"}

    kept = roots()
    assert seen in kept and fresh not in kept
    assert kept[seen].status == "ready" and kept[seen].quality == "legacy_preserved"
    ok(client.patch(f"/api/campaigns/{cid}", json={"scene_generation": True}, headers=admin))
    assert len(roots()) == len(kept)  # повторное включение ничего не добавляет

    async def walk(ctx):
        there = await _ok(ctx, "move", {"character_ids": [hid], "location_id": fresh})
        back = await _ok(ctx, "move", {"character_ids": [hid], "location_id": seen})
        return there, back

    there, back = _play(settings, cid, walk)
    assert "operation_ref" in there  # новое место готовится при входе
    assert "operation_ref" not in back  # посещённое осталось как было
    ok(client.patch(f"/api/campaigns/{cid}", json={"scene_generation_llm": True}, headers=admin))
    patched = ok(client.patch(f"/api/campaigns/{cid}", json={"scene_generation": False}, headers=admin))
    assert patched["settings"]["scene_generation"] is False and patched["settings"]["scene_generation_llm"] is True
