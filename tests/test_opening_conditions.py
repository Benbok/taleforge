# ruff: noqa: F811 — integration test fixtures
"""Тесты стартовых условий кампании (изъятие снаряжения по завязке)."""

from app.core import plot
from tests.test_lead import FakeCatalog, checked, good_plan
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
