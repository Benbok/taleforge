# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Каркас кампании: выбор шаблона сюжета, проверки сервера, архитектор с повтором, версии, афиша и доступ."""

import copy

from app.core import plot
from app.db.models import CampaignPlan, CampaignSecret, LlmCall
from tests.game import ok
from tests.test_api import invite, make_campaign, register
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def good_plan() -> dict:
    """Каркас короткой кампании на шаблонах базового пакета."""
    return {
        "title": "Туман над Солёной бухтой",
        "tagline": "В порту пропадают корабли, а в тумане поют.",
        "tags": ["мистика", "порт", "3–5 сессий"],
        "public_intro": "Рыбацкий порт живёт в страхе: корабли уходят в туман и не возвращаются.",
        "structure_id": "plot.investigation",
        "conflict": "Культ приманивает корабли песней, чтобы открыть путь тому, что спит под водой.",
        "stakes": "Порт опустеет, а спящее проснётся.",
        "antagonists": [
            {
                "id": "villain",
                "name": "Мать Ирса",
                "template_id": "creature.cult_fanatic",
                "goal": "Разбудить спящего под бухтой",
                "methods": "Культ среди портовых, песня в тумане",
                "weakness": "Без маяка песня не слышна",
                "secret": "Сама слышит голос и боится его",
                "threat": ["Пропадает ещё корабль", "Культ захватывает маяк", "Песня звучит днём", "Спящий шевелится"],
            }
        ],
        "locations": [
            {
                "id": "loc_port",
                "name": "Солёная бухта",
                "template_id": "location.port",
                "role": "Начало",
                "mood": "Сырость и тревога",
                "secret": "Смотритель порта в культе",
            },
            {
                "id": "loc_tavern",
                "name": "Кривой якорь",
                "template_id": "location.tavern",
                "role": "Слухи",
                "mood": "Шумно и пьяно",
                "secret": "В погребе собирается культ",
            },
            {
                "id": "loc_light",
                "name": "Старый маяк",
                "template_id": "location.ruins",
                "role": "Логово культа",
                "mood": "Ветер и крики чаек",
                "secret": "Линза маяка сделана из кости",
            },
            {
                "id": "loc_crypt",
                "name": "Затопленный склеп",
                "template_id": "location.crypt",
                "role": "Финал",
                "mood": "Вода по колено",
                "secret": "Здесь спит древнее",
            },
        ],
        "npcs": [
            {
                "id": "npc_warden",
                "name": "Бертольд",
                "template_id": "creature.noble",
                "role": "Смотритель порта",
                "want": "Сохранить власть",
                "fear": "Разоблачения",
                "secret": "Служит культу",
                "attitude": "Любезен",
                "look": "Толстяк в бархате",
                "location_id": "loc_port",
            },
            {
                "id": "npc_keeper",
                "name": "Лис",
                "template_id": "creature.commoner",
                "role": "Трактирщик",
                "want": "Тишины",
                "fear": "Культа",
                "secret": "Видел ритуал",
                "attitude": "Насторожен",
                "look": "Худой, с бельмом",
                "location_id": "loc_tavern",
            },
            {
                "id": "npc_guard",
                "name": "Марта",
                "template_id": "creature.guard",
                "role": "Стражница",
                "want": "Найти брата",
                "fear": "Моря",
                "secret": "Брат в культе",
                "attitude": "Ищет помощи",
                "look": "Рыжая, в кольчуге",
            },
        ],
        "factions": [{"name": "Портовые", "stance": "Боятся и молчат"}],
        "acts": [
            {
                "id": "act1",
                "title": "Туман",
                "goal": "Понять, что с кораблями",
                "exit": "Найден след к маяку",
                "nodes": [
                    {"id": "n_arrival", "title": "Пропажа", "summary": "Уходит ещё корабль", "location_id": "loc_port"},
                    {
                        "id": "n_rumors",
                        "title": "Слухи",
                        "summary": "В таверне шепчут о песне",
                        "location_id": "loc_tavern",
                        "npc_ids": ["npc_keeper"],
                    },
                ],
            },
            {
                "id": "act2",
                "title": "Маяк",
                "goal": "Остановить песню",
                "exit": "Культ разбит",
                "milestone_level": 3,
                "nodes": [
                    {"id": "n_light", "title": "Маяк", "summary": "Культ на маяке", "location_id": "loc_light"},
                    {
                        "id": "n_betrayal",
                        "title": "Измена",
                        "summary": "Смотритель выдаёт себя",
                        "npc_ids": ["npc_warden"],
                    },
                ],
            },
            {
                "id": "act3",
                "title": "Спящий",
                "goal": "Не дать проснуться",
                "exit": "Финал",
                "nodes": [
                    {
                        "id": "n_crypt",
                        "title": "Склеп",
                        "summary": "Ритуал в склепе",
                        "location_id": "loc_crypt",
                        "npc_ids": ["villain"],
                    },
                    {"id": "n_end", "title": "Выбор", "summary": "Запечатать или уничтожить"},
                ],
            },
        ],
        "reveals": [
            {
                "id": "r_cult",
                "truth": "Корабли губит культ",
                "node_id": "n_light",
                "clues": [
                    {"at": "npc_keeper", "text": "Видел ритуал"},
                    {"at": "loc_port", "text": "Журнал смотрителя подчищен"},
                    {"at": "npc_guard", "text": "Брат пел ту же песню"},
                ],
            },
            {
                "id": "r_sleeper",
                "truth": "Под бухтой спит древнее",
                "node_id": "n_crypt",
                "clues": [
                    {"at": "loc_light", "text": "Костяная линза"},
                    {"at": "loc_crypt", "text": "Надписи на стенах"},
                    {"at": "villain", "text": "Проговаривается в гневе"},
                ],
            },
        ],
        "endings": ["Спящий запечатан, культ разбит", "Порт покинут, спящий ждёт"],
    }


def plan_call(p):
    return {"tool_calls": [(plot.TOOL, p)]}


class FakeCatalog:
    """Каталог базового пакета для проверок без базы: только то, на что смотрит plot.check."""

    ids = {
        "location_template": {"location.port", "location.tavern", "location.ruins", "location.crypt"},
        "creature_template": {"creature.cult_fanatic", "creature.noble", "creature.commoner", "creature.guard"},
        "faction": set(),
    }

    def find(self, rid, kind=None):
        kinds = [kind] if kind else list(self.ids)
        return object() if any(rid in self.ids.get(k, ()) for k in kinds) else None

    def by_kind(self, kind):
        return list(self.ids.get(kind, ()))

    def search(self, kind, query, limit=3):
        return []


def test_check_accepts_good_plan_and_marks_sketches():
    p, errors = plot.check(good_plan(), length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == [] and p is not None
    assert {x["status"] for x in p["locations"] + p["npcs"]} == {"sketch"}
    assert p["acts"][0]["status"] == "active" and p["acts"][1]["status"] == "pending"
    assert p["antagonists"][0]["threat_step"] == 0 and p["reveals"][0]["revealed"] is False


def test_check_reports_problems():
    bad = copy.deepcopy(good_plan())
    bad["npcs"][0]["template_id"] = "creature.dragon_king"
    bad["reveals"][0]["clues"] = bad["reveals"][0]["clues"][:2]
    bad["acts"] = bad["acts"][:2]
    bad["locations"][1]["id"] = "loc_port"
    bad["acts"][0]["nodes"][0]["location_id"] = "loc_nowhere"
    bad["antagonists"][0]["methods"] = "Пытки пленников"
    p, errors = plot.check(bad, length="short", catalog=FakeCatalog(), excluded=["пытки"])
    text = "\n".join(errors)
    assert p is None
    assert "нет шаблона creature.dragon_king" in text
    assert "r_cult: нужно не меньше 3 зацепок" in text
    assert "актов для длительности «короткая, 3–5 сессий»: от 3 до 3, сейчас 2" in text
    assert "id loc_port повторяется" in text
    assert "нет локации loc_nowhere" in text
    assert "запретные темы: пытки" in text


def test_pick_structure_follows_brief():
    class E:
        def __init__(self, id, data):
            self.id, self.data, self.name = id, data, id

    heist = E("plot.heist", {"pillars": {"social": 2, "puzzles": 2}, "emotions": ["humor"]})
    siege = E("plot.siege", {"pillars": {"combat": 2}, "emotions": ["heroism", "fear"]})
    brief = {"pillars": {"combat": "high"}, "emotions": ["fear"]}
    assert plot.pick_structure([heist, siege], brief).id == "plot.siege"
    assert plot.pick_structure([heist, siege], {"emotions": ["humor"]}).id == "plot.heist"
    assert plot.pick_structure([heist, siege], brief, "plot.heist").id == "plot.heist"


def test_architect_retries_then_saves_plan(game_client, admin_g, llm, settings):
    c = make_campaign(game_client, admin_g, brief={"length": "short", "pillars": {"mystery": "high"}})
    opts = ok(game_client.get(f"/api/campaigns/{c['id']}/plan/options", headers=admin_g))
    assert opts["structures"][0]["best"] and opts["structure_id"] == opts["structures"][0]["id"]
    assert len(opts["structures"]) == 7 and opts["estimate"]["tokens_out"] == 6000

    bad = good_plan()
    bad["npcs"][0]["template_id"] = "creature.nope"
    llm.replies += [plan_call(bad), plan_call(good_plan())]
    r = ok(game_client.post(f"/api/campaigns/{c['id']}/plan", json={"note": "мрачнее"}, headers=admin_g), 202)
    assert r["status"] == "generating"
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])

    # вторая попытка получила ошибки первой
    tool_msg = llm.requests[1]["messages"][-1]
    assert tool_msg["role"] == "tool" and "нет шаблона creature.nope" in tool_msg["content"]
    assert "мрачнее" in llm.requests[0]["messages"][1]["content"]
    assert "Шаблон сюжета (plot." in llm.requests[0]["messages"][1]["content"]

    st = ok(game_client.get(f"/api/campaigns/{c['id']}/plan", headers=admin_g))
    assert st["status"] == "ready" and st["version"] == 1 and st["versions"] == 1
    assert st["poster"] == {
        "title": "Туман над Солёной бухтой",
        "tagline": "В порту пропадают корабли, а в тумане поют.",
        "tags": ["мистика", "порт", "3–5 сессий"],
    }
    assert st["public_intro"].startswith("Рыбацкий порт") and "plan" not in st  # владелец не мастер: без каркаса
    (secret,) = rows(settings, CampaignSecret)
    assert secret.plot["title"] == "Туман над Солёной бухтой" and secret.plot["version"] == 1
    # после каркаса мастер сразу готовит вступление ко всей кампании
    assert [x.purpose for x in rows(settings, LlmCall)] == ["plan", "plan", "campaign_intro"]
    (secret,) = rows(settings, CampaignSecret)  # вступление лежит в тайнах до старта, игроки его ещё не видят
    assert secret.setting["campaign_intro"]["text"] and secret.setting["campaign_intro"]["version"] == 1

    # второй вариант — новая версия, завязка из каркаса обновляется
    second = good_plan() | {"title": "Песнь маяка", "public_intro": "Маяк снова горит."}
    llm.replies += [plan_call(second)]
    ok(game_client.post(f"/api/campaigns/{c['id']}/plan", json={}, headers=admin_g), 202)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert "Туман над Солёной бухтой" in llm.requests[2]["messages"][1]["content"]  # не повторять прошлый
    st = ok(game_client.get(f"/api/campaigns/{c['id']}/plan", headers=admin_g))
    assert st["version"] == 2 and st["public_intro"] == "Маяк снова горит."
    assert [p.version for p in rows(settings, CampaignPlan)] == [1, 2]

    # игрокам — только афиша в настройках кампании, каркас и статус подготовки им не нужны
    inv = invite(game_client, admin_g, c["id"])
    head = register(game_client, inv["token"], "Гимли")
    assert game_client.get(f"/api/campaigns/{c['id']}/plan", headers=head).status_code == 403
    assert game_client.get(f"/api/campaigns/{c['id']}/secrets", headers=head).status_code == 404
    assert (
        ok(game_client.get(f"/api/campaigns/{c['id']}", headers=head))["settings"]["poster"]["title"] == "Песнь маяка"
    )


def test_architect_gives_up_after_three_attempts(game_client, admin_g, llm):
    c = make_campaign(game_client, admin_g, brief={"length": "short"})
    bad = good_plan()
    bad["endings"] = ["один финал"]
    llm.replies += [plan_call(bad)] * 3
    ok(game_client.post(f"/api/campaigns/{c['id']}/plan", json={}, headers=admin_g), 202)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    st = ok(game_client.get(f"/api/campaigns/{c['id']}/plan", headers=admin_g))
    assert st["status"] == "failed" and "финалов от 2 до 3" in st["error"] and st["versions"] == 0


def test_human_master_sees_plan_and_no_regeneration_after_start(game_client, admin_g, llm):
    c = make_campaign(game_client, admin_g, master={"type": "owner"}, brief={"length": "short"})
    llm.replies += [plan_call(good_plan())]
    ok(game_client.post(f"/api/campaigns/{c['id']}/plan", json={"structure_id": "plot.heist"}, headers=admin_g), 202)
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert "Шаблон сюжета (plot.heist)" in llm.requests[0]["messages"][1]["content"]
    st = ok(game_client.get(f"/api/campaigns/{c['id']}/plan", headers=admin_g))
    assert st["plan"]["title"] == "Туман над Солёной бухтой" and st["plan"]["structure_id"] == "plot.heist"
    bad = game_client.post(f"/api/campaigns/{c['id']}/plan", json={"structure_id": "plot.nope"}, headers=admin_g)
    assert bad.status_code == 404
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin_g))
    r = game_client.post(f"/api/campaigns/{c['id']}/plan", json={}, headers=admin_g)
    assert r.status_code == 409 and "игра уже началась" in r.json()["detail"]


def test_render_for_master():
    p, _ = plot.check(good_plan(), length="short", catalog=FakeCatalog(), excluded=[])
    text = plot.render(p)
    assert "Каркас кампании «Туман над Солёной бухтой»" in text
    assert "Следующий шаг угрозы: Пропадает ещё корабль" in text
    assert "Акт act1 «Туман» [active]" in text and "узел n_rumors [sketch] Слухи @loc_tavern (npc_keeper)" in text
    assert "Тайна r_cult (не раскрыта) → n_light" in text and "Возможные финалы:" in text
