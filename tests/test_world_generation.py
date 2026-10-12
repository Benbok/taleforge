# ruff: noqa: F811
"""Подготовка исследуемых сцен, поставка 3 (docs/world-objects-delivery3.md, §3): профили, дерево бюджета,
lease/CAS, атомарная материализация, исследование контейнера и ожидание подготовки в ходе."""

from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.content.catalog import Catalog, Entry
from app.core import world_tx
from app.core.narrative.contracts import FactRef, SnapshotRef
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked, Proposal, ProposedObject
from app.core.world_generation.policy import build_plan, child_seed, root_reservation
from app.core.world_generation.profiles import MINIMAL, ProfileError, eligible, load_profile, parse_profile
from app.core.world_generation.service import Orchestrator
from app.core.world_generation.validation import validate
from app.db.models import Campaign, Character, Entity, Event, NarrativeFact, WorldGenerationState, now
from app.db.session import make_engine, make_sessionmaker
from app.gateway.coordination import InMemoryCoordination
from app.tools.registry import execute
from tests.game import import_base, party, quiet, run
from tests.test_map import _ok, _play
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода

WGS = WorldGenerationState


@pytest.fixture(autouse=True)
def _fast_retry(monkeypatch):
    monkeypatch.setattr(storage, "RETRY_AFTER", timedelta(0))


def _with_maker(settings, fn):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            return await fn(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def _prepare(settings, cid, ref, orchestrator=None):
    orch = orchestrator or Orchestrator(InMemoryCoordination())
    return _with_maker(settings, lambda maker: orch.prepare(maker, cid, ref))


def _row(settings, ref) -> WorldGenerationState:
    return run(settings, lambda s: s.get(WGS, ref))


def _generated(settings, ref) -> list[Entity]:
    async def go(s):
        found = (await s.scalars(select(Entity).where(Entity.kind == "object"))).all()
        return [e for e in found if ((e.state or {}).get("world_object") or {}).get("generation_ref") == ref]

    return run(settings, go)


def _room(settings, cid, name="Склад", profile="scene_profile.warehouse"):
    """Место, назначенный профиль и принятая подготовка."""

    async def build(ctx):
        room = (await _ok(ctx, "create_location", {"name": name, "make_current": True}))["location_id"]
        out = await _ok(ctx, "resolve_location", {"location_id": room, "profile_id": profile})
        return room, out["operation_ref"]

    return _play(settings, cid, build)


# --- профиль ---


def _entry(eid: str, kind: str = "item_template", **data) -> Entry:
    return Entry(eid, kind, data.pop("status", "canon"), "pack", data)


def _profile(**over):
    data = {
        "schema_version": 1,
        "loot_budget": 20,
        "visible_share": 30,
        "limits": {"max_generated_entities": 10, "max_item_units": 6, "max_containers": 3, "max_depth": 2},
        "items": [{"template": "item.good", "generation_cost": 2}],
        "containers": [{"slot": "chest", "name": "Сундук", "visual_key": "item:chest"}],
        "inner_containers": [{"slot": "box", "name": "Шкатулка"}],
    }
    return _entry("scene_profile.test", "scene_profile", **(data | over))


def _catalog(*extra: Entry):
    good = _entry("item.good", category="gear")
    entries = [good, _entry("item.rare", category="gear", rarity="rare"), *extra]
    return Catalog({e.id: e for e in entries}).view(allow_proposals=False)


def test_profile_is_strict_and_minimal_has_no_loot(settings):
    catalog = _catalog()
    profile = parse_profile(_profile(), catalog)
    assert profile.budget == 20 and profile.items[0].cost == 2 and profile.limits.depth == 2
    for bad in (
        _profile(surprise=1),
        _profile(items=[{"template": "item.good", "generation_cost": 0}]),
        _profile(items=[{"template": "item.missing", "generation_cost": 1}]),
        _profile(items=[{"template": "item.rare", "generation_cost": 1}]),
        _profile(limits={"max_generated_entities": 1}),
        _profile(schema_version=2),
    ):
        with pytest.raises(ProfileError):
            parse_profile(bad, catalog)
    assert load_profile(catalog, None) is MINIMAL and load_profile(catalog, "minimal") is MINIMAL
    with pytest.raises(ProfileError):
        load_profile(catalog, "scene_profile.unknown")
    campaign = Campaign(id="c1", content_chain=[])
    res = root_reservation(campaign, "room", MINIMAL, [])
    plan = build_plan(res, MINIMAL, "room")
    assert res["budget"] == 0 and plan.slots == [] and plan.children == {}

    # базовый пакет: все профили проходят строгую проверку, шаблоны — только допустимая добыча
    import_base(settings)

    async def base(s):
        from app.content.catalog import campaign_catalog

        cat = await campaign_catalog(s, Campaign(id="probe", content_chain=[]))
        found = cat.by_kind("scene_profile")
        assert len(found) == 8
        for entry in found:
            p = parse_profile(entry, cat)
            assert p.items and all(eligible(cat.get(r.template, "item_template")) for r in p.items)

    run(settings, base)


def _walk(res, profile, target="t", depth=0):
    plan = build_plan(res, profile, target)
    total = plan.spent + sum(int(c["budget"]) for c in plan.children.values())
    assert total <= int(res["budget"])
    out = [(res["path"], plan.spent, int(res["budget"]))]
    for ref, child in plan.children.items():
        assert int(child["budget"]) < int(res["budget"]) or int(res["budget"]) == 0
        assert child["depth"] == res["depth"] - 1 and child["seed"] == child_seed(int(res["seed"]), ref)
        out += _walk(child, profile, f"{target}/{ref}", depth + 1)
    return out


def test_budget_tree_shares_and_stable_seeds():
    catalog = _catalog()
    profile = parse_profile(_profile(loot_budget=40), catalog)
    campaign = Campaign(id="camp", content_chain=[])
    res = root_reservation(campaign, "room", profile, [])
    tree = _walk(res, profile)
    assert len(tree) > 2  # корень, контейнеры, вложенные
    assert sum(spent for _path, spent, _budget in tree) <= 40
    assert _walk(res, profile) == tree  # тот же резерв — тот же план, порядок обхода не важен
    assert root_reservation(campaign, "other", profile, [])["seed"] != res["seed"]
    # авторская добыча учитывается первой; шаблон вне профиля обнуляет остаток
    assert root_reservation(campaign, "room", profile, ["item.good"])["budget"] == 38
    unknown = root_reservation(campaign, "room", profile, ["item.dagger"])
    assert unknown["budget"] == 0 and unknown["diagnostics"] == ["unknown_authored_cost"]


def test_validation_accepts_only_plan_slots():
    catalog = _catalog()
    profile = parse_profile(_profile(loot_budget=40), catalog)
    plan = build_plan(root_reservation(Campaign(id="c", content_chain=[]), "r", profile, []), profile, "r")
    good = tuple(ProposedObject(s.slot_ref, s.role, s.name or "Вещь", "", s.template_id) for s in plan.slots)
    validate(plan, Proposal(1, good))
    item = next(o for o in good if o.role == "item")
    for objects in (
        (*good, ProposedObject("item:99", "item", "Лишнее", "", "item.good")),
        tuple(o for o in good if o is not item),
        tuple(ProposedObject(o.slot_ref, o.role, o.name, "", "item.rare") if o is item else o for o in good),
        tuple(ProposedObject(o.slot_ref, o.role, "x" * 200, "", o.template_id) if o is item else o for o in good),
    ):
        with pytest.raises(Blocked):
            validate(plan, Proposal(1, objects))


# --- исполнение ---


def test_location_prepares_once_with_reserves_for_children(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    room, ref = _room(settings, cid)
    assert _row(settings, ref).requested_at is not None
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.status == "ready" and row.result_digest and row.attempt_count == 1
    made = _generated(settings, ref)
    assert {o["id"] for o in row.result_manifest["objects"]} == {e.id for e in made}
    assert all(e.location_id == room for e in made)
    children = run(settings, lambda s: s.scalars(select(WGS).where(WGS.phase == "container_contents")))
    children = list(children)
    assert children and set(row.result_manifest["children"].values()) == {c.id for c in children}
    assert all(c.status == "unprepared" and c.requested_at is None for c in children)
    total = row.result_manifest["spent"] + sum(c.reservation["budget"] for c in children)
    assert total <= row.reservation["budget"]
    assert _prepare(settings, cid, ref) == "ready"  # повтор ничего не создаёт
    assert len(_generated(settings, ref)) == len(made)
    events = rows(settings, Event, Event.tool == "prepare_scene")
    assert len(events) == 1 and events[0].hidden


def test_concurrent_preparation_makes_one_result(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)

    async def both(maker):
        a, b = Orchestrator(InMemoryCoordination()), Orchestrator(InMemoryCoordination())
        return await asyncio.gather(a.prepare(maker, cid, ref), b.prepare(maker, cid, ref))

    outcomes = _with_maker(settings, both)
    assert "ready" in outcomes and set(outcomes) <= {"ready", "leased"}
    row = _row(settings, ref)
    assert {o["id"] for o in row.result_manifest["objects"]} == {e.id for e in _generated(settings, ref)}
    assert len(rows(settings, Event, Event.tool == "prepare_scene")) == 1


def test_expired_lease_is_taken_over_and_old_owner_cannot_write(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)
    stale = _with_maker(settings, lambda maker: storage.claim(maker, cid, ref))
    assert isinstance(stale, storage.Claim)
    assert _prepare(settings, cid, ref) == "leased"  # живой lease чужой

    async def expire(s):
        (await s.get(WGS, ref)).lease_until = now() - timedelta(seconds=1)
        await world_tx.world_write(s, cid)
        await s.commit()

    run(settings, expire)
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.attempt_count == 2  # счётчики не обнуляются при перехвате

    async def late(maker):
        orch = Orchestrator(InMemoryCoordination())
        draft = await orch._plan(maker, stale)
        with pytest.raises((storage.LeaseLost, world_tx.WorldConflict)):
            await storage.commit_result(maker, orch.dice_factory, stale, draft.plan, draft.proposal)

    _with_maker(settings, late)
    assert len(rows(settings, Event, Event.tool == "prepare_scene")) == 1


def test_failure_mid_insert_rolls_back_everything_and_retry_keeps_seed(client, admin, settings, monkeypatch):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)
    reservation = dict(_row(settings, ref).reservation)

    from app.tools.master import items

    real = items._put_in_scene
    calls = []

    async def broken(*args, **kw):
        calls.append(1)
        if len(calls) == 1:  # обстановка уже вставлена, первая находка падает
            raise RuntimeError("диск отвалился")
        return await real(*args, **kw)

    monkeypatch.setattr(items, "_put_in_scene", broken)
    assert _prepare(settings, cid, ref) == "blocked"
    row = _row(settings, ref)
    assert row.last_error == "internal_error" and len(calls) == 1
    assert _generated(settings, ref) == [] and rows(settings, WGS, WGS.phase == "container_contents") == []
    monkeypatch.setattr(items, "_put_in_scene", real)

    async def again(ctx):
        return await _ok(ctx, "retry_preparation", {"operation_ref": ref})

    assert _play(settings, cid, again)["operation_ref"] == ref
    row = _row(settings, ref)
    assert row.status == "unprepared" and row.reservation == reservation and row.seed == reservation["seed"]
    assert _prepare(settings, cid, ref) == "ready"


def test_world_change_conflicts_then_stale_context_and_retry(client, admin, settings, monkeypatch):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)
    real = Orchestrator._plan
    seen = []

    async def racing(self, maker, claim):
        out = await real(self, maker, claim)
        seen.append(claim.ref)
        async with maker() as s:  # кто-то изменил мир между снимком и записью
            await world_tx.world_write(s, cid)
            await s.commit()
        return out

    monkeypatch.setattr(Orchestrator, "_plan", racing)
    assert _prepare(settings, cid, ref) == "blocked"
    row = _row(settings, ref)
    assert len(seen) == 2 and row.last_error == "stale_context" and row.conflict_count == 2
    assert _generated(settings, ref) == []
    monkeypatch.setattr(Orchestrator, "_plan", real)

    async def again(ctx):
        return await _ok(ctx, "retry_preparation", {"operation_ref": ref})

    _play(settings, cid, again)
    assert _row(settings, ref).conflict_count == 0
    assert _prepare(settings, cid, ref) == "ready"


def test_recovery_prepares_only_requested_phases(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)
    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))
    assert _row(settings, ref).status == "ready"
    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))
    for child in rows(settings, WGS, WGS.phase == "container_contents"):
        assert child.status == "unprepared" and child.requested_at is None  # закрытое неисследованное не трогаем


# --- исследование контейнера ---


def test_search_container_charges_once_and_reads_ready_contents(client, admin, settings, monkeypatch):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    quiet(client)
    cid, hid = campaign["id"], hero["id"]
    room, ref = _room(settings, cid)

    async def move_in(ctx):
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": room})

    _play(settings, cid, move_in)
    assert _prepare(settings, cid, ref) == "ready"
    chest = next(o["id"] for o in _row(settings, ref).result_manifest["objects"] if o["slot_ref"].startswith("cont"))
    child = run(settings, lambda s: s.scalar(select(WGS).where(WGS.target_entity_id == chest)))

    from app.tools.master import generation

    charged = []
    real_charge = generation.economy.charge

    def counting(ctx, hero_id, kind, bonus=False):
        charged.append((hero_id, kind))
        return real_charge(ctx, hero_id, kind, bonus)

    monkeypatch.setattr(generation.economy, "charge", counting)

    async def first(ctx):
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        peek = await _ok(ctx, "inspect_container", {"character_id": hid, "container_id": chest})
        assert peek["contents"] is None and peek["note"] == "не исследован"
        loose = await _ok(ctx, "place_item", {"item_template_id": "item.torch", "reason": "лежит на полу"})
        stored = await execute(
            ctx, "store_object", {"character_id": hid, "container_id": chest, "object_id": loose["entity_id"]}
        )
        assert not stored["ok"] and "не исследовано" in stored["error"]
        a = await execute(ctx, "search_container", {"character_id": hid, "container_id": chest}, key="s:1")
        assert a["ok"] and a["result"] == {"container_id": chest, "accepted": True, "operation_ref": child.id}
        assert a["status"]["status"] == "pending" and child.id in ctx.operation_refs and hid in ctx.closed
        b = await execute(ctx, "search_container", {"character_id": hid, "container_id": chest}, key="s:2")
        assert b["result"] == a["result"]  # тот же герой, новый ключ: исходная квитанция

        other = Character(
            campaign_id=cid,
            name="Другой",
            status="approved",
            location_id=room,
            sheet=dict(ctx.world.characters[hid].sheet),
        )
        ctx.session.add(other)
        await ctx.session.flush()
        ctx.world.characters[other.id] = other
        c = await _ok(ctx, "search_container", {"character_id": other.id, "container_id": chest})
        assert c["status"] == "pending" and c["operation_ref"] == child.id
        return other.id

    _play(settings, cid, first)
    assert charged == [(hid, "search")]
    assert _prepare(settings, cid, child.id) == "ready"
    items = {o["id"] for o in _row(settings, child.id).result_manifest["objects"]}

    async def ready(ctx):
        seen = await _ok(ctx, "search_container", {"character_id": hid, "container_id": chest})
        assert seen["status"] == "ready" and {x["id"] for x in seen["contents"]} == items
        peek = await _ok(ctx, "inspect_container", {"character_id": hid, "container_id": chest})
        assert {x["id"] for x in peek["contents"]} == items
        for item in items:
            await _ok(ctx, "retrieve_object", {"character_id": hid, "container_id": chest, "object_id": item})
        again = await _ok(ctx, "search_container", {"character_id": hid, "container_id": chest})
        assert again["contents"] == []  # вынесли — новой добычи нет

    _play(settings, cid, ready)
    assert charged == [(hid, "search")]
    assert _prepare(settings, cid, child.id) == "ready"
    assert {e.id for e in _generated(settings, child.id)} == items


def test_move_requests_preparation_only_with_campaign_flag(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    quiet(client)
    cid, hid = campaign["id"], hero["id"]

    async def go(ctx):
        cellar = (await _ok(ctx, "create_location", {"name": "Погреб"}))["location_id"]
        off = await _ok(ctx, "move", {"character_ids": [hid], "location_id": cellar})
        assert "operation_ref" not in off
        hall = (await _ok(ctx, "create_location", {"name": "Зал"}))["location_id"]
        assert await storage.find(ctx.session, cid, hall, "location_initial") is None  # навигатор не активируется
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        on = await execute(ctx, "move", {"character_ids": [hid], "location_id": hall})
        assert on["ok"] and on["result"]["preparation"]["accepted"] and on["status"]["status"] == "pending"
        back = await _ok(ctx, "move", {"character_ids": [hid], "location_id": cellar})
        again = await _ok(ctx, "move", {"character_ids": [hid], "location_id": hall})
        assert "operation_ref" in back and "operation_ref" not in again
        row = await storage.find(ctx.session, cid, hall, "location_initial")
        assert row.profile_ref == "minimal"  # без профиля шаблона и ведущего
        return row.id

    ref = _play(settings, cid, go)
    assert _prepare(settings, cid, ref) == "ready"
    assert _row(settings, ref).result_manifest["objects"] == []


def test_new_current_location_is_prepared_without_move(client, admin, settings):
    """Мастер создаёт место сразу текущим — отряд уже там, отдельного ``move`` не будет."""
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]

    async def go(ctx):
        off = await _ok(ctx, "create_location", {"name": "Пустырь", "make_current": True})
        assert "operation_ref" not in off  # без флага кампании — как раньше
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        aside = (await _ok(ctx, "create_location", {"name": "Маяк"}))["location_id"]
        assert await storage.find(ctx.session, cid, aside, "location_initial") is None  # не текущее — не готовится
        docks = await _ok(
            ctx, "create_location", {"name": "Доки", "template_id": "location.port", "make_current": True}
        )
        assert docks["preparation"]["accepted"]
        return docks["operation_ref"]

    ref = _play(settings, cid, go)
    assert _prepare(settings, cid, ref) == "ready"
    assert _row(settings, ref).profile_ref == "scene_profile.warehouse"  # профиль по шаблону места
    assert _generated(settings, ref)


def test_turn_waits_for_generated_scene_and_describes_it(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid, hid = c["id"], hero["id"]

    async def build(ctx):
        room = (await _ok(ctx, "create_location", {"name": "Таверна у моста"}))["location_id"]
        ctx.world.entities[room].state = {
            **(ctx.world.entities[room].state or {}),
            "scene_profile": "scene_profile.tavern",
        }
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        return room

    room = _play(settings, cid, build)
    llm.replies += [
        {"tool_calls": [("move", {"character_ids": [hid], "location_id": room})]},
        DONE,
        {"text": "Таверна шумит."},
    ]
    told = act(game_client, p1, cid, "Захожу в таверну")
    assert told["kind"] == "narration"
    (row,) = rows(settings, WGS, WGS.phase == "location_initial")
    assert row.status == "ready" and row.result_manifest["objects"]
    names = {e.name for e in _generated(settings, row.id)}
    narrate = llm.requests[-1]["messages"]
    assert any(n in str(narrate) for n in names)  # описание видит уже готовую обстановку
    assert "исследование пока недоступно" not in str(narrate)


def test_commit_result_with_used_fact_refs(client, admin, settings):
    """commit_result seals both string and dict used_fact_refs without ValidationError."""
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]
    _room_id, ref = _room(settings, cid)

    snap_ref = SnapshotRef(kind="plan", source_id="p-1", typed_address="plan:1")
    fact_str = NarrativeFact(
        campaign_id=cid,
        namespace="campaign",
        subject_id="room_1",
        key="situation_premise",
        version=1,
        kind="truth",
        temporal_semantics="current_state",
        freedom="draft",
        value="Dusty table",
        audience=[],
        depends_on=[],
        source_refs=[],
        snapshot_ref=snap_ref.model_dump(),
    )
    fact_dict = NarrativeFact(
        campaign_id=cid,
        namespace="campaign",
        subject_id="room_1",
        key="role",
        version=1,
        kind="truth",
        temporal_semantics="current_state",
        freedom="draft",
        value="Storage",
        audience=[],
        depends_on=[],
        source_refs=[],
        snapshot_ref=snap_ref.model_dump(),
    )

    async def init_facts(s):
        s.add_all([fact_str, fact_dict])
        await s.commit()

    run(settings, init_facts)

    claim = _with_maker(settings, lambda maker: storage.claim(maker, cid, ref))
    assert isinstance(claim, storage.Claim)

    async def commit_with_refs(maker):
        orch = Orchestrator(InMemoryCoordination())
        draft = await orch._plan(maker, claim)
        dict_ref = FactRef(
            campaign_id=cid, namespace="campaign", subject_id="room_1", key="role", version=1, snapshot_ref=snap_ref
        )
        obj1 = ProposedObject(
            slot_ref=draft.plan.slots[0].slot_ref,
            role="clutter",
            name="Dusty note",
            used_fact_refs=("campaign:room_1:situation_premise",),
        )
        obj2 = ProposedObject(
            slot_ref=draft.plan.slots[1].slot_ref if len(draft.plan.slots) > 1 else draft.plan.slots[0].slot_ref,
            role="feature",
            name="Storage box",
            used_fact_refs=(dict_ref.model_dump(),),
        )
        proposal = Proposal(schema_version=1, objects=(obj1, obj2))
        await storage.commit_result(maker, orch.dice_factory, claim, draft.plan, proposal)

    _with_maker(settings, commit_with_refs)

    async def verify(s):
        f1 = await s.get(NarrativeFact, fact_str.id)
        f2 = await s.get(NarrativeFact, fact_dict.id)
        assert f1.freedom == "committed"
        assert f2.freedom == "committed"

    run(settings, verify)
