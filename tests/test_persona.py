# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Характер, который живёт (этап 9б): анкета, «Помочь», «Проверить», летопись и её откат, характер ИИ-мастера."""

from types import SimpleNamespace

from app.agents import character
from app.db.models import LlmCall, PersonaNote
from tests.game import ok, party
from tests.test_ai_players import ai_party, build_hero, seat_ai
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_offline import narration
from tests.test_ws import connect, next_of

SHEET = {
    "text": "Угрюмый страж брода, верит только делам.",
    "fields": {"voice": "«Меньше слов. Больше дела.»", "fear": "воды", "junk": "лишнее поле"},
}


def test_hero_persona_saved_and_private(game_client, admin_g, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    url = f"/api/campaigns/{c['id']}/characters/{hero['id']}/persona"
    out = ok(game_client.put(url, json=SHEET, headers=p1))
    assert out["persona"]["fields"] == {"voice": "«Меньше слов. Больше дела.»", "fear": "воды"}
    assert out["persona"]["core"] == ["voice", "never", "conflict"] and out["can_edit"]
    assert [f["id"] for f in out["schema"]["fields"]][:3] == ["conflict", "want", "fear"]
    # владелец и мастер видят, но не правят; другой игрок не видит
    seen = ok(game_client.get(url, headers=admin_g))
    assert seen["persona"]["text"].startswith("Угрюмый") and not seen["can_edit"]
    assert game_client.put(url, json=SHEET, headers=admin_g).status_code == 403
    assert game_client.get(url, headers=p2).status_code == 403


def test_help_fills_only_empty_fields(game_client, admin_g, settings, llm):
    c, (p1,), hero = party(game_client, admin_g)
    url = f"/api/campaigns/{c['id']}/characters/{hero['id']}/persona"
    ok(game_client.put(url, json=SHEET, headers=p1))
    llm.replies.append(
        {"tool_calls": [("fill_persona", {"voice": "ПЕРЕПИСАНО", "want": "вернуть долг", "goal": "стать капитаном"})]}
    )
    out = ok(game_client.post(url + "/help", json={}, headers=p1))["persona"]
    assert out["fields"]["voice"] == "«Меньше слов. Больше дела.»"  # заполненное не трогаем
    assert out["fields"]["want"] == "вернуть долг" and out["fields"]["goal"] == "стать капитаном"
    ask = llm.requests[-1]
    assert "Угрюмый страж" in ask["messages"][1]["content"] and "Бран" in ask["messages"][1]["content"]
    assert set(ask["tools"][0]["function"]["parameters"]["properties"]) == {
        "conflict",
        "want",
        "party",
        "secret",
        "never",
        "goal",
    }
    # помощник предлагает, но не сохраняет
    assert "want" not in ok(game_client.get(url, headers=p1))["persona"]["fields"]
    calls = rows(settings, LlmCall, LlmCall.campaign_id == c["id"], LlmCall.purpose == "persona_help")
    assert len(calls) == 1


def test_try_scenes_use_unsaved_sheet(game_client, admin_g, settings, llm):
    c, (p1,), hero = party(game_client, admin_g)
    url = f"/api/campaigns/{c['id']}/characters/{hero['id']}/persona/test"
    llm.replies += [{"text": "«Короткой дорогой.»"}, {"text": "Бран отдаёт кошель."}, {"text": "Бран прыгает."}]
    out = ok(game_client.post(url, json={"persona": {"text": "Трус, но скрывает это"}}, headers=p1))
    assert [s["scene"] for s in out["scenes"]] == ["Спор в отряде", "Соблазн", "Опасность"]
    assert out["scenes"][1]["reply"] == "Бран отдаёт кошель."
    assert "Трус, но скрывает это" in llm.requests[0]["messages"][0]["content"]


def test_chronicle_notes_edit_revert_and_reach_the_agent(game_client, admin_g, settings, llm):
    c, p1, _ = ai_party(game_client, admin_g)
    cid = c["id"]
    seat = seat_ai(game_client, admin_g, cid)
    ch = build_hero(game_client, admin_g, cid, seat)
    url = f"/api/campaigns/{cid}/characters/{ch['id']}/persona"
    ok(
        game_client.put(
            url + f"?as_seat={seat}",
            json={"text": "Весельчак", "fields": {"never": "не бросит своих"}},
            headers=admin_g,
        )
    )

    note = {"text": "стал осторожнее и больше не шутит о смерти", "cause": "гибель Брана"}
    llm.replies += [
        {"tool_calls": [("write_chronicle", {"notes": [note, {"text": "  "}]})]},  # ИИ-герой; пустая запись отброшена
        {"tool_calls": [("write_chronicle", {"notes": []})]},  # ИИ-мастер: ничего не изменилось
    ]
    n = game_client.portal.call(character.chronicle, game_client.app.state.master, cid, "гибель Брана")
    assert n == 1
    ask = llm.requests[0]["messages"][1]["content"]
    assert "Весельчак" in ask and "Чего никогда не сделает (неизменно): не бросит своих" in ask
    got = ok(game_client.get(url + f"?as_seat={seat}", headers=admin_g))
    assert [x["text"] for x in got["notes"]] == [note["text"]] and got["notes"][0]["source"] == "event"
    nid = got["notes"][0]["id"]

    # владелец правит запись; игрок другого героя — нет
    assert game_client.patch(url + f"/notes/{nid}", json={"text": "x"}, headers=p1).status_code == 403
    edited = ok(
        game_client.patch(url + f"/notes/{nid}?as_seat={seat}", json={"text": "стал осторожнее"}, headers=admin_g)
    )
    assert edited["notes"][0]["text"] == "стал осторожнее" and edited["notes"][0]["edited"]

    # агент видит анкету и летопись в системной подсказке
    # ИИ-игрок заявляет действие до хода мастера, мастер отвечает на весь пакет
    llm.replies += [{"text": "Торин молча кивает."}, DONE, DONE, {"text": "Тихо."}]
    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Бран слушает"}})
        for _ in range(40):
            m = next_of(ws, "message.new")["payload"]
            if m["seat_id"] == seat:
                break
        narration(ws)
        game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    system = next(r for r in llm.requests if r["messages"][0]["content"].startswith("Ты — игрок"))["messages"][0][
        "content"
    ]
    assert "Весельчак" in system and "стал осторожнее" in system
    master_system = next(r for r in llm.requests if r["messages"][0]["content"].startswith("Ты — мастер"))["messages"][
        0
    ]["content"]
    assert "Характеры героев" in master_system and "Весельчак" in master_system

    # откат: запись остаётся в летописи, но в подсказку не идёт
    back = ok(game_client.patch(url + f"/notes/{nid}?as_seat={seat}", json={"reverted": True}, headers=admin_g))
    assert back["notes"][0]["reverted"]
    note_row = rows(settings, PersonaNote, PersonaNote.id == nid)[0]
    from app.core import persona

    assert "стал осторожнее" not in persona.render({"text": "x"}, [note_row])


def test_master_character_help_test_and_prompt(game_client, admin_g, settings, llm):
    c, (p1,), _ = party(game_client, admin_g)
    cid = c["id"]
    base = f"/api/campaigns/{cid}/master-character"
    assert game_client.get(base, headers=p1).status_code == 403
    out = ok(
        game_client.put(
            base, json={"text": "Мастер-насмешник", "fields": {"never": "не убивает героя без броска"}}, headers=admin_g
        )
    )
    assert out["persona"]["core"] == ["samples", "never"]
    assert [f["id"] for f in out["schema"]["fields"]] == ["tricks", "samples", "never", "party"]

    llm.replies.append({"tool_calls": [("fill_persona", {"tricks": "запахи и звуки", "never": "другое"})]})
    helped = ok(game_client.post(base + "/help", json={}, headers=admin_g))["persona"]
    assert helped["fields"]["tricks"] == "запахи и звуки" and helped["fields"]["never"] == "не убивает героя без броска"

    llm.replies += [{"text": "Таверна пахнет дымом."}, {"text": "Стражник смеётся."}, {"text": "Камни летят вниз."}]
    scenes = ok(game_client.post(base + "/test", json={}, headers=admin_g))["scenes"]
    assert [s["scene"] for s in scenes] == ["Описание места", "Реакция NPC", "Провал героя"]
    assert "Мастер-насмешник" in llm.requests[-1]["messages"][0]["content"]

    # стиль мастера в ходе: персона кампании плюс свой характер
    llm.replies += [DONE, DONE, {"text": "Дорога петляет."}]
    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "Бран идёт"}})
        narration(ws)
        game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    system = llm.requests[-3]["messages"][0]["content"]
    assert "Твой характер как мастера" in system and "Мастер-насмешник" in system


def test_strong_events_start_chronicle(game_client, monkeypatch):
    master = game_client.app.state.master
    reasons = []

    async def fake(svc, cid, reason, **kw):
        reasons.append(reason)
        return 0

    monkeypatch.setattr(character, "chronicle", fake)
    hero = SimpleNamespace(id="ch1", name="Бран", status="active", resources={"hp": 5})
    world = SimpleNamespace(characters={"ch1": hero}, scene=SimpleNamespace(mode="combat"))
    ctx = SimpleNamespace(campaign=SimpleNamespace(id="c1"), world=world, events=[])

    async def watch():
        master._watch_strong(ctx)  # задача летописи заводится в цикле событий

    game_client.portal.call(watch)  # первое наблюдение — только запомнить
    hero.resources = {"hp": 0, "dead": True}
    world.scene.mode = "explore"
    game_client.portal.call(watch)
    game_client.portal.call(master.wait_idle, "c1")
    assert reasons == ["пал герой Бран; бой закончился"]
    game_client.portal.call(watch)  # то же состояние — второй записи нет
    game_client.portal.call(master.wait_idle, "c1")
    assert len(reasons) == 1


def test_tables_fill_only_empty_places(game_client, admin_g, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    url = f"/api/campaigns/{c['id']}/characters/{hero['id']}/persona"
    draft = {"text": "", "fields": {"want": "своё: вернуть долг"}}
    out = ok(game_client.post(url + "/tables", json={"persona": draft}, headers=p1))
    got = out["persona"]
    assert got["fields"]["want"] == "своё: вернуть долг"  # заполненное не трогаем
    assert got["text"] and got["fields"]["secret"] and got["fields"]["conflict"]
    assert [x["slot"] for x in out["taken"]] == ["trait", "bond", "flaw"]
    # ничего не сохраняется само; другой игрок таблицами не пользуется
    assert ok(game_client.get(url, headers=p1))["persona"]["text"] == ""
    assert game_client.post(url + "/tables", json={}, headers=p2).status_code == 403
    # всё занято — пустой список, без ошибки
    again = ok(game_client.post(url + "/tables", json={"persona": got}, headers=p1))
    assert again["taken"] == [] and again["persona"] == got


def test_from_tables_prefers_own_table():
    from app.core import persona

    tables = [
        {"slot": "ideal", "rows": ["общий"]},
        {"slot": "ideal", "rows": ["для воина"], "for": ["class.fighter"]},
    ]
    first = lambda rows: rows[0]  # noqa: E731
    out, _ = persona.from_tables({}, tables, {"class.fighter"}, first)
    assert out["fields"]["want"] == "для воина"
    out, _ = persona.from_tables({}, tables, {"class.wizard"}, first)
    assert out["fields"]["want"] == "общий"


def test_marked_moment_starts_chronicle(game_client, monkeypatch):
    master = game_client.app.state.master
    reasons = []

    async def fake(svc, cid, reason, **kw):
        reasons.append(reason)
        return 0

    monkeypatch.setattr(character, "chronicle", fake)
    hero = SimpleNamespace(id="ch1", name="Бран", status="active", resources={"hp": 5})
    world = SimpleNamespace(characters={"ch1": hero}, scene=SimpleNamespace(mode="explore"))
    ev = SimpleNamespace(tool="mark_moment", payload={"label": "предательство", "text": "Марта сдала отряд страже"})
    ctx = SimpleNamespace(campaign=SimpleNamespace(id="c2"), world=world, events=[ev])

    async def watch():
        master._watch_strong(ctx)

    game_client.portal.call(watch)  # отметка работает и в первом наблюдении
    game_client.portal.call(master.wait_idle, "c2")
    assert reasons == ["предательство: Марта сдала отряд страже"]
