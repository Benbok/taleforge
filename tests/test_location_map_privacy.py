"""Персональный доступ к проходам после глобального раскрытия двери."""

import copy
import json

from app.core.layout import store, transit
from app.core.map_memory import discover_passage, observe_area
from app.core.map_projection import location_plan
from app.db.models import Character, MapMemory, PartyMapMemory
from tests.test_layout_passages import _built
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура


def test_secret_reveal_is_shared_by_party(client, admin, settings):
    cid, _heads, hid, village, _root, ids = _built(client, admin, settings, "sacristy", "vault")

    async def setup(ctx):
        first = ctx.world.characters[hid]
        second = Character(
            id="second-map-hero",
            campaign_id=cid,
            name="Второй",
            status="active",
            location_id=village,
            sheet=first.sheet,
            resources=first.resources,
        )
        ctx.session.add(second)
        await ctx.session.flush()
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        await _ok(ctx, "edit_sketch", {"action": "reveal", "target": "Тайная дверь", "location_id": ids["sacristy"]})

    _play(settings, cid, setup)

    async def verify(ctx):
        await _ok(ctx, "move", {"character_ids": ["second-map-hero"], "location_id": ids["sacristy"]})
        from app.core.map_memory import known_passages, known_passages_campaign

        grants = await known_passages(ctx.session, hid, ids["sacristy"])
        root = store.root_of(ctx.world.entities, ctx.world.entities[ids["sacristy"]])
        assert (root.id, "p_vault") in grants
        transit.check(ctx.world, [hid], "p_vault", known_passages=grants)
        second_grants = await known_passages_campaign(ctx.session, cid)
        transit.check(ctx.world, ["second-map-hero"], "p_vault", known_passages=second_grants)
        first_map = await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, ids["sacristy"])
        second_map = await location_plan(
            ctx.session, ctx.world.characters["second-map-hero"], ctx.world.entities, ids["sacristy"]
        )
        assert "p_vault" in str(first_map)
        assert "p_vault" in str(second_map) and "Тайная дверь" in str(second_map)

    _play(settings, cid, verify)


def test_remembered_area_serializes_to_json(client, admin, settings):
    """Запомненный участок уходит в map.state через send_json: время наблюдения — строка ISO, а не datetime."""
    cid, _heads, hid, _village, _root, ids = _built(client, admin, settings, "road", "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["road"]})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        return await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, ids["sacristy"])

    plan = _play(settings, cid, go)
    remembered = [a for a in plan["areas"] if a["status"] == "remembered"]
    assert remembered, "дорога должна остаться в памяти героя"
    assert all(isinstance(a["observed_at"], str) for a in remembered)
    json.dumps(plan)


def test_root_projection_keeps_all_public_areas_before_visit(client, admin, settings):
    cid, _heads, hid, _village, root_id, ids = _built(client, admin, settings, "road")

    async def go(ctx):
        plan = await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, root_id)
        return plan, ids

    plan, ids = _play(settings, cid, go)
    assert plan["here_id"] is None
    assert {area["id"] for area in plan["areas"]} >= set(ids.values()) - {ids["vault"]}
    assert all(area["status"] == "prepared" for area in plan["areas"])
    assert all(not area["sketch"]["features"] for area in plan["areas"])


def test_map_memory_inverse_follows_journal_format(client, admin, settings):
    """Откат памяти: новая строка — delete, изменённое поле — {table, id, field, before}, как в остальном журнале."""
    cid, _heads, hid, _village, root, ids = _built(client, admin, settings, "sacristy", "vault")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        row = await ctx.session.get(MapMemory, (hid, ids["sacristy"]))
        before_snapshot, before_revision = copy.deepcopy(row.snapshot), row.revision
        granted: list = []
        await discover_passage(ctx, root, "p_vault", [hid], granted)
        observed: list = []
        await observe_area(ctx, ids["sacristy"], [hid], observed)
        fresh: list = []
        await discover_passage(ctx, root, "p_vault", ["nobody-yet"], fresh)
        return before_snapshot, before_revision, granted, observed, fresh

    before_snapshot, before_revision, granted, observed, fresh = _play(settings, cid, go)
    key = [hid, ids["sacristy"]]
    assert granted == [{"table": "map_memories", "id": key, "field": "discovered_passages", "before": []}]
    assert observed == [
        {"table": "map_memories", "id": key, "field": "snapshot", "before": before_snapshot},
        {"table": "map_memories", "id": key, "field": "revision", "before": before_revision},
    ]
    assert fresh == []  # героя нет в мире — память не заводится


def _second(ctx, cid, hid, location_id):
    first = ctx.world.characters[hid]
    return Character(
        id="second-map-hero",
        campaign_id=cid,
        name="Второй",
        status="active",
        location_id=location_id,
        sheet=first.sheet,
        resources=first.resources,
    )


def _exit_refs(plan, area_id):
    area = next(a for a in plan["areas"] if a["id"] == area_id)
    return {x.get("passage_ref") for x in area["sketch"].get("exits") or []}


def test_passage_grant_covers_both_ends_and_survives_hide(client, admin, settings):
    """Найденная тайная дверь видна герою с обеих сторон; повторное сокрытие не стирает его знание,
    а герою, не видевшему раскрытия, проход не показывается ни с одной стороны."""
    cid, _heads, hid, village, _root, ids = _built(client, admin, settings, "sacristy", "vault")

    async def join(ctx):
        ctx.session.add(_second(ctx, cid, hid, village))

    _play(settings, cid, join)

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        await _ok(ctx, "edit_sketch", {"action": "reveal", "target": "Тайная дверь", "location_id": ids["sacristy"]})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["vault"]})
        from_vault = await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, ids["vault"])
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        await _ok(ctx, "edit_sketch", {"action": "hide", "target": "Тайная дверь", "location_id": ids["sacristy"]})
        after_hide = await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, ids["sacristy"])
        await _ok(ctx, "move", {"character_ids": ["second-map-hero"], "location_id": ids["vault"]})
        stranger = await location_plan(
            ctx.session, ctx.world.characters["second-map-hero"], ctx.world.entities, ids["vault"]
        )
        return from_vault, after_hide, stranger

    from_vault, after_hide, stranger = _play(settings, cid, go)
    assert "p_vault" in _exit_refs(from_vault, ids["vault"])
    assert "p_vault" in _exit_refs(after_hide, ids["sacristy"])
    assert "p_vault" in str(stranger) and "Тайная дверь" in str(stranger)


def test_left_area_memory_ignores_later_changes(client, admin, settings):
    """Память участка, который герой покинул, не узнаёт об изменениях, сделанных без него;
    свидетель уносит с собой то, что видел перед уходом."""
    cid, _heads, hid, village, _root, ids = _built(client, admin, settings, "road", "sacristy")

    async def join(ctx):
        ctx.session.add(_second(ctx, cid, hid, village))

    _play(settings, cid, join)

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["road"]})
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["sacristy"]})
        before = copy.deepcopy((await ctx.session.get(MapMemory, (hid, ids["road"]))).snapshot)
        await _ok(ctx, "move", {"character_ids": ["second-map-hero"], "location_id": ids["road"]})
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})
        after = (await ctx.session.get(MapMemory, (hid, ids["road"]))).snapshot
        await _ok(ctx, "move", {"character_ids": ["second-map-hero"], "location_id": ids["sacristy"]})
        witness = (await ctx.session.get(MapMemory, ("second-map-hero", ids["road"]))).snapshot
        return before, after, witness

    before, after, witness = _play(settings, cid, go)

    def door(snapshot):
        return next(x for x in snapshot["geometry"]["exits"] if x.get("name") == "Двери храма")["state"]

    assert after == before and door(after) == "closed"
    assert door(witness) == "open"


def test_party_map_memory_survives_personal_memory_removal(client, admin, settings):
    """Общий снимок карты не исчезает вместе с личной памятью героя."""
    cid, _heads, hid, _village, _root, ids = _built(client, admin, settings, "road", "sacristy")

    async def go(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": ids["road"]})
        shared = await ctx.session.get(PartyMapMemory, (cid, ids["sacristy"], ids["road"]))
        assert shared is not None and shared.snapshot is not None
        await ctx.session.delete(await ctx.session.get(MapMemory, (hid, ids["road"])))
        await ctx.session.flush()
        return await location_plan(ctx.session, ctx.world.characters[hid], ctx.world.entities, ids["sacristy"])

    plan = _play(settings, cid, go)
    remembered = next(area for area in plan["areas"] if area["id"] == ids["road"])
    assert remembered["status"] == "remembered"
