# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Герой (этап 7, часть 3): разбор чисел листа и быстрые действия из интерфейса."""

from app.db.models import Entity, Message
from tests.game import ok, party, run
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def _explain(client, head, cid, character_id, stat):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "stat.explain", "payload": {"character_id": character_id, "stat": stat}})
        return next_of(ws, "stat.explained")["payload"]


def test_explain_numbers_of_own_hero(game_client, admin_g):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    cid, hid = c["id"], hero["id"]
    sheet = ok(game_client.get(f"/api/campaigns/{cid}/characters/{hid}", headers=p1))

    ac = _explain(game_client, p1, cid, hid, "ac")
    assert ac["value"] == sheet["derived"]["ac"] and ac["label"] == "Класс доспеха"
    assert sum(int(p["value"]) for p in ac["parts"]) == ac["value"]  # части складываются в итог

    strength = _explain(game_client, p1, cid, hid, "ability:str")
    assert strength["value"] == sheet["derived"]["abilities"]["str"]
    assert strength["parts"][0]["label"] == "Распределено при создании" and "Модификатор" in strength["note"]

    athletics = _explain(game_client, p1, cid, hid, "skill:athletics")
    assert [p["label"] for p in athletics["parts"]] == ["Сила 16", "Владение (выбор класса)"]
    assert athletics["value"] == sheet["derived"]["skills"]["athletics"]

    sword = _explain(game_client, p1, cid, hid, "attack:item.longsword")
    assert sword["value"] == next(
        a["attack_bonus"] for a in sheet["derived"]["attacks"] if a["key"] == "item.longsword"
    )
    assert "Урон 1d8" in sword["note"]

    hp = _explain(game_client, p1, cid, hid, "hp_max")
    assert hp["value"] == sheet["resources"]["hp_max"]
    assert _explain(game_client, p1, cid, hid, "hp")["history"] == []

    # чужой лист закрыт, неизвестная величина — понятная причина
    assert "чужой лист закрыт" in _explain(game_client, p2, cid, hid, "ac")["error"]
    assert "не знаю, как разобрать" in _explain(game_client, p1, cid, hid, "luck")["error"]


def _goblin(settings, cid):
    async def go(s):
        e = Entity(campaign_id=cid, kind="creature", name="Гоблин", template_id="creature.goblin",
                   state={"hp": 7, "hp_max": 7, "attitude": "hostile"})  # fmt: skip
        s.add(e)
        await s.commit()
        return e.id

    return run(settings, go)


def test_quick_action_skips_parser_but_not_validation(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    goblin = _goblin(settings, cid)
    sheet = ok(game_client.get(f"/api/campaigns/{cid}/characters/{hero['id']}", headers=p1))
    sword = next(i["id"] for i in sheet["inventory"] if i["item"] == "item.longsword")
    llm.replies += [DONE, DONE, {"text": "Клинок звенит."}]

    with connect(game_client, p1, cid) as (ws, _):
        attack = {"verb": "attack", "target_id": goblin, "instrument_id": sword}
        ws.send_json({"type": "message.send", "payload": {
            "kind": "action", "text": "Атакую гоблина длинным мечом", "client_id": "q1", "quick": {"actions": [attack]},
        }})  # fmt: skip
        m = next_of(ws, "message.new")
        assert m["payload"]["kind"] == "action"
    # пока реплика ждёт мастера, вторая не принимается (ожидающая реплика): дожидаемся ответа
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {
            "kind": "action", "text": "Взлетаю", "client_id": "q2", "quick": {"actions": [{"verb": "fly"}]},
        }})  # fmt: skip
        bad = next_of(ws, "message.rejected")["payload"]
    assert bad == {"reason": "быстрое действие не прошло проверку", "client_id": "q2"}
    assert llm.parser_requests == []  # модель намерение не разбирала
    (action,) = rows(settings, Message, Message.kind == "action")
    assert action.intent["actions"][0]["target_id"] == goblin and action.intent["actions"][0]["instrument_id"] == sword
