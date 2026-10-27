# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Ведение по каркасу: «Сюжет сейчас», инструменты сюжета, часы угроз, пересмотр между актами и скрытность."""

import copy

import pytest

from app.core import plot
from app.db.models import CampaignSecret, MasterTurn
from tests.game import run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_plan import FakeCatalog, good_plan


def last_turn(settings) -> MasterTurn:
    # без ORDER BY PostgreSQL отдаёт строки в порядке хранения: обновлённый ход уезжает в конец
    return sorted(rows(settings, MasterTurn), key=lambda t: t.started_at)[-1]


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
