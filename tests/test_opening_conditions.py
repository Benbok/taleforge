# ruff: noqa: F811 — integration test fixtures
"""Тесты стартовых условий кампании (изъятие снаряжения по завязке)."""

from app.agents import prelude
from app.core import plot
from app.core.world_objects import read_world_object
from app.db.models import CampaignSecret, Entity, InventoryItem, LlmCall
from tests.game import party, quiet, run
from tests.test_lead import FakeCatalog, checked, good_plan, set_plan
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401


def test_plot_opening_schema_valid_kept():
    plan = good_plan()
    plan["opening"] = {"gear": "kept"}
    p, errors = plot.check(plan, length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == []
    assert p["opening"]["gear"] == "kept"

    # Без указания opening по умолчанию gear = kept
    plan_no_opening = good_plan()
    plan_no_opening.pop("opening", None)
    p_def, err_def = plot.check(plan_no_opening, length="short", catalog=FakeCatalog(), excluded=[])
    assert err_def == []
    assert p_def["opening"]["gear"] == "kept"


def test_plot_opening_schema_confiscated_without_stash():
    plan = good_plan()
    plan["opening"] = {"gear": "confiscated"}
    p, errors = plot.check(plan, length="short", catalog=FakeCatalog(), excluded=[])
    assert any("при gear=confiscated необходимо указать stash" in e for e in errors)


def test_plot_opening_schema_confiscated_with_invalid_stash():
    plan = good_plan()
    plan["opening"] = {"gear": "confiscated", "stash": "non_existent_stash"}
    p, errors = plot.check(plan, length="short", catalog=FakeCatalog(), excluded=[])
    assert any("opening.stash: место non_existent_stash не найдено" in e for e in errors)


def test_plot_opening_schema_confiscated_valid():
    plan = good_plan()
    stash_id = plan["locations"][1]["id"]
    plan["opening"] = {"gear": "confiscated", "stash": stash_id, "note": "Отобрано стражей гарнизона"}
    p, errors = plot.check(plan, length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == []
    assert p["opening"]["gear"] == "confiscated"
    assert p["opening"]["stash"] == stash_id
    assert p["opening"]["note"] == "Отобрано стражей гарнизона"


def test_plot_opening_schema_keyword_hint_in_public_intro():
    plan = good_plan()
    plan["public_intro"] = "Вы приходите в себя в сыром каземате, лишённые оружия и доспехов."
    plan.pop("opening", None)
    p, errors = plot.check(plan, length="short", catalog=FakeCatalog(), excluded=[])
    assert any("завязка говорит об изъятом снаряжении" in e for e in errors)


def test_prelude_confiscates_gear(game_client, admin_g, llm, settings):
    c, _, ch = party(game_client, admin_g, location_layouts=False)
    hid = ch["id"]
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

    plan = checked()
    stash_id = plan["locations"][1]["id"]
    stash_name = plan["locations"][1]["name"]
    plan["opening"] = {"gear": "confiscated", "stash": stash_id, "note": "Сложено в караулке"}
    set_plan(settings, c["id"], plan)

    # Добавляем герою одежду, друидическую фокусировку и уникальный артефакт
    art_id = None

    async def seed(s):
        nonlocal art_id
        # Одежда и фокусировка
        s.add(InventoryItem(character_id=hid, item_template_id="item.clothes_common", qty=1))
        s.add(InventoryItem(character_id=hid, item_template_id="item.druidic_focus", qty=1))
        # Уникальный предмет с сущностью Entity
        art = Entity(campaign_id=c["id"], kind="object", name="Фамильный перстень", state={"item": True})
        s.add(art)
        await s.flush()
        art_id = art.id
        s.add(InventoryItem(character_id=hid, item_template_id="item.dagger", world_entity_id=art.id, qty=1))
        await s.commit()

    run(settings, seed)

    llm.replies += [{"text": "Герои очнулись в запертой камере."}]
    res = game_client.portal.call(prelude.introduce, game_client.app.state.master, c["id"])
    assert res is not None, [(call.purpose, call.error) for call in rows(settings, LlmCall)]

    # Проверяем инвентарь героя после изъятия
    inv = rows(settings, InventoryItem, InventoryItem.character_id == hid)
    inv_templates = {it.item_template_id for it in inv}
    # Обычное оружие/доспехи/рационы изъяты
    assert "item.longsword" not in inv_templates
    assert "item.chain_mail" not in inv_templates
    assert "item.rations" not in inv_templates
    # Одежда и фокусировка остались
    assert "item.clothes_common" in inv_templates
    assert "item.druidic_focus" in inv_templates

    # Проверяем тайник и контейнер
    stash_locs = rows(
        settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "location", Entity.name == stash_name
    )
    assert len(stash_locs) == 1
    stash_place = stash_locs[0]

    containers = rows(
        settings,
        Entity,
        Entity.campaign_id == c["id"],
        Entity.location_id == stash_place.id,
        Entity.name == "Изъятые вещи",
    )
    assert len(containers) == 1
    container = containers[0]
    c_obj = read_world_object(container)
    assert c_obj.role == "container"

    # Уникальный предмет перенесён в контейнер тайника
    art_en = rows(settings, Entity, Entity.id == art_id)[0]
    assert art_en.location_id == stash_place.id
    assert read_world_object(art_en).container_id == container.id

    # В plot.opening.applied_to записан hid
    sec = rows(settings, CampaignSecret, CampaignSecret.campaign_id == c["id"])[0]
    assert hid in (sec.plot.get("opening") or {}).get("applied_to", [])

    # Проверяем промпт нарратора
    req = llm.requests[-1]["messages"][1]["content"]
    assert "Стартовое условие кампании: снаряжение героев изъято" in req
    assert stash_name in req
    assert "Не утверждай о наличии снаряжения вопреки фактическому листу персонажа" in req

    # Повторный вызов introduce не дублирует изъятие
    items_count_before = len(rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "object"))
    llm.replies += [{"text": "Ничего не изменилось."}]
    game_client.portal.call(prelude.introduce, game_client.app.state.master, c["id"])
    items_count_after = len(rows(settings, Entity, Entity.campaign_id == c["id"], Entity.kind == "object"))
    assert items_count_before == items_count_after


def test_late_joiner_after_stash_opened(game_client, admin_g, llm, settings):
    from tests.game import FIGHTER, ok

    c, heads, ch1 = party(game_client, admin_g, players=2, location_layouts=False)
    assert ch1["id"]
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

    plan = checked()
    stash_id = plan["locations"][1]["id"]
    plan["opening"] = {"gear": "confiscated", "stash": stash_id}
    set_plan(settings, c["id"], plan)

    # Первое вступление
    llm.replies += [{"text": "Первый герой в камере."}]
    res = game_client.portal.call(prelude.introduce, game_client.app.state.master, c["id"])
    assert res is not None

    # Находим контейнер и "вскрываем" его (access.open = True)
    containers = rows(settings, Entity, Entity.campaign_id == c["id"], Entity.name == "Изъятые вещи")
    assert len(containers) == 1
    container = containers[0]

    async def open_stash(s):
        en = await s.get(Entity, container.id)
        st = dict(en.state or {})
        wo = dict(st.get("world_object") or {})
        acc = dict(wo.get("access") or {})
        acc["open"] = True
        wo["access"] = acc
        st["world_object"] = wo
        en.state = st
        await s.commit()

    run(settings, open_stash)

    ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))

    # Второй игрок создаёт и сдаёт персонажа
    ch2 = ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=heads[1]), 201)
    ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=heads[1]))
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin_g))
    quiet(game_client)
    hid2 = ch2["id"]

    # Второе вступление (для опоздавшего героя)
    llm.replies += [{"text": "Появился опоздавший герой."}]
    res2 = game_client.portal.call(prelude.introduce, game_client.app.state.master, c["id"])
    assert res2 is not None

    # Поскольку тайник уже открыт, опоздавший герой НЕ теряет снаряжение
    inv2 = rows(settings, InventoryItem, InventoryItem.character_id == hid2)
    assert any(it.item_template_id == "item.longsword" for it in inv2)

    # И он добавлен в applied_to
    sec = rows(settings, CampaignSecret, CampaignSecret.campaign_id == c["id"])[0]
    assert hid2 in (sec.plot.get("opening") or {}).get("applied_to", [])


def test_turn_prompt_reflects_opening(game_client, admin_g, settings):
    from app.agents.master.common import render

    plan = checked()
    stash_id = plan["locations"][1]["id"]
    stash_name = plan["locations"][1]["name"]
    plan["opening"] = {"gear": "confiscated", "stash": stash_id, "note": "Отобрано стражей"}

    # Проверяем now_block
    now = plot.now_block(plan)
    assert "Стартовое условие: снаряжение героев изъято и находится в «" + stash_name in now
    assert "@" + stash_id in now
    assert "Отобрано стражей" in now

    # Проверяем системный промпт мастера
    sys_prompt = render(
        "master_system.j2",
        campaign_name="Тест",
        secrets=now,
        dc_scale="10 = лёгкая",
        max_calls=4,
        difficulty="medium",
        leveling=False,
        random_events=False,
        critical_checks=True,
    )
    assert "Стартовое условие: снаряжение героев изъято" in sys_prompt
    assert "Никогда не описывай наличие снаряжения вопреки фактическому листу персонажа" in sys_prompt
