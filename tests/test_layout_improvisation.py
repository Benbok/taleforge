# ruff: noqa: F811
"""Импровизация ИИ-мастера и генерация незапланированных мест (quality-v3).

Проверяет игровой путь создания незапланированных мест:
- ИИ создаёт место через create_location -> резервируется и активируется location_layout.
- Оркестратор публикует структуру и геометрию.
- Группа входит в реальный участок, мастер работает с реальными ID геометрии/проходов.
- Повторные вызовы идемпотентны и не создают дубликаты.
- Проверка с включённой и выключенной LLM-генерацией.
- Проверка кампании без каркаса сюжета.
- Проверка секретного места (secret=True).
- Проверка места без шаблона.
- Проверка отказа/сбоя модели с безопасным fallback на детерминированную генерацию.
- Проверка отсутствия двойного расхода бюджета наполнения корня.
"""

from app.agents.llm import ScriptedLLM
from app.core.layout import store
from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import CampaignSecret, Character, Entity, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.game import import_base, party, quiet, run
from tests.test_layout_model_phase import _flags
from tests.test_layout_preparation import _areas, _setup
from tests.test_map import _ok, _play
from tests.test_master import DONE, act, rows
from tests.test_world_generation import _prepare, _row

WGS = WorldGenerationState


def _orch(llm):
    return Orchestrator(InMemoryCoordination(), llm=llm)


def test_unplanned_location_created_and_prepared_in_turn(game_client, admin_g, llm, settings):
    """Игроки идут незапланированным путём -> ИИ создаёт место -> карта готовится -> отряд во входном участке."""
    c, (p1,), hero = party(game_client, admin_g)
    cid, hid = c["id"], hero["id"]
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    # Герои идут по тракту
    async def place_on_road(ctx):
        road = (await _ok(ctx, "create_location", {"name": "Тракт", "make_current": True}))["location_id"]
        await _ok(ctx, "move", {"character_ids": [hid], "location_id": road})
        return road

    _play(settings, cid, place_on_road)

    # Мастер создаёт незапланированную таверну, затем завершает вызовы и описывает
    narration = "Вы свернули с тракта и вошли в тёплый общий зал придорожного трактира."
    llm.replies += [
        {
            "tool_calls": [
                (
                    "create_location",
                    {"name": "Придорожный трактир", "template_id": "location.tavern", "make_current": True},
                )
            ]
        },
        DONE,
        {"text": narration},
        {"text": narration},
        {"text": narration},
    ]

    told = act(game_client, p1, cid, "Сворачиваем с тракта к огням трактира")
    assert told["kind"] == "narration"

    # Проверяем, что локация создана и стала комплексом
    found_locs = rows(settings, Entity, Entity.campaign_id == cid, Entity.name == "Придорожный трактир")
    assert len(found_locs) == 1
    tavern = found_locs[0]
    areas = _areas(settings, tavern.id)
    assert len(areas) >= 3  # Общий зал, кухня/покои, погреб/комнаты
    bp = store.blueprint_of(tavern)
    assert bp is not None

    # Герои переместились в локацию
    h_loc = run(settings, lambda s: s.get(Character, hid)).location_id
    assert h_loc == tavern.id or h_loc in [a.id for a in areas.values()]

    # Layout подготовлен и готов
    layout_row = run(settings, lambda s: storage.find(s, cid, tavern.id, "location_layout"))
    assert layout_row is not None and layout_row.status == "ready"


def test_idempotent_creation_and_no_duplicates(client, admin, settings):
    """Повторные вызовы create_location или входа не создают дубликатов WorldGenerationState."""
    cid, _heads, hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    async def go(ctx):
        res1 = await _ok(
            ctx, "create_location", {"name": "Лесная сторожка", "template_id": "location.forest", "make_current": True}
        )
        loc_id = res1["location_id"]
        from app.tools.master.places import request_preparation

        res2 = await request_preparation(ctx, ctx.world.entities[loc_id], [])
        return loc_id, res1, res2

    loc_id, r1, r2 = _play(settings, cid, go)
    assert r1.get("operation_ref") or r1.get("layout")

    # Проверяем количество записей location_layout для loc_id
    layout_rows = rows(
        settings, WGS, WGS.campaign_id == cid, WGS.target_entity_id == loc_id, WGS.phase == "location_layout"
    )
    assert len(layout_rows) == 1


def test_unplanned_location_without_plot_frame(client, admin, settings):
    """Кампания вообще без сюжетного каркаса создаёт и готовит незапланированное место."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    quiet(client)
    cid = c["id"]

    async def clear_plot(s):
        sec = await s.get(CampaignSecret, cid)
        sec.plot = {}
        await s.commit()

    run(settings, clear_plot)
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    async def go(ctx):
        return await _ok(
            ctx,
            "create_location",
            {"name": "Святилище в горах", "template_id": "location.temple", "make_current": True},
        )

    res = _play(settings, cid, go)
    loc_id = res["location_id"]
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    assert layout_row is not None
    assert layout_row.reservation["source"] == "improvisation"
    assert _prepare(settings, cid, layout_row.id) == "ready"
    assert len(_areas(settings, loc_id)) >= 2


def test_unplanned_location_without_template(client, admin, settings):
    """Место без шаблона (template_id=None) строится детерминированным провайдером."""
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    async def go(ctx):
        return await _ok(ctx, "create_location", {"name": "Старый колодец", "template_id": None, "make_current": True})

    res = _play(settings, cid, go)
    loc_id = res["location_id"]
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    assert layout_row is not None
    assert _prepare(settings, cid, layout_row.id) == "ready"
    assert _row(settings, layout_row.id).quality in ("normal", "fallback")
    assert len(_areas(settings, loc_id)) >= 2


def test_secret_unplanned_location(client, admin, settings):
    """Секретное незапланированное место сохраняет secret=True у корня."""
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    async def go(ctx):
        return await _ok(
            ctx,
            "create_location",
            {"name": "Убежище гильдии", "template_id": "location.tavern", "secret": True, "make_current": True},
        )

    res = _play(settings, cid, go)
    loc_id = res["location_id"]
    loc = run(settings, lambda s: s.get(Entity, loc_id))
    assert (loc.state or {}).get("secret") is True
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    assert _prepare(settings, cid, layout_row.id) == "ready"


def test_model_refusal_falls_back_to_deterministic_layout(client, admin, settings):
    """При ошибке или отказе LLM генерация безопасно переходит на детерминированный алгоритм."""
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts=True, location_layout_templates=False, location_layouts_llm=True)

    async def go(ctx):
        return await _ok(
            ctx, "create_location", {"name": "Разрушенная башня", "template_id": "location.ruins", "make_current": True}
        )

    res = _play(settings, cid, go)
    loc_id = res["location_id"]
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    assert layout_row is not None

    # LLM выдаёт невалидный ответ (отказ/ошибка)
    llm = ScriptedLLM([lambda msgs, tools: {"tool_calls": [("propose_layout", {"invalid": True})]}])
    assert _prepare(settings, cid, layout_row.id, _orch(llm)) == "ready"
    row = _row(settings, layout_row.id)
    assert row.quality in ("normal", "fallback")
    assert any(n.startswith("fallback:") for n in row.result_manifest.get("notes", []))
    assert len(_areas(settings, loc_id)) >= 2


def test_disabled_llm_uses_template_or_deterministic(client, admin, settings):
    """При выключенной LLM-генерации модель даже не вызывается."""
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts=True, location_layout_templates=True, location_layouts_llm=False)

    async def go(ctx):
        return await _ok(
            ctx, "create_location", {"name": "Тёмная пещера", "template_id": "location.cave", "make_current": True}
        )

    res = _play(settings, cid, go)
    loc_id = res["location_id"]
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    llm = ScriptedLLM([])  # пустой ScriptedLLM: если будет вызов модели, упадёт с ошибкой
    assert _prepare(settings, cid, layout_row.id, _orch(llm)) == "ready"
    assert llm.requests == []


def test_root_initial_budget_not_double_spent(client, admin, settings):
    """location_initial корня, созданный до готовности карты, имеет budget=0 и не тратит бюджет дважды."""
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(
        settings,
        cid,
        location_layouts=True,
        scene_generation=True,
        location_layout_templates=True,
        location_layouts_llm=False,
    )

    async def go(ctx):
        return await _ok(
            ctx, "create_location", {"name": "Прибрежный склад", "template_id": "location.port", "make_current": True}
        )

    res = _play(settings, cid, go)
    loc_id = res["location_id"]

    initial_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_initial"))
    assert initial_row is not None
    # Бюджет случайной добычи корня обнулён в пользу будущих участков
    assert initial_row.reservation.get("budget") == 0
    assert initial_row.reservation.get("limits", {}).get("entities") == 0

    # Готовим location_initial (он тянет за собой layout)
    assert _prepare(settings, cid, initial_row.id) == "ready"
    layout_row = run(settings, lambda s: storage.find(s, cid, loc_id, "location_layout"))
    assert layout_row.status == "ready"

    # Проверяем, что в корне комплекса не насыпаны случайные предметы
    root_objects = rows(
        settings, Entity, Entity.campaign_id == cid, Entity.location_id == loc_id, Entity.kind == "object"
    )
    assert len(root_objects) == 0
