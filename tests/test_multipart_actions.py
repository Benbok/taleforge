# ruff: noqa: F811 — shared integration fixtures
"""Сквозные интеграционные тесты жизненного цикла составных действий игрока (Task 7).

Проверяет:
1. Двухчастную заявку search+cast со сквозным выполнением и подтверждением находки.
2. Откат хода с возвратом эффектов и прогресса при сбое до фиксации.
3. Восстановление хода после фиксации эффектов без повторного вызова инструментов.
4. Запрет получения лишнего действия в бою при многочастной заявке.
5. Недопустимость перенацеливания старой заявки при смене сцены/локации.
6. Обратную совместимость одиночных действий старого формата и неразобранного текста.
"""

from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401


def test_scene_change_does_not_retarget_old_request(game_client, admin_g, llm, settings):
    """Смена локации / сцены не позволяет действию примениться к объектам старого места

    или ошибочно перенацелиться на новую локацию.
    """
    from tests.test_tools import call, play

    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]

    async def scenario(ctx):
        loc1_res = await call(ctx, "create_location", {"name": "Старый зал", "make_current": True})
        loc1 = loc1_res["result"]["location_id"]

        box1_res = await call(ctx, "create_container", {"name": "Сундук в зале", "location_id": loc1})
        box1 = box1_res["result"]["container_id"]

        loc2_res = await call(ctx, "create_location", {"name": "Новый коридор", "make_current": False})
        loc2 = loc2_res["result"]["location_id"]

        ch = ctx.world.characters[hero["id"]]
        ch.location_id = loc1

        # Перемещаем героя в loc2
        ch.location_id = loc2
        ctx.world.scene.location_id = loc2

        # Пытаемся применить действие к box1 (который остался в loc1)
        res = await call(ctx, "open_container", {"character_id": ch.id, "container_id": box1})
        # Действие должно быть отклонено, так как цель не в текущей локации
        assert not res["ok"]
        assert "в другой" in res.get("error", "") or "недоступ" in res.get("error", "")

    play(settings, cid, [], scenario)
