# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Характер, который живёт (этап 9б): анкета, «Помочь», «Проверить», летопись и её откат, характер ИИ-мастера."""

from types import SimpleNamespace

from app.agents import character
from app.db.models import LlmCall
from tests.game import ok, party
from tests.test_master import DONE, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры

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


def test_master_try_works_without_ruleset_pack(game_client, admin_g, settings, llm):
    """Универсальная кампания не опирается на пакет правил: «Проверить» не требует каталога."""
    from sqlalchemy import delete

    from app.content.catalog import clear_cache
    from app.db.models import Campaign, ContentPack
    from tests.test_master import run

    c, _, _ = party(game_client, admin_g)

    async def drop(s):
        (await s.get(Campaign, c["id"])).content_chain = None
        await s.execute(delete(ContentPack))
        await s.commit()

    run(settings, drop)
    clear_cache()
    llm.replies += [{"text": "Серое утро."}, {"text": "Стражник хмурится."}, {"text": "Вы теряете время."}]
    url = f"/api/campaigns/{c['id']}/master-character/test"
    out = ok(game_client.post(url, json={"persona": {"text": "Суровый"}}, headers=admin_g))
    assert len(out["scenes"]) == 3
