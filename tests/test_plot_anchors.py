# ruff: noqa: F811
"""Сюжетные резервы, поставка 4 (docs/world-objects-delivery4.md, §3): стабильные id зацепок, привязки носителей,
носители в подготовке места и контейнера, пересмотр, утрата и явная привязка."""

from __future__ import annotations

import copy
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.content.catalog import Catalog, Entry
from app.core import plot, plot_anchors
from app.core.world_generation import storage
from app.core.world_generation.policy import build_plan, root_reservation
from app.core.world_generation.profiles import parse_profile
from app.db.models import Campaign, CampaignSecret, Entity, PlotAnchorBinding, WorldGenerationState
from tests.game import import_base, party, quiet, run
from tests.test_map import _ok, _play
from tests.test_plan import FakeCatalog, good_plan
from tests.test_world_generation import _generated, _prepare, _row

WGS = WorldGenerationState
PAB = PlotAnchorBinding


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    monkeypatch.setattr(storage, "RETRY_AFTER", timedelta(0))


class ItemCatalog(FakeCatalog):
    ids = {**FakeCatalog.ids, "item_template": {"item.plot_note", "item.dagger"}}


def _checked(**over) -> dict:
    """Каркас с двумя носителями: журнал на виду в порту и линза, спрятанная на маяке."""
    p = good_plan()
    port, lens = p["reveals"][0]["clues"][1], p["reveals"][1]["clues"][0]
    port["carrier"] = {"name": "Журнал смотрителя", "description": "Последние страницы вырваны"}
    lens["carrier"] = {"name": "Костяная линза", "description": "Холодная, в инее", "hidden": True}
    p.update(over)
    checked, errors = plot.check(p, length="short", catalog=ItemCatalog(), excluded=[])
    assert errors == [], errors
    return checked


def _party(client, admin):
    campaign, heads, hero = party(client, admin)
    quiet(client)
    # These regressions exercise legacy standalone places. New complex routing is
    # covered by test_layout_develop and the map content lifecycle suite.
    response = client.patch(f"/api/campaigns/{campaign['id']}",
                            json={"location_layouts": False, "location_layouts_llm": False}, headers=admin)
    assert response.status_code == 200
    return campaign, heads, hero


def _install(settings, cid, p):
    async def go(s):
        secret = await s.get(CampaignSecret, cid)
        if secret is None:
            secret = CampaignSecret(campaign_id=cid)
            s.add(secret)
        secret.plot = copy.deepcopy(p)
        await plot_anchors.sync_bindings(s, cid, p)
        await s.commit()

    run(settings, go)


def _bindings(settings, cid) -> dict[str, PlotAnchorBinding]:
    async def go(s):
        return {b.anchor_id: b for b in await s.scalars(select(PAB).where(PAB.campaign_id == cid))}

    return run(settings, go)


def _anchor_ids(p) -> tuple[str, str]:
    return p["reveals"][0]["clues"][1]["id"], p["reveals"][1]["clues"][0]["id"]


def test_clue_ids_are_stable_and_carriers_strict():
    p = _checked()
    ids = [c["id"] for r in p["reveals"] for c in r["clues"]]
    assert len(set(ids)) == len(ids) and all(i.startswith("clue_") for i in ids)
    port, _lens = _anchor_ids(p)
    assert p["reveals"][0]["clues"][1]["carrier"] == {
        "name": "Журнал смотрителя",
        "description": "Последние страницы вырваны",
        "hidden": False,
    }
    assert "carrier" not in p["reveals"][0]["clues"][0]  # разговор остаётся текстом
    assert f"[{port}]" in plot.render(p) and "вещь: Журнал смотрителя" in plot.render(p)
    again, errors = plot.check(copy.deepcopy(p), length="short", catalog=ItemCatalog(), excluded=[], keep_state=True)
    assert errors == [] and [c["id"] for r in again["reveals"] for c in r["clues"]] == ids  # id не пересчитываются

    rev = {"acts": copy.deepcopy(p["acts"][1:]), "reveals": [copy.deepcopy(p["reveals"][0])]}
    rev["reveals"][0]["clues"].append({"at": "loc_port", "text": "Новая находка"})
    merged, _ = plot.merge_revision(p, rev)
    merged, errors = plot.check(merged, length="short", catalog=ItemCatalog(), excluded=[], keep_state=True)
    assert errors == []
    clues = merged["reveals"][-1]["clues"] if merged["reveals"][-1]["id"] == "r_cult" else merged["reveals"][0]["clues"]
    assert clues[1]["id"] == port and clues[-1]["id"].startswith("clue_") and clues[-1]["id"] not in ids

    dup = copy.deepcopy(p)
    dup["reveals"][1]["clues"][0]["id"] = port
    assert any("повторяется" in e for e in plot.check(dup, length="short", catalog=ItemCatalog(), excluded=[])[1])
    bad = good_plan()
    bad["reveals"][0]["clues"][1]["carrier"] = {"name": "Вещь", "description": "x", "template_id": "item.nope"}
    assert any("item.nope" in e for e in plot.check(bad, length="short", catalog=ItemCatalog(), excluded=[])[1])


def test_anchor_cost_and_routing_do_not_change_loot():
    good = Entry("item.good", "item_template", "canon", "pack", {"category": "gear"})
    note = Entry("item.plot_note", "item_template", "canon", "pack", {"category": "gear", "not_loot": True})
    catalog = Catalog({e.id: e for e in (good, note)}).view(allow_proposals=False)
    profile = parse_profile(
        Entry(
            "scene_profile.t",
            "scene_profile",
            "canon",
            "pack",
            {
                "schema_version": 1,
                "loot_budget": 30,
                "limits": {"max_generated_entities": 10, "max_item_units": 6, "max_containers": 3, "max_depth": 1},
                "items": [{"template": "item.good", "generation_cost": 2}],
                "containers": [{"slot": "a", "name": "Шкаф"}, {"slot": "b", "name": "Ящик"}],
            },
        ),
        catalog,
    )
    campaign = Campaign(id="c", content_chain=[])
    hidden = {
        "anchor_id": "clue_1",
        "name": "Письмо",
        "description": "",
        "template_id": "item.plot_note",
        "hidden": True,
    }
    seen = {"anchor_id": "clue_2", "name": "Перстень", "description": "", "template_id": "item.good", "hidden": False}
    bare = root_reservation(campaign, "room", profile, [])
    full = root_reservation(campaign, "room", profile, [], [hidden, seen])
    assert full["budget"] == bare["budget"] - 2  # записка — 0, перстень — по профилю
    a, b = build_plan(bare, profile, "room"), build_plan(full, profile, "room")
    loot = lambda plan: [(s.slot_ref, s.template_id) for s in plan.slots if s.anchor_id is None]  # noqa: E731
    assert loot(b) == loot(a)  # носители не сдвигают генератор добычи
    assert {k: v["seed"] for k, v in a.children.items()} == {k: v["seed"] for k, v in b.children.items()}
    assert [s.slot_ref for s in b.slots if s.anchor_id] == ["anchor:clue_2"]
    assert sum(len(c.get("anchors") or []) for c in b.children.values()) == 1
    unknown = root_reservation(campaign, "room", profile, [], [dict(seen, template_id="item.dagger")])
    assert unknown["budget"] == 0 and "unknown_anchor_cost" in unknown["diagnostics"]


def _develop(settings, cid, sketch):
    """Место развёрнуто, но отряд туда не пришёл: вход — отдельным шагом теста."""

    async def go(ctx):
        return (await _ok(ctx, "develop", {"sketch_id": sketch, "details": "-", "here": False}))["entity_id"]

    return _play(settings, cid, go)


def test_visible_carrier_without_generation_flag_and_lost_is_not_restored(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = _party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    p = _checked()
    port_anchor, lens_anchor = _anchor_ids(p)
    _install(settings, cid, p)
    found = _bindings(settings, cid)
    assert set(found) == {port_anchor, lens_anchor} and all(b.state == "reserved" for b in found.values())
    assert found[port_anchor].target_location_id is None  # место ещё не развёрнуто
    port = _develop(settings, cid, "loc_port")
    assert _bindings(settings, cid)[port_anchor].target_location_id == port

    async def enter(ctx):
        return await _ok(ctx, "move", {"character_ids": [hid], "location_id": port})

    entered = _play(settings, cid, enter)
    ref = entered["operation_ref"]
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.reservation["profile_ref"] == "minimal"  # без флага — только сюжет
    made = _generated(settings, ref)
    assert [e.name for e in made] == ["Журнал смотрителя"]
    note = made[0]
    assert note.state["plot_anchor"] == port_anchor and note.state["world_object"]["unique"] is True
    b = _bindings(settings, cid)[port_anchor]
    assert b.state == "materialized" and b.holder_entity_id == note.id
    assert _prepare(settings, cid, ref) == "ready" and len(_generated(settings, ref)) == 1

    async def burn(s):
        await s.delete(await s.get(Entity, note.id))
        await s.commit()

    run(settings, burn)
    _install(settings, cid, p)  # любая запись каркаса сверяет привязки
    assert _bindings(settings, cid)[port_anchor].state == "lost"
    _play(settings, cid, enter)
    assert _generated(settings, ref) == []  # утраченный носитель не восстанавливается


def test_developing_current_place_prepares_it_with_carriers(client, admin, settings):
    """Мастер разворачивает место каркаса прямо под отрядом — отдельного ``move`` не будет: подготовка
    запрашивается сразу, и в её резерве уже есть носитель зацепки этого места."""
    import_base(settings)
    campaign, _heads, _hero = _party(client, admin)
    cid = campaign["id"]
    p = _checked()
    port_anchor, _lens = _anchor_ids(p)
    _install(settings, cid, p)

    async def go(ctx):
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        return await _ok(ctx, "develop", {"sketch_id": "loc_port", "details": "-"})

    out = _play(settings, cid, go)
    assert out["current"] and out["preparation"]["accepted"]
    ref = out["operation_ref"]
    assert [a["anchor_id"] for a in _row(settings, ref).reservation["anchors"]] == [port_anchor]
    assert _prepare(settings, cid, ref) == "ready"
    assert "Журнал смотрителя" in {e.name for e in _generated(settings, ref)}


def test_hidden_carrier_goes_into_container_and_appears_on_search(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = _party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    p = _checked()
    _port, lens_anchor = _anchor_ids(p)
    _install(settings, cid, p)
    light = _develop(settings, cid, "loc_light")

    async def build(ctx):
        out = await _ok(ctx, "resolve_location", {"location_id": light, "profile_id": "scene_profile.warehouse"})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": light})
        return out["operation_ref"]

    ref = _play(settings, cid, build)
    assert _prepare(settings, cid, ref) == "ready"
    assert all(e.state.get("plot_anchor") is None for e in _generated(settings, ref))  # на виду линзы нет
    holders = [r for r in run(settings, lambda s: s.scalars(select(WGS))) if r.phase == "container_contents"]
    (box,) = [r for r in holders if any(a["anchor_id"] == lens_anchor for a in r.reservation.get("anchors") or [])]
    assert _bindings(settings, cid)[lens_anchor].state == "reserved"

    async def search(ctx):
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": box.target_entity_id})
        await _ok(ctx, "search_container", {"character_id": hid, "container_id": box.target_entity_id})

    _play(settings, cid, search)
    assert _prepare(settings, cid, box.id) == "ready"
    lens = [e for e in _generated(settings, box.id) if e.state.get("plot_anchor") == lens_anchor]
    assert len(lens) == 1 and lens[0].state["world_object"]["container_id"] == box.target_entity_id
    assert _bindings(settings, cid)[lens_anchor].holder_entity_id == lens[0].id


def test_revision_updates_reserved_keeps_materialized_and_replaces_removed(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = _party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    p = _checked()
    port_anchor, lens_anchor = _anchor_ids(p)
    _install(settings, cid, p)
    port = _develop(settings, cid, "loc_port")

    async def enter(ctx):
        return (await _ok(ctx, "move", {"character_ids": [hid], "location_id": port}))["operation_ref"]

    assert _prepare(settings, cid, _play(settings, cid, enter)) == "ready"
    secret = run(settings, lambda s: s.get(CampaignSecret, cid))
    revised = copy.deepcopy(secret.plot)
    revised["reveals"][0]["clues"][1]["carrier"]["name"] = "Другой журнал"
    revised["reveals"][1]["clues"][0]["carrier"]["description"] = "Тёплая, светится"
    _install(settings, cid, revised)
    found = _bindings(settings, cid)
    assert found[port_anchor].source_snapshot["carrier"]["name"] == "Журнал смотрителя"  # факт не переписан
    assert found[lens_anchor].source_snapshot["carrier"]["description"] == "Тёплая, светится"
    revised["reveals"][1]["clues"] = revised["reveals"][1]["clues"][1:]
    _install(settings, cid, revised)
    found = _bindings(settings, cid)
    assert found[lens_anchor].state == "replaced_by_story" and found[port_anchor].state == "materialized"

    async def reveal(ctx):
        await _ok(ctx, "plot_reveal", {"reveal_id": "r_cult", "how": "прочли журнал"})

    _play(settings, cid, reveal)
    assert _bindings(settings, cid)[port_anchor].state == "revealed"


def test_late_anchor_appears_on_entering_ready_place_and_explicit_binding(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = _party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    bare = good_plan()
    checked, errors = plot.check(bare, length="short", catalog=ItemCatalog(), excluded=[])
    assert errors == []
    _install(settings, cid, checked)
    port = _develop(settings, cid, "loc_port")

    async def ready_place(ctx):
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        return (await _ok(ctx, "move", {"character_ids": [hid], "location_id": port}))["operation_ref"]

    ref = _play(settings, cid, ready_place)
    assert _prepare(settings, cid, ref) == "ready"
    assert _bindings(settings, cid) == {}  # филлер обязательств не получает

    secret = run(settings, lambda s: s.get(CampaignSecret, cid))
    late = copy.deepcopy(secret.plot)
    clue = late["reveals"][0]["clues"][1]
    clue["carrier"] = {"name": "Подчищенный журнал", "description": "Страницы вырваны", "hidden": False}
    _install(settings, cid, late)
    assert _bindings(settings, cid)[clue["id"]].state == "reserved"

    async def walk(ctx):
        out = await _ok(ctx, "create_location", {"name": "Пирс"})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": out["location_id"]})
        back = await _ok(ctx, "move", {"character_ids": [hid], "location_id": port})
        return back

    back = _play(settings, cid, walk)
    (note,) = back["plot_anchors"]
    b = _bindings(settings, cid)[clue["id"]]
    assert b.state == "materialized" and b.holder_entity_id == note

    # явный адаптер: зацепка без носителя привязывается к существующей вещи, без копии
    other = late["reveals"][1]["clues"][1]["id"]

    async def bind(ctx):
        item = await _ok(ctx, "place_item", {"item_template_id": "item.dagger", "reason": "лежит у алтаря"})
        before = len(ctx.world.entities)
        out = await _ok(ctx, "bind_plot_anchor", {"anchor_id": other, "entity_id": item["entity_id"]})
        assert len(ctx.world.entities) == before and out["state"] == "materialized"
        return item["entity_id"]

    dagger = _play(settings, cid, bind)
    b = _bindings(settings, cid)[other]
    assert b.holder_entity_id == dagger and b.state == "materialized"
    assert run(settings, lambda s: s.get(Entity, dagger)).state["plot_anchor"] == other
