# ruff: noqa: F811
"""Тесты пресетов мастера: сохранение, редактирование, удаление, применение в кампании и создание с пресетом."""

from tests.game import ok, party
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401


def test_master_presets_crud_and_apply(game_client, admin_g, settings, llm):
    # 1. Список изначально пуст
    presets = ok(game_client.get("/api/me/master-presets", headers=admin_g))
    assert presets == []

    # 2. Создание пресета
    body = {
        "name": "Мрачный инквизитор",
        "style": "Говорит сухо и зловеще",
        "persona_settings": {
            "seriousness": 5,
            "humor": "none",
            "darkness": 5,
            "verbosity": "short",
            "pace": "fast",
            "manner": "chronicler",
            "harshness": 5,
        },
        "character": {
            "text": "Строгий инквизитор веры, ищет следы ереси.",
            "fields": {
                "never": "никогда не прощает ложь",
                "tricks": "внезапные допросы при свечах",
            },
            "core": ["never"],
        },
    }
    created = ok(game_client.post("/api/me/master-presets", json=body, headers=admin_g), code=201)
    assert created["id"].startswith("mpre_")
    assert created["name"] == "Мрачный инквизитор"
    assert created["character"]["fields"]["never"] == "никогда не прощает ложь"
    assert "Мрачность: жёсткий гримдарк" in (created["style_preview"] or "")

    # 3. Получение по ID
    got = ok(game_client.get(f"/api/me/master-presets/{created['id']}", headers=admin_g))
    assert got["id"] == created["id"]
    assert got["name"] == "Мрачный инквизитор"

    # 4. Обновление пресета (patch)
    patched = ok(
        game_client.patch(
            f"/api/me/master-presets/{created['id']}",
            json={"name": "Великий инквизитор", "style": "Говорит шёпотом"},
            headers=admin_g,
        )
    )
    assert patched["name"] == "Великий инквизитор"
    assert patched["style"] == "Говорит шёпотом"

    # 5. Тестирование пресета пробными сценами
    llm.replies += [
        {"text": "Дым клубится у порога."},
        {"text": "Стражник сжимает алебарду."},
        {"text": "Герой падает во тьму."},
    ]
    test_res = ok(
        game_client.post(
            "/api/me/master-presets/test",
            json={"character": patched["character"], "style": patched["style"]},
            headers=admin_g,
        )
    )
    assert len(test_res["scenes"]) == 3
    assert test_res["scenes"][0]["scene"] == "Описание места"

    # 6. Создание новой кампании с пресетом
    camp_body = {
        "name": "Экспедиция инквизиции",
        "difficulty": "normal",
        "master": {
            "type": "agent",
            "preset_id": created["id"],
        },
    }
    c = ok(game_client.post("/api/campaigns", json=camp_body, headers=admin_g), code=201)
    cid = c["id"]

    # Проверяем, что мастер кампании получил характер и стиль из пресета
    char = ok(game_client.get(f"/api/campaigns/{cid}/master-character", headers=admin_g))
    assert char["persona"]["text"] == "Строгий инквизитор веры, ищет следы ереси."
    assert char["persona"]["fields"]["never"] == "никогда не прощает ложь"

    # 7. Сохранение пресета прямо из существующей кампании
    # Изменим характер в кампании
    ok(
        game_client.put(
            f"/api/campaigns/{cid}/master-character",
            json={"text": "Новый характер из игры", "fields": {"tricks": "падающие люстры"}},
            headers=admin_g,
        )
    )
    saved_from_camp = ok(
        game_client.post(
            f"/api/campaigns/{cid}/save-master-preset",
            json={"name": "Пресет из первой кампании"},
            headers=admin_g,
        )
    )
    assert saved_from_camp["name"] == "Пресет из первой кампании"
    assert saved_from_camp["character"]["text"] == "Новый характер из игры"
    assert saved_from_camp["character"]["fields"]["tricks"] == "падающие люстры"

    # 8. Применение пресета к другой кампании
    c2, _, _ = party(game_client, admin_g)
    applied = ok(
        game_client.post(
            f"/api/campaigns/{c2['id']}/apply-master-preset/{saved_from_camp['id']}",
            headers=admin_g,
        )
    )
    assert applied["ok"] is True
    assert applied["character"]["persona"]["text"] == "Новый характер из игры"

    # 9. Удаление пресета
    del_res = game_client.delete(f"/api/me/master-presets/{created['id']}", headers=admin_g)
    assert del_res.status_code == 204

    # Проверяем, что удалён
    assert game_client.get(f"/api/me/master-presets/{created['id']}", headers=admin_g).status_code == 404


def test_master_preset_conflicts_and_access(game_client, admin_g, settings):
    # 1. Создание пресета
    ok(
        game_client.post(
            "/api/me/master-presets",
            json={"name": "Уникальный мастер", "style": "Лаконичный"},
            headers=admin_g,
        ),
        code=201,
    )

    # 2. Попытка создать пресет с тем же именем -> 409
    dup = game_client.post(
        "/api/me/master-presets",
        json={"name": "Уникальный мастер", "style": "Другой"},
        headers=admin_g,
    )
    assert dup.status_code == 409
    assert "уже есть" in dup.text

    # 3. Создание второго пресета и попытка переименовать его в занятое имя -> 409
    p2 = ok(
        game_client.post(
            "/api/me/master-presets",
            json={"name": "Второй мастер", "style": "Болтливый"},
            headers=admin_g,
        ),
        code=201,
    )
    ren = game_client.patch(
        f"/api/me/master-presets/{p2['id']}",
        json={"name": "Уникальный мастер"},
        headers=admin_g,
    )
    assert ren.status_code == 409

    # 4. Несуществующий пресет -> 404
    assert game_client.get("/api/me/master-presets/mpre_nonexistent", headers=admin_g).status_code == 404
    assert (
        game_client.patch("/api/me/master-presets/mpre_nonexistent", json={"name": "Х"}, headers=admin_g).status_code
        == 404
    )
    assert game_client.delete("/api/me/master-presets/mpre_nonexistent", headers=admin_g).status_code == 404

    # 5. Игрок без прав админа не имеет доступа к пресетам мастера -> 403
    c, (player,), _ = party(game_client, admin_g)
    assert game_client.get("/api/me/master-presets", headers=player).status_code == 403

    # 6. Сохранение из кампании с уже занятым именем без preset_id -> 409
    save_dup = game_client.post(
        f"/api/campaigns/{c['id']}/save-master-preset",
        json={"name": "Уникальный мастер"},
        headers=admin_g,
    )
    assert save_dup.status_code == 409


def test_master_preset_fallback_missing_model(game_client, admin_g, settings):
    # Пресет ссылается на удалённый или несуществующий ID профиля модели
    p = ok(
        game_client.post(
            "/api/me/master-presets",
            json={
                "name": "Пресет со старой моделью",
                "model_profile_id": "mprof_deleted",
                "style": "Вкрадчивый",
            },
            headers=admin_g,
        ),
        code=201,
    )
    # Применяем пресет к кампании — не должно падать, профиль грациозно остаётся дефолтным
    c, _, _ = party(game_client, admin_g)
    applied = ok(
        game_client.post(
            f"/api/campaigns/{c['id']}/apply-master-preset/{p['id']}",
            headers=admin_g,
        )
    )
    assert applied["ok"] is True
    assert applied["persona"]["style"] == "Вкрадчивый"
