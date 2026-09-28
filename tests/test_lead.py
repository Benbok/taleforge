# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Ведение по каркасу: «Сюжет сейчас», инструменты сюжета, часы угроз, пересмотр между актами и скрытность."""

import copy

import pytest

from app.core import plot
from app.db.models import Campaign, CampaignPlan, CampaignSecret, Entity, Event, MasterTurn, Scene
from tests.game import ok, party, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_plan import FakeCatalog, good_plan


def checked() -> dict:
    p, errors = plot.check(good_plan(), length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == []
    return p


def names(request) -> set[str]:
    return {t["function"]["name"] for t in request["tools"] or []}


def test_clock_moves_threats_by_game_days():
    p = checked()
    assert plot.clock(p, 1000, "short") == [] and p["clock_at"] == 1000  # первый вызов — точка отсчёта
    assert plot.clock(p, 1000 + 2 * plot.DAY, "short") == []
    ticks = plot.clock(p, 1000 + 7 * plot.DAY, "short")  # два полных срока по 3 дня
    assert [step for _, step, _ in ticks] == ["Пропадает ещё корабль", "Культ захватывает маяк"]
    assert p["antagonists"][0]["threat_step"] == 2 and p["clock_at"] == 1000 + 6 * plot.DAY
    one = checked()
    assert plot.clock(one, 0, "oneshot") == [] and plot.clock(one, 30 * plot.DAY, "oneshot") == []


def test_now_block_shows_current_act_and_what_is_near():
    p = checked()
    plot.close_node(p, "n_arrival", "done", "Корабль «Чайка» ушёл в туман")
    plot.develop_sketch(p, "loc_tavern", "Низкий зал, пахнет рыбой", "en_tav")
    text = plot.now_block(p, location_entity_id="en_tav")
    assert "Текущий акт 1 из 3: act1 «Туман»" in text
    assert "узел n_arrival [пройден] Пропажа: итог — Корабль «Чайка» ушёл в туман" in text
    assert "узел n_rumors [открыт] Слухи @loc_tavern (npc_keeper)" in text
    assert "Отряд сейчас в месте каркаса loc_tavern" in text
    assert "loc_tavern Кривой якорь [развёрнут, в реестре en_tav]" in text and "Детали: Низкий зал" in text
    assert "npc_keeper Лис [набросок]" in text
    assert "loc_crypt" not in text  # дальние места — через get_plot
    assert "Тайна r_cult" not in text  # тайна ведёт в узел второго акта
    assert "следующий шаг угрозы (1/4): Пропадает ещё корабль" in text and "Дальше: «Маяк»" in text
    with pytest.raises(plot.PlotError):
        plot.close_node(p, "n_arrival", "done", "ещё раз")
    assert plot.valid_ids(p, "nodes") == ["n_rumors", "n_light", "n_betrayal", "n_crypt", "n_end"]
    assert "loc_tavern" not in plot.valid_ids(p, "sketches")


def test_revision_keeps_played_act_and_checks_references():
    p = checked()
    plot.close_node(p, "n_arrival", "done", "Корабль пропал")
    rev = {
        "summary": "Маяк раньше",
        "acts": [
            {"id": "act1", "title": "Другое", "goal": "-", "exit": "-", "nodes": []},  # в нём уже играли: не меняется
            {
                "id": "act2",
                "title": "Маяк в огне",
                "goal": "Пробиться на маяк",
                "exit": "Культ разбит",
                "nodes": [
                    {"id": "n_light", "title": "Штурм", "summary": "Культ держит маяк"},
                    {"id": "n_boat", "title": "Лодка", "summary": "Нужна лодка", "location_id": "loc_new"},
                ],
            },
            copy.deepcopy(p["acts"][2]),
        ],
        "locations": [
            {"id": "loc_new", "name": "Причал", "template_id": "location.port", "role": "-", "mood": "-", "secret": "-"}
        ],
    }
    merged, errors = plot.merge_revision(p, rev)
    assert errors == []
    merged, errors = plot.check(merged, length="short", catalog=FakeCatalog(), excluded=[], keep_state=True)
    assert errors == [], errors
    assert merged["acts"][0]["title"] == "Туман" and merged["acts"][0]["status"] == "active"
    assert merged["acts"][0]["nodes"][0]["status"] == "done"
    assert merged["acts"][1]["title"] == "Маяк в огне" and merged["acts"][1]["status"] == "pending"
    assert [x["id"] for x in merged["locations"]][-1] == "loc_new" and len(merged["locations"]) == 5

    # тайна ссылается на узел, который пересмотр выбросил
    rev["acts"][1]["nodes"] = rev["acts"][1]["nodes"][1:]
    merged, _ = plot.merge_revision(p, rev)
    _, errors = plot.check(merged, length="short", catalog=FakeCatalog(), excluded=[], keep_state=True)
    assert any("тайна r_cult: нет узла n_light" in e for e in errors)


def set_plan(settings, cid, p):
    async def go(s):
        secret = await s.get(CampaignSecret, cid)
        if secret is None:
            secret = CampaignSecret(campaign_id=cid)
            s.add(secret)
        secret.plot = p
        await s.commit()

    run(settings, go)


def test_master_leads_by_plan(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g, brief={"length": "short"})
    cid = c["id"]

    # без каркаса инструментов сюжета у мастера нет
    llm.replies += [DONE, DONE, {"text": "Туман."}]
    act(game_client, p1, cid, "Жду у причала")
    assert (
        "advance_plot" not in names(llm.requests[0]) and "Сюжет сейчас" not in llm.requests[0]["messages"][0]["content"]
    )

    set_plan(settings, cid, checked())
    start = len(llm.requests)
    calls = [
        ("develop", {"sketch_id": "loc_port", "details": "Сети сушатся на ветру", "here": True}),
        ("develop", {"sketch_id": "npc_warden", "details": "Говорит медленно, потеет", "here": True}),
        ("advance_plot", {"node_id": "n_arrival", "outcome": "Герои видели, как «Чайка» ушла в туман"}),
        ("advance_plot", {"node_id": "n_rumors", "result": "skipped", "outcome": "В таверну не пошли"}),
        ("plot_reveal", {"reveal_id": "r_cult", "how": "Бертольд проговорился"}),
        ("threat_tick", {"antagonist_id": "villain", "reason": "герои медлили"}),
        ("end_act", {"outcome": "След ведёт к маяку"}),
        ("auto_success", {"character_id": hero["id"], "reason": "осмотр порта"}),
    ]
    revision = {
        "summary": "Смотритель разоблачён раньше: акт про маяк начинается со штурма",
        "acts": [
            {
                "id": "act2",
                "title": "Штурм маяка",
                "goal": "Взять маяк",
                "exit": "Культ разбит",
                "milestone_level": 3,
                "nodes": [
                    {"id": "n_light", "title": "Маяк", "summary": "Культ укрепил маяк", "location_id": "loc_light"},
                    {"id": "n_escape", "title": "Бегство", "summary": "Бертольд бежит к культу"},
                ],
            },
            copy.deepcopy(good_plan()["acts"][2]),
        ],
    }
    llm.replies += [
        {"tool_calls": calls},
        DONE,
        {"text": "Туман густеет над бухтой."},
        {"tool_calls": [(plot.REVISE_TOOL, revision)]},
    ]
    n = act(game_client, p1, cid, "Осматриваю порт и расспрашиваю смотрителя")
    assert n["content"] == "Туман густеет над бухтой."

    decide, _, narrate, replan = llm.requests[start:]
    assert {"advance_plot", "develop", "threat_tick", "end_act", "get_plot"} <= names(decide)
    enum = next(t for t in decide["tools"] if t["function"]["name"] == "develop")["function"]["parameters"]
    assert "loc_port" in enum["properties"]["sketch_id"]["enum"]
    system = decide["messages"][0]["content"]
    assert "Сюжет сейчас — «Туман над Солёной бухтой»" in system and "Как вести по каркасу" in system
    assert "Текущий акт 1 из 3" in system and "loc_crypt" not in system
    assert "[СЮЖЕТ: только для мастера" in narrate["messages"][1]["content"]
    assert replan["messages"][0]["content"] == plot.REVISE_SYSTEM and names(replan) == {plot.REVISE_TOOL}
    assert (
        "итог — Герои видели" in replan["messages"][1]["content"] or "Герои видели" in replan["messages"][1]["content"]
    )

    turn = rows(settings, MasterTurn)[-1]
    assert all(x["result"]["ok"] for x in turn.trace["calls"]), turn.trace["calls"]

    (secret,) = rows(settings, CampaignSecret)
    p = secret.plot
    port = next(x for x in p["locations"] if x["id"] == "loc_port")
    warden = next(x for x in p["npcs"] if x["id"] == "npc_warden")
    assert port["status"] == "developed" and warden["status"] == "developed"
    ents = {e.id: e for e in rows(settings, Entity, Entity.campaign_id == cid)}
    loc, npc = ents[port["entity_id"]], ents[warden["entity_id"]]
    assert loc.kind == "location" and loc.name == "Солёная бухта" and loc.template_id == "location.port"
    assert npc.kind == "creature" and npc.template_id == "creature.noble" and npc.location_id == loc.id
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.location_id == loc.id
    assert [a["status"] for a in p["acts"]] == ["done", "active", "pending"]
    assert p["acts"][0]["outcome"] == "След ведёт к маяку" and p["acts"][0]["nodes"][1]["status"] == "skipped"
    assert p["acts"][1]["title"] == "Штурм маяка"  # пересмотр лёг на акт, в котором ещё ничего не прошли
    assert p["reveals"][0]["revealed"] and p["antagonists"][0]["threat_step"] == 1 and "clock_at" in p
    (row,) = rows(settings, CampaignPlan)
    assert row.version == 1 and row.note.startswith("пересмотр: Смотритель разоблачён")
    assert all(e.hidden for e in rows(settings, Event, Event.tool.in_(["advance_plot", "develop", "end_act"])))

    # игрокам — только статус пересмотра, без итога и каркаса
    st = ok(game_client.get(f"/api/campaigns/{cid}", headers=p1))["settings"]["plan"]
    assert st["revision"] == {"status": "ready"} and "Смотритель" not in str(st)
    assert game_client.get(f"/api/campaigns/{cid}/plan", headers=p1).status_code == 403

    # закрытый узел второй раз не закрыть: его нет среди допустимых id
    (camp,) = rows(settings, Campaign, Campaign.id == cid)
    assert camp.brief["length"] == "short"
    llm.replies += [
        {"tool_calls": [("advance_plot", {"node_id": "n_arrival", "outcome": "снова"})]},
        DONE,
        DONE,
        {"text": "Ветер."},
    ]
    act(game_client, p1, cid, "Жду")
    turn = rows(settings, MasterTurn)[-1]
    first = turn.trace["calls"][0]
    assert first["tool"] == "advance_plot" and not first["result"]["ok"] and "n_arrival" in first["result"]["error"]
