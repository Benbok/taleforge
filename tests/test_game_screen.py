# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Игровой экран (этап 7, часть 2): карточки бросков в чате, карточки сущностей по уровню знаний."""

from app.core import rolls
from app.db.models import Entity, Event, Knowledge, Message
from tests.game import ok, party, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def test_roll_cards_before_narration_and_hidden_rolls_stay_hidden(game_client, admin_g, llm, dice, settings):
    c, (p1,), hero = party(game_client, admin_g)
    dice += [14, 3]
    check = {"character_id": hero["id"], "difficulty": "dc.medium"}
    llm.replies += [
        {
            "tool_calls": [
                ("roll_check", {**check, "stat": "athletics", "reason": "дверь"}),
                ("roll_check", {**check, "stat": "perception", "reason": "засада"}),  # скрытая
            ]
        },
        DONE,
        {"text": f"[[{hero['id']}|Бран]] вышибает дверь."},
    ]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Вышибаю дверь"}})
        card = next_of(ws, "message.new")
        while card["payload"]["kind"] != "roll":
            card = next_of(ws, "message.new")
        narration = next_of(ws, "message.new")
    assert narration["payload"]["kind"] == "narration" and narration["seq"] > card["seq"]
    data = card["payload"]["data"]
    assert data["title"] == "Проверка: Атлетика" and data["who"] == "Бран" and data["outcome"] == "success"
    assert data["roll"]["natural"] == 14 and data["roll"]["total"] == 19
    assert data["against"] == {"label": "Сл", "value": 15}
    assert card["payload"]["content"] == "Проверка: Атлетика · Бран · 19 против Сл 15 · успех"

    cards = rows(settings, Message, Message.kind == "roll")
    assert len(cards) == 1  # у скрытой проверки внимательности карточки нет
    assert "Внимательность" not in str([m.content for m in rows(settings, Message)])


def test_attack_card_hides_creature_armor():
    ev = Event(
        tool="resolve_attack",
        target_id="en_1",
        payload={"attack": "Длинный меч", "attacker": "Бран", "target": "Гоблин", "roll": 17, "target_ac": 15,
                 "hit": True, "critical": False, "damage": 7, "damage_type": "slashing", "killed": True},
        dice=[{"d20": [13], "natural": 13, "modifier": 4, "mode": "normal", "total": 17},
              {"expr": "1d8+2", "rolls": [[5]], "total": 7}],
        hidden=False,
    )  # fmt: skip
    c = rolls.card(ev, hero_ids={"ch_1"})
    assert c["against"] is None and c["outcome"] == "hit" and c["damage"]["type"] == "рубящий"
    assert "Гоблин повержен" in c["notes"] and "15" not in rolls.line(c)
    ev.target_id = "ch_1"
    assert rolls.card(ev, hero_ids={"ch_1"})["against"] == {"label": "КБ", "value": 15}
    ev.hidden = True
    assert rolls.card(ev, hero_ids=set()) is None


def _spawn(settings, cid, **kw):
    async def go(s):
        e = Entity(campaign_id=cid, **kw)
        s.add(e)
        await s.commit()
        return e.id

    return run(settings, go)


def _know(settings, ch, en, level):
    async def go(s):
        s.add(Knowledge(character_id=ch, entity_id=en, level=level))
        await s.commit()

    run(settings, go)


def test_entity_card_by_knowledge_level(game_client, admin_g, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    cid = c["id"]
    goblin = _spawn(
        settings,
        cid,
        kind="creature",
        name="Гоблин-разведчик",
        template_id="creature.goblin",
        description="Мелкий, в грязной коже",
        state={"hp": 5, "hp_max": 7, "attitude": "hostile", "plot_id": "npc_secret"},
    )
    hidden = _spawn(settings, cid, kind="creature", name="Тайный культист", template_id="creature.goblin")

    def inspect(head, eid):
        with connect(game_client, head, cid) as (ws, _):
            ws.send_json({"type": "entity.inspect", "payload": {"entity_id": eid}})
            return next_of(ws, "entity.card")["payload"]

    # ещё не видел: сущности для героя нет
    assert inspect(p1, goblin) == {"id": goblin, "error": "такого в мире нет"}

    _know(settings, hero["id"], goblin, 0)
    card = inspect(p1, goblin)
    assert card["level"] == 0 and card["type"] == "creature" and card["description"] == "Мелкий, в грязной коже"
    assert "stats" not in card and "condition" not in card and card["locked"] == ["наслышан", "изучил", "знает всё"]
    assert "npc_secret" not in str(card)

    run(settings, lambda s: _raise(s, hero["id"], goblin, 2))
    card = inspect(p1, goblin)
    assert card["kind_name"] and card["condition"] == "ранен" and card["attacks"] and "stats" not in card

    run(settings, lambda s: _raise(s, hero["id"], goblin, 3))
    card = inspect(p1, goblin)
    assert card["stats"]["ac"] == 15 and card["stats"]["hp"] == 5 and card["locked"] == []

    # второй игрок без героя и без упоминаний сущность не видит
    assert "error" in inspect(p2, goblin)
    assert "error" in inspect(p1, hidden)
    # мастер-владелец не за столом: мест мастера у него нет, видит как зритель
    assert "error" in inspect(admin_g, hidden)

    types = ok(game_client.get(f"/api/campaigns/{cid}/entity-types?ids={goblin},{hero['id']},en_nope", headers=p2))
    assert types == {goblin: "creature", hero["id"]: "hero"}
    hero_card = inspect(p2, hero["id"])
    assert hero_card["type"] == "hero" and hero_card["hero"]["name"] == "Бран"


async def _raise(s, ch, en, level):
    row = await s.get(Knowledge, (ch, en))
    row.level = level
    await s.commit()


def test_knowledge_notice_goes_only_to_that_player(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    goblin = _spawn(settings, c["id"], kind="creature", name="Гоблин", template_id="creature.goblin")
    llm.replies += [
        {"tool_calls": [("reveal_knowledge", {"character_id": hero["id"], "entity_id": goblin, "level": 1})]},
        DONE,
        DONE,  # действие не закрыто: мастера переспрашивают
        {"text": f"Бран вспоминает, что [[{goblin}|гоблины]] боятся огня."},
    ]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Вспоминаю, что знаю о гоблинах"}})
        notice = next_of(ws, "knowledge.revealed")
    assert notice["payload"] == {"entity_id": goblin, "name": "Гоблин", "level": 1}


def test_actions_follow_state(game_client, admin_g, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]

    def state(head):
        with connect(game_client, head, cid) as (ws, snap):
            ws.send_json({"type": "actions.get", "payload": {}})
            again = next_of(ws, "state.actions")["payload"]
        assert again == {"actions": snap["payload"]["actions"], "blocked": snap["payload"]["blocked"]}
        return again

    owner, player = state(admin_g), state(p1)
    assert owner["actions"] == ["session.pause", "campaign.end", "invite.create", "chat.ooc"]  # сессия идёт
    assert player["actions"] == ["chat.ooc", "chat.whisper", "chat.play"] and player["blocked"] == {}

    ok(game_client.post(f"/api/campaigns/{cid}/session/pause", headers=admin_g))
    owner, player = state(admin_g), state(p1)
    assert "session.start" in owner["actions"] and "session.pause" not in owner["actions"]
    assert player["actions"] == ["chat.ooc"] and player["blocked"]["chat.play"].startswith("Сессия не идёт")

    ok(game_client.post(f"/api/campaigns/{cid}/session/start", headers=admin_g))
    goblin = _spawn(settings, cid, kind="creature", name="Гоблин", template_id="creature.goblin")

    async def fight(s):
        from app.core.world import get_scene

        sc = await get_scene(s, cid)
        sc.mode, sc.turn_order, sc.state = "combat", [{"id": goblin}, {"id": hero["id"]}], {"turn": 0}
        await s.commit()

    run(settings, fight)
    player = state(p1)
    assert "chat.play" not in player["actions"] and "turn.pass" not in player["actions"]
    assert "сейчас ход: существ" in player["blocked"]["chat.play"]

    ok(game_client.post(f"/api/campaigns/{cid}/session/end", headers=admin_g))
    assert state(admin_g)["actions"] == ["chat.ooc"]  # кампания завершена: управлять больше нечем
