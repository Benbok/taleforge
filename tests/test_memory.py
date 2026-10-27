# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Память кампании: поиск по правилам и лору, сводки, «Ранее в кампании…», сборка контекста мастера."""

from app.agents import memory
from app.content.catalog import Catalog, Entry
from app.content.loader import load_with_dependencies
from app.core import knowledge
from app.db.models import Campaign, Summary
from tests.game import BASE, ok, party, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def base_catalog():
    chain, _ = load_with_dependencies(BASE, None)
    entries = {r.id: Entry(r.id, r.kind, r.status, p.id, r.data) for p in chain for r in p.records.values()}
    return Catalog(entries, []).view(False)


def test_rules_search_finds_by_russian_word_forms():
    cat = base_catalog()
    top = lambda q: knowledge.rules_for(cat, q, 1)[0].id  # noqa: E731
    assert top("прячусь в тени за бочкой") == "rule.hiding"
    assert top("хочу отдохнуть у костра до утра") == "rule.resting"
    assert top("спрыгиваю с обрыва") == "rule.falling"
    assert top("убеждаю стражника пропустить нас") == "rule.social"
    assert knowledge.rules_for(cat, "", 3) == []


def test_lore_visibility_filter():
    secs = [
        knowledge.Section(
            "l1", "lore_fact", "Левиафаны — ангелы", "Все знают: левиафаны пришли спасти людей.", "common"
        ),
        knowledge.Section("l2", "lore_fact", "Левиафаны — корабли", "Левиафаны — живые корабли глубин.", "hidden"),
    ]
    idx = knowledge.Index(secs)
    assert {s.id for s in idx.search("левиафаны", 5)} == {"l1", "l2"}
    assert [s.id for s in idx.search("левиафаны", 5, visible=("common",))] == ["l1"]
    assert "[только мастер]" in secs[1].render()


def add_whisper(settings, cid, text):
    """Шёпот мастеру прямо в журнал: без хода мастера, чтобы не тратить заготовленные ответы модели."""
    from app.core.chat import next_seq
    from app.db.models import Message

    async def go(s):
        c = await s.get(Campaign, cid)
        # последнее место игрока: при ожидающей реплике шёпот первого игрока не дал бы ему сходить
        seat = [x for x in c.seats if x.role == "player"][-1]
        s.add(
            Message(
                campaign_id=cid,
                seq=await next_seq(s, cid),
                seat_id=seat.id,
                kind="whisper",
                content=text,
                visible_to=[seat.id],
            )
        )
        await s.commit()

    run(settings, go)


def set_every(settings, cid, n):
    async def go(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "summary_every": n}
        await s.commit()

    run(settings, go)


def test_session_summary_and_recap(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [DONE, DONE, {"text": "Дорога пуста."}]
    act(game_client, p1, c["id"], "Иду по дороге на север")
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    (sm,) = rows(settings, Summary, Summary.campaign_id == c["id"])
    assert sm.kind == "session" and sm.session_id
    with connect(game_client, p1, c["id"]) as (ws, _):
        ok(game_client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin_g))
        texts = [next_of(ws, "message.new")["payload"]["content"] for _ in range(2)]
    assert texts[1] == "Ранее в кампании: " + memory.SummaryContent.model_validate(sm.content).recap


def test_rolling_summary_waits_for_enough_messages(game_client, admin_g, llm, settings):
    c, _, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    assert game_client.portal.call(master.summarize, c["id"]) is None  # одно сообщение из 30
    assert rows(settings, Summary) == [] and llm.parser_requests == []
