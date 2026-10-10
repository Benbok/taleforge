"""Генерация World Objects: транзакционная фиксация, бюджет, скрытое содержимое и сюжет."""

from __future__ import annotations

from sqlalchemy import select

from app.content.catalog import Catalog, Entry
from app.core import world_generation as gen
from app.db.models import Entity, PlotAnchorBinding, WorldGenerationState
from app.tools.registry import execute
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play


def test_generator_whitelist_budget_and_seed_are_deterministic():
    def entry(eid: str, **fields) -> Entry:
        return Entry(eid, "item_template", fields.pop("status", "canon"), "pack", fields)

    good = entry("item.good", category="gear", price={"gp": 2})
    candidate = entry("item.cheap", category="consumable", rarity="common", price={"sp": 8})
    blocked = [
        entry("item.unique", category="gear", unique=True, price={"gp": 1}),
        entry("item.plot", category="gear", story_gate=True, price={"gp": 1}),
        entry("item.rare", category="gear", rarity="rare", price={"gp": 1}),
        entry("item.service", category="service", price={"gp": 1}),
        entry("item.custom", category="gear", modifiers=[{"op": "custom"}], price={"gp": 1}),
        entry("item.free", category="gear", status="proposal", price={"gp": 1}),
        entry("item.unknown", category="gear", price={"fk": 20}),
        entry("item.no_price", category="gear"),
    ]
    catalog = Catalog({e.id: e for e in [good, candidate, *blocked]}).view(allow_proposals=True)
    profile = gen.LocationProfile((("Сундук", "item:chest"),), tuple(e.id for e in [good, candidate, *blocked]), 250, 3, 2)
    pool = gen.permitted_pool(catalog, profile)
    assert {e.id for e in pool} == {"item.good", "item.cheap"}
    seed = gen.stable_seed("camp", "room", "location_initial", "склад")
    assert seed == gen.stable_seed("camp", "room", "location_initial", "склад")
    assert seed != gen.stable_seed("camp", "other_room", "location_initial", "склад")
    chosen = gen.choose_loot(pool, seed, profile.budget_cp, 3)
    assert [e.id for e in chosen] == [e.id for e in gen.choose_loot(list(reversed(pool)), seed, 250, 3)]
    assert sum(gen.item_price_cp(e) for e in chosen) <= 250
    assert gen.choose_loot([], seed, 0, 2) == []
    assert gen.source_snapshot(pool, "склад", "location_initial")[0] == ["pack"]


def test_location_and_container_generate_once_and_keep_persistent_ids(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid = campaign["id"]

    async def first(ctx):
        room = await _ok(ctx, "create_location", {"name": "Кладовая", "make_current": True})
        room_id = room["location_id"]
        manual = await _ok(ctx, "create_container", {"name": "Ручной сундук"})
        assert not (await ctx.session.scalars(select(WorldGenerationState))).all()
        before_entities = set(ctx.world.entities)
        made = await _ok(ctx, "resolve_location", {"location_id": room_id, "profile": "склад"})
        assert made["ready"] and not made["repeated"] and len(made["containers"]) == 3
        assert set(made["containers"]).isdisjoint(before_entities)
        for item_id in made["items"]:
            obj = ctx.world.entities[item_id]
            assert obj.location_id == room_id
            assert obj.state["world_object"]["generation_ref"]
            if obj.template_id:
                rec = ctx.world.catalog.get(obj.template_id, "item_template")
                assert gen.eligible(rec)
                assert obj.state.get("visual_key") == rec.data.get("visual_key")
        same = await _ok(ctx, "resolve_location", {"location_id": room_id, "profile": "склад"})
        assert same["repeated"] and same["containers"] == made["containers"]
        assert same["items"] == made["items"]
        empty_manual = await _ok(ctx, "resolve_container", {"container_id": manual["container_id"]})
        assert empty_manual["repeated"] and empty_manual["items"] == []
        first_container = made["containers"][0]
        assert ctx.world.entities[first_container].state["world_object"]["contents"]["status"] == "unprepared"
        filled = await _ok(ctx, "resolve_container", {"container_id": first_container})
        repeated = await _ok(ctx, "resolve_container", {"container_id": first_container})
        assert filled["ready"] and not filled["repeated"]
        assert repeated["repeated"] and repeated["items"] == filled["items"]
        assert ctx.world.entities[first_container].state["world_object"]["contents"]["status"] == "ready"
        for item_id in filled["items"]:
            obj = ctx.world.entities[item_id]
            assert obj.state["world_object"]["container_id"] == first_container
        return room_id, made, first_container, filled

    room_id, made, chest, filled = _play(settings, cid, first)
    visible = _map(client, player, cid)
    assert set(made["containers"]).issubset({x["id"] for x in visible["around"]})
    assert all(x["id"] not in {z["id"] for z in visible["around"]} for x in filled["items"])

    async def after(ctx):
        row = await ctx.session.scalar(
            select(WorldGenerationState).where(
                WorldGenerationState.campaign_id == cid,
                WorldGenerationState.target_entity_id == room_id,
                WorldGenerationState.phase == "location_initial",
            )
        )
        assert row.status == "ready"
        assert row.seed is not None and row.context_digest and row.result_digest
        opened = await _ok(ctx, "open_container", {"character_id": hero["id"], "container_id": chest})
        assert opened["opened"]
        contents = await _ok(ctx, "inspect_container", {"character_id": hero["id"], "container_id": chest})
        assert {x["id"] for x in contents["contents"]} == set(filled["items"])
        if filled["items"]:
            moved = await _ok(ctx, "retrieve_object", {
                "character_id": hero["id"], "container_id": chest, "object_id": filled["items"][0]
            })
            assert moved["object_id"] == filled["items"][0]
        repeat = await _ok(ctx, "resolve_container", {"container_id": chest})
        assert repeat["repeated"] and repeat["items"] == filled["items"]
        assert row.status == "ready"

    _play(settings, cid, after)


def test_story_anchor_materializes_once_but_missing_template_stays_reserved(client, admin, settings):
    import_base(settings)
    campaign, _, _ = party(client, admin)
    cid = campaign["id"]

    async def materialize(ctx):
        room = await _ok(ctx, "create_location", {"name": "Склеп", "make_current": True})
        rid = room["location_id"]
        anchor = PlotAnchorBinding(
            campaign_id=cid,
            anchor_id="clue.handwritten-letter",
            plot_ref="story.missing-person",
            target_location_id=rid,
            state="reserved",
            source_snapshot={"item_template_id": "item.potion_of_healing"},
        )
        pending = PlotAnchorBinding(
            campaign_id=cid, anchor_id="clue.secret", plot_ref="story.secret",
            target_location_id=rid, state="reserved", source_snapshot={"text": "только намёк"}
        )
        lost = PlotAnchorBinding(
            campaign_id=cid, anchor_id="clue.lost", plot_ref="story.lost",
            target_location_id=rid, state="lost", source_snapshot={"item_template_id": "item.dagger"}
        )
        ctx.session.add_all([anchor, pending, lost])
        await ctx.session.flush()
        created = await _ok(ctx, "resolve_location", {"location_id": rid, "profile": "склеп"})
        assert created["anchors"] == [anchor.anchor_id]
        assert created["pending_anchors"] == [pending.anchor_id]
        assert anchor.state == "materialized" and anchor.holder_entity_id
        assert pending.state == "reserved" and pending.holder_entity_id is None
        assert lost.state == "lost" and lost.holder_entity_id is None
        created_id = anchor.holder_entity_id
        obj = ctx.world.entities[created_id]
        assert obj.state["world_object"]["unique"] is True
        assert obj.state["visual_key"] == "item:potion"
        again = await _ok(ctx, "resolve_location", {"location_id": rid, "profile": "таверна"})
        assert again["repeated"] and again["anchors"] == [anchor.anchor_id]
        assert anchor.holder_entity_id == created_id
        return rid, created_id

    rid, item_id = _play(settings, cid, materialize)

    async def verify(ctx):
        binding = await ctx.session.scalar(
            select(PlotAnchorBinding).where(PlotAnchorBinding.campaign_id == cid, PlotAnchorBinding.anchor_id == "clue.handwritten-letter")
        )
        assert binding.holder_entity_id == item_id
        assert ctx.world.entities[item_id].location_id == rid

    _play(settings, cid, verify)


def test_invalid_story_reservation_rolls_back_entire_generation(client, admin, settings):
    import_base(settings)
    campaign, _, _ = party(client, admin)
    cid = campaign["id"]

    async def exercise(ctx):
        room = await _ok(ctx, "create_location", {"name": "Зал", "make_current": True})
        rid = room["location_id"]
        ctx.session.add(PlotAnchorBinding(
            campaign_id=cid, anchor_id="clue.invalid", plot_ref="plot.invalid",
            target_location_id=rid, state="reserved", source_snapshot={"item_template_id": "item.missing"}
        ))
        await ctx.session.flush()
        before = set(ctx.world.entities)
        bad = await execute(ctx, "resolve_location", {"location_id": rid, "profile": "дом"})
        assert not bad["ok"] and "сюжетный резерв" in bad["error"]
        assert set(ctx.world.entities) == before
        row = await ctx.session.scalar(
            select(WorldGenerationState).where(WorldGenerationState.target_entity_id == rid)
        )
        assert row is None

    _play(settings, cid, exercise)
