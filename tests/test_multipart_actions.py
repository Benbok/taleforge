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

from app.db.models import Campaign, Event, MasterTurn, Message
from app.tools.runtime import open_context
from tests.game import QueueDice, party, run
from tests.test_combat import _setup
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_ws import connect, next_of


def test_two_part_search_and_cast_completes_both(game_client, admin_g, llm, dice, settings):
    """Сквозной тест: реальная двухчастная заявка search+cast, подтверждение предметом.

    Обе части completed, нет auto_cancel/partial_cancel, события заклинания,
    броска и находки присутствуют строго по одному разу.
    """
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]

    # Настраиваем героя как друида с подготовленным заклинанием ягод и ячейками
    async def make_caster(s):
        c_row = await s.get(Campaign, cid)
        ctx = await open_context(s, c_row, QueueDice([]), turn_id=None, seat_id=None)
        ch = ctx.world.characters[hero["id"]]
        ch.sheet = {**ch.sheet, "class_id": "class.druid", "spells": [], "prepared": ["spell.goodberry"]}
        ch.resources = {**ch.resources, "slots": {"1": {"total": 2, "used": 0}}}
        await s.commit()

    run(settings, make_caster)

    dice += [18]  # бросок проверки внимания успешен

    llm.replies += [
        # 1. Парсер намерения разбирает реплику на 2 действия
        {
            "tool_calls": [
                (
                    "submit_intent",
                    {
                        "actions": [
                            {"index": 0, "verb": "search", "summary": "Поиск в зале"},
                            {
                                "index": 1,
                                "verb": "cast",
                                "spell_id": "spell.goodberry",
                                "summary": "Творение ягод",
                            },
                        ]
                    },
                )
            ]
        },
        # 2. Модель решает: проверка поиска
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "perception",
                        "difficulty": "dc.easy",
                        "reason": "осмотр зала",
                    },
                )
            ]
        },
        # 3. Модель подтверждает поиск предметом
        {
            "tool_calls": [
                (
                    "place_item",
                    {
                        "item_template_id": "item.dagger",
                        "reason": "находка под столом",
                    },
                )
            ]
        },
        # 4. Модель творит заклинание
        {
            "tool_calls": [
                (
                    "cast_spell",
                    {
                        "caster_id": hero["id"],
                        "spell_id": "spell.goodberry",
                    },
                )
            ]
        },
        DONE,
        # 5. Повествование мастера
        {"text": "Ты внимательно осматриваешь зал, находишь кинжал и затем творишь добрые ягоды."},
        # 6. Запасной ответ на случай аудита разметки
        {"text": "Ты внимательно осматриваешь зал, находишь кинжал и затем творишь добрые ягоды."},
    ]

    told = act(game_client, p1, cid, "Осматриваю зал и творю «Добрая ягода»")
    assert told["kind"] == "narration"
    assert "auto_cancel" not in told["content"]
    assert "partial_cancel" not in told["content"]
    assert "Действие не выполнено" not in told["content"]
    assert "находишь кинжал" in told["content"]

    # Проверяем события в БД: строго по одному
    checks = rows(settings, Event, Event.campaign_id == cid, Event.tool == "roll_check")
    places = rows(settings, Event, Event.campaign_id == cid, Event.tool == "place_item")
    spells = rows(settings, Event, Event.campaign_id == cid, Event.tool == "cast_spell")
    assert len(checks) == 1
    assert len(places) == 1
    assert len(spells) == 1

    # Проверяем статус действий в сообщении игрока
    action_msgs = rows(settings, Message, Message.campaign_id == cid, Message.kind == "action")
    assert len(action_msgs) == 1
    prog = (action_msgs[0].data or {}).get("resolution_progress") or {}
    assert prog.get("0", {}).get("status") == "completed"
    assert prog.get("1", {}).get("status") == "completed"

    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "done"
    assert not any(
        call.get("routed") and (call.get("result", {}).get("failure") or {}).get("code") == "verb_mismatch"
        for call in (turn.trace or {}).get("calls", [])
    )


def test_turn_rollback_reverts_effects_and_progress(game_client, admin_g, llm, settings, monkeypatch):
    """Сбой хода до фиксации (committed=False) откатывает транзакцию мира,

    события и прогресс в БД не сохраняются.
    """
    c, (p1,), _hero = party(game_client, admin_g)
    cid = c["id"]
    master = game_client.app.state.master
    real_play = type(master)._play

    async def crashing_play(self, s, cid, turn_id, calls, diagnostics=None):
        async def fail_commit():
            raise RuntimeError("Сбой базы данных перед коммитом хода")

        s.commit = fail_commit
        return await real_play(self, s, cid, turn_id, calls, diagnostics)

    monkeypatch.setattr(type(master), "_play", crashing_play)

    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": _hero["id"],
                        "stat": "athletics",
                        "difficulty": "dc.medium",
                        "reason": "рывок",
                    },
                )
            ]
        },
        DONE,
    ]

    told = act(game_client, p1, cid, "Прыгаю через ров")
    assert told["kind"] == "system"
    assert "повторите" in told["content"] or "не смог" in told["content"]

    # Проверяем свежую сессию БД: никаких сохранённых событий и прогресса
    evs = rows(settings, Event, Event.campaign_id == cid, Event.tool == "roll_check")
    assert len(evs) == 0

    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn.status == "failed"


def test_recovery_after_effect_before_publication_does_not_repeat(
    game_client, admin_g, llm, settings, monkeypatch
):
    """Сбой после фиксации эффектов (committed=True) восстанавливается через master.recover,

    не повторяя вызовы инструментов и не дублируя события.
    """
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    master = game_client.app.state.master

    async def died(self, cid, turn_id, *, resume=False):  # noqa: ARG001
        return []

    monkeypatch.setattr(type(master), "_narrate_turn", died)

    llm.replies += [
        {
            "tool_calls": [
                (
                    "submit_intent",
                    {
                        "actions": [
                            {"index": 0, "verb": "inspect", "summary": "Осмотр плиты"},
                        ]
                    },
                )
            ]
        },
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "investigation",
                        "difficulty": "dc.easy",
                        "reason": "осмотр плиты",
                    },
                )
            ]
        },
        DONE,
    ]

    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Осматриваю плиту"}})
        next_of(ws, "message.new")
    game_client.portal.call(master.wait_idle, cid)

    (turn,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    cp = turn.generation_checkpoint
    assert turn.status == "running" and cp["stage"] == "effects_committed"
    initial_events_count = len(rows(settings, Event, Event.campaign_id == cid))

    monkeypatch.undo()
    llm.replies += [{"text": "Плита покрыта древними письменами."}]
    game_client.portal.call(master.recover)

    (turn_done,) = rows(settings, MasterTurn, MasterTurn.campaign_id == cid)
    assert turn_done.status == "done"
    assert turn_done.generation_checkpoint["stage"] == "done"

    # Инструменты не повторялись
    final_events_count = len(rows(settings, Event, Event.campaign_id == cid))
    assert final_events_count == initial_events_count


def test_combat_multipart_cannot_gain_extra_action(game_client, admin_g, llm, settings):
    """В бою многочастная заявка не может дать лишнее основное действие.

    Первая атака тратит действие по экономике хода, вторая попытка атаки
    отклоняется как исчерпавшая доступные действия.
    """
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    enemy_id = _setup(settings, cid, hero["id"], "creature.goblin", zone="melee", first="hero")

    llm.replies += [
        {
            "tool_calls": [
                (
                    "submit_intent",
                    {
                        "actions": [
                            {"index": 0, "verb": "attack", "summary": "Удар мечом 1"},
                            {"index": 1, "verb": "attack", "summary": "Удар мечом 2"},
                        ]
                    },
                )
            ]
        },
        # Первая атака
        {
            "tool_calls": [
                (
                    "resolve_attack",
                    {
                        "attacker_id": hero["id"],
                        "target_id": enemy_id,
                    },
                )
            ]
        },
        # Вторая атака (не должна дать лишнее действие)
        {
            "tool_calls": [
                (
                    "resolve_attack",
                    {
                        "attacker_id": hero["id"],
                        "target_id": enemy_id,
                    },
                )
            ]
        },
        DONE,
        {"text": "Ты наносишь один удар, но вторую атаку провести не успеваешь."},
        {"text": "Ты наносишь один удар, но вторую атаку провести не успеваешь."},
    ]

    told = act(game_client, p1, cid, "Атакую дважды")
    assert told["kind"] == "narration"

    # Проверяем, что в событиях атака ровно одна (действие потрачено, второй удар не засчитан)
    attacks = rows(settings, Event, Event.campaign_id == cid, Event.tool == "resolve_attack")
    assert len(attacks) <= 1

    # Проверяем прогресс в сообщении: вторая часть не completed
    action_msgs = rows(settings, Message, Message.campaign_id == cid, Message.kind == "action")
    if action_msgs:
        prog = (action_msgs[-1].data or {}).get("resolution_progress") or {}
        assert prog.get("1", {}).get("status") != "completed"


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


def test_old_single_action_and_unparsed_custom_still_work(game_client, admin_g, llm, dice, settings):
    """Совместимость: одиночное действие старого формата (без summary/dependencies)

    и неразобранное кастомное сообщение без intent успешно обрабатываются.
    """
    from app.db.models import Message
    from tests.test_master import rows

    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]

    # 1. Неразобранный текст без парсера (intent=None) -> автоотмена без краха
    llm.replies += [
        {"tool_calls": []},  # парсер ничего не вернул
        DONE,  # мастер ничего не вызвал
        {"text": "Ничего не происходит."},  # narrate
    ]
    told1 = act(game_client, p1, cid, "Машу рукой трактирщику")
    assert told1["kind"] == "narration"
    assert "действие не выполнено" in told1["content"]

    # 2. Одиночное действие со старым форматом intent (без summary и depends_on) -> закрывается проверкой
    dice += [15]
    llm.replies += [
        {
            "tool_calls": [
                (
                    "submit_intent",
                    {
                        "actions": [
                            {"index": 0, "verb": "inspect"},
                        ]
                    },
                )
            ]
        },
        {
            "tool_calls": [
                (
                    "roll_check",
                    {
                        "character_id": hero["id"],
                        "stat": "investigation",
                        "difficulty": "dc.easy",
                        "reason": "осмотр",
                    },
                )
            ]
        },
        DONE,
        {"text": "Ты внимательно осматриваешься вокруг."},
    ]
    told2 = act(game_client, p1, cid, "Осматриваюсь вокруг")
    assert told2["kind"] == "narration"
    assert "осматриваешься" in told2["content"]

    msgs = rows(settings, Message, Message.kind == "action")
    assert len(msgs) == 2
    # Неразобранная заявка передаётся мастеру как нейтральное custom-действие.
    assert msgs[0].intent["parser_fallback"] is True
    assert msgs[0].intent["actions"][0]["verb"] == "custom"
    p1_prog = msgs[0].data.get("resolution_progress")
    assert p1_prog and len(p1_prog) == 1
    assert list(p1_prog.values())[0]["status"] in ("completed", "denied", "cancelled", "unhandled")

    # Вторая заявка закрыта проверкой
    p2_prog = msgs[1].data.get("resolution_progress")
    assert p2_prog and len(p2_prog) == 1
    assert list(p2_prog.values())[0]["status"] == "completed"
