# ruff: noqa: F811
"""Тесты безопасности и изоляции повествовательного доступа (Task 20).

Проверяет:
1. Владелец без места мастера не видит закрытые причины режиссёра, черновики и секреты плана.
2. Безопасный статус NarrativePreparationStatusOut не содержит grounds, source_refs или summary.
3. Другая группа персонажей не видит чужие приватные нити и их количество.
4. Отключение адаптивного режима (переход в strict) сохраняет существующие overrides и факты.
5. Журнал мастера скрывает секреты и причины при выключенной настройке master_log_secrets.
"""

from __future__ import annotations

from app.core.narrative.threads import attention_count
from app.db.models import MasterTurn, NarrativeFact
from app.db.session import make_engine, make_sessionmaker
from tests.game import ok
from tests.narrative_helpers import thread
from tests.test_api import make_campaign
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401 - fixtures


def test_owner_without_master_seat_cannot_read_director_reasons(game_client, admin_g, settings):
    # Владелец создает кампанию с агентом-мастером (owner_plays=True, т.е. владелец занимает место игрока, не мастера)
    c = make_campaign(game_client, admin_g, brief={"length": "short"})
    cid = c["id"]

    # Доступ к плану
    plan_resp = ok(game_client.get(f"/api/campaigns/{cid}/plan", headers=admin_g))
    assert "grounds" not in plan_resp
    assert "draft" not in plan_resp
    assert "secret_summary" not in plan_resp
    assert "plan" not in plan_resp  # сырой каркас недоступен игроку

    # Доступ к безопасному статусу
    status_resp = ok(game_client.get(f"/api/campaigns/{cid}/narrative/status", headers=admin_g))
    assert status_resp["status"] in ("pending", "preparing", "ready", "failed")
    assert "grounds" not in status_resp
    assert "source_refs" not in status_resp
    assert "summary" not in status_resp


def test_foreign_group_cannot_see_private_threads_or_counts(tmp_path):
    # Проверка изоляции нитей между независимыми группами / персонажами
    t_public = thread(id="t-pub", status="active", audience=())
    t_hero1 = thread(id="t-priv-1", status="active", audience=("hero-1",))
    t_hero2 = thread(id="t-priv-2", status="active", audience=("hero-2",))

    all_threads = (t_public, t_hero1, t_hero2)

    # Герой 1 видит общую и свою нить, но не чужую нить героя 2
    assert attention_count(all_threads, audience=("hero-1",)) == 2
    # Герой 2 видит общую и свою нить, но не нить героя 1
    assert attention_count(all_threads, audience=("hero-2",)) == 2
    # Общая партия видит только публичную нить
    assert attention_count(all_threads, audience=("party",)) == 1


def test_mode_switch_to_strict_preserves_overrides(game_client, admin_g, settings):
    c = make_campaign(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]

    # Проверяем, что в настройках зафиксирован адаптивный режим
    c_info = ok(game_client.get(f"/api/campaigns/{cid}", headers=admin_g))
    assert c_info["settings"].get("narrative", {}).get("mode") == "adaptive"

    # Добавляем факт/оверрайд в БД
    import asyncio

    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)

    async def add_fact():
        async with maker() as s:
            f = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="creature.guard",
                key="motivation",
                version=1,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value="Специальный оверрайд",
                audience=["party"],
                snapshot_ref={"kind": "package", "source_id": "p1"},
            )
            s.add(f)
            await s.commit()

    asyncio.run(add_fact())

    # Переключаем режим на strict через PATCH
    patch_resp = ok(game_client.patch(f"/api/campaigns/{cid}", json={"narrative_mode": "strict"}, headers=admin_g))
    assert patch_resp["settings"].get("narrative", {}).get("mode") == "strict"

    # Проверяем, что факт не был удален из базы
    async def verify_fact():
        async with maker() as s:
            f = await s.get(NarrativeFact, cid + ":module:creature.guard:motivation")
            if f is None:
                from sqlalchemy import select

                res = await s.scalars(select(NarrativeFact).where(NarrativeFact.campaign_id == cid))
                facts = res.all()
                assert len(facts) == 1
                assert facts[0].value == "Специальный оверрайд"
            else:
                assert f.value == "Специальный оверрайд"

    asyncio.run(verify_fact())


def test_master_log_redacts_secrets_when_disabled(game_client, admin_g, settings):
    c = make_campaign(game_client, admin_g)
    cid = c["id"]

    import asyncio

    engine = make_engine(settings.database_url)
    maker = make_sessionmaker(engine)

    async def seed_turn():
        async with maker() as s:
            turn = MasterTurn(
                campaign_id=cid,
                session_id=None,
                status="completed",
                upto_seq=5,
                trace={
                    "calls": [
                        {
                            "tool": "whisper",
                            "secret": True,
                            "args": {"text": "секретное сообщение"},
                            "result": {"ok": True, "result": {"secret_detail": "спрятано"}},
                        }
                    ],
                    "advance": {"reason": "secret director step"},
                    "audit": {"secret_grounds": "hidden evidence"},
                },
            )
            s.add(turn)
            await s.commit()

    asyncio.run(seed_turn())

    # При выключенном показе секретов
    from dataclasses import replace

    game_client.app.state.settings = replace(game_client.app.state.settings, master_log_secrets=False)
    log = ok(game_client.get(f"/api/campaigns/{cid}/master-log", headers=admin_g))
    assert not log["secrets_visible"]
    turn_entry = log["turns"][0]
    call = turn_entry["calls"][0]
    assert call["secret"] is True
    assert "args" not in call
    assert "result" not in call
    assert turn_entry.get("audit") is None
    assert turn_entry.get("advance") is None
