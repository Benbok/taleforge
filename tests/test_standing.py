"""Последствия поступков и случайности мира: отношение NPC и фракций, их ответ, вдохновение, встречи и находки."""

from app.core import standing as sd
from app.db.models import Campaign, Entity
from app.tools import fortune, standing
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context
from tests.game import QueueDice, import_base, ok, party, run
from tests.test_api import invite, make_campaign, register
from tests.test_worlds import ECHO_FIGHTER, worlds  # noqa: F401 — фикстура


def echo_party(client, admin, **kw):
    """Тестовая кампания мира (черновые записи пакета видны) с одобренным героем."""
    body = {"creation_rules": {"review": "auto"}, "collect_window_sec": 0, "test_mode": True, **kw}
    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans", **body)
    h = register(client, invite(client, admin, c["id"])["token"], "Арагорн")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=ECHO_FIGHTER, headers=h), 201)
    assert ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=h))["status"] == "approved"
    ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
    return c["id"], ch["id"], h


def play(settings, cid, dice, fn):
    async def go(s):
        ctx = await open_context(s, await s.get(Campaign, cid), QueueDice(dice), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


def test_tiers_follow_points():
    assert [sd.tier_of(p) for p in (0, 1, 2, 4, 5, 9, 10, 15)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert [sd.tier_of(p) for p in (-1, -2, -5, -10)] == [0, -1, -2, -3]


def test_help_to_faction_ripples_and_ripens_into_gratitude(client, admin, settings, worlds):  # noqa: F811
    cid, hero, _ = echo_party(client, admin)

    async def go(ctx):
        deed = await execute(
            ctx,
            "record_deed",
            {
                "subject_id": "faction.miners_underground",
                "character_ids": [hero],
                "effect": "help",
                "weight": "major",
                "reason": "вывели беглых детей из шахты",
            },
        )
        early = await standing.run_standing(ctx)
        early_resolve = await execute(ctx, "resolve_response", {"response_id": "resp1", "how": "рано"})
        await execute(ctx, "advance_time", {"amount": 5, "unit": "day", "reason": "путь"})
        note = await standing.run_standing(ctx)
        view = await execute(ctx, "get_standing", {})
        done = await execute(ctx, "resolve_response", {"response_id": "resp1", "how": "дали карту протоков"})
        return deed, early, early_resolve, note, view, done

    deed, early, early_resolve, note, view, done = play(settings, cid, [], go)
    assert deed["ok"], deed
    changes = {c["subject"]: c for c in deed["result"]["changes"]}
    main = changes["Шахтёрское подполье"]
    assert main["tier"] == "благосклонны (+1)" and main["response"]["mood"] == "благодарность"
    assert main["response"]["due_in_hours"] == 48  # 1d4 дня: пустая очередь кубиков даёт 2
    # враг подполья недоволен, союзник рад: круги по отношениям фракций пакета
    assert changes["Синдикаты Крови"]["points"] == -1 and changes["Низшее духовенство"]["points"] == 1
    assert early == "" and not early_resolve["ok"] and "ещё не готовы" in early_resolve["error"]
    assert "resp1: Шахтёрское подполье" in note and "Листовка с картой тайных протоков" in note
    assert "для: Арагорн" in note or "для: Ржавый" in note
    assert view["result"]["responses"][0]["status"] == "ready"
    assert done["ok"] and done["result"]["mood"] == "благодарность"


def test_harm_to_npc_turns_to_revenge_at_once(client, admin, settings, worlds):  # noqa: F811
    cid, hero, _ = echo_party(client, admin)

    async def go(ctx):
        sp = await execute(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.syndicate_guard", "name": "Стражник Прохор", "attitude": "friendly"},
        )
        guard = sp["result"]["spawned"][0]["id"]
        deed = await execute(
            ctx,
            "record_deed",
            {
                "subject_id": guard,
                "character_ids": [hero],
                "effect": "harm",
                "weight": "critical",
                "reason": "избили и отобрали ключи",
            },
        )
        note = await standing.run_standing(ctx)
        return guard, deed, note

    guard, deed, note = play(settings, cid, [], go)
    assert deed["ok"], deed
    main, *rest = deed["result"]["changes"]
    assert main["tier"] == "враждебны (-2)" and main["attitude"] == "neutral"
    # стражник — человек Синдиката: фракция узнаёт и тоже злится, но слабее
    assert rest[0]["subject"] == "Синдикаты Крови" and rest[0]["points"] == -3
    assert "resp1: Стражник Прохор" in note and "месть" in note and "сейчас в сцене" in note

    async def attitude(s):
        return (await s.get(Entity, guard)).state["attitude"]

    assert run(settings, attitude) == "neutral"  # остыл сам, но нападать решает мастер


def test_secret_deed_changes_nothing_until_exposed(client, admin, settings, worlds):  # noqa: F811
    cid, hero, _ = echo_party(client, admin)

    async def go(ctx):
        hidden = await execute(
            ctx,
            "record_deed",
            {
                "subject_id": "faction.house_liquor",
                "character_ids": [hero],
                "effect": "harm",
                "weight": "major",
                "secret": True,
                "reason": "подменили партию ликвора",
            },
        )
        before = await execute(ctx, "get_standing", {})
        exposed = await execute(ctx, "expose_deed", {"deed_id": "deed1", "how": "курьер проболтался"})
        again = await execute(ctx, "expose_deed", {"deed_id": "deed1", "how": "ещё раз"})
        return hidden, before, exposed, again

    hidden, before, exposed, again = play(settings, cid, [], go)
    assert hidden["ok"] and hidden["result"]["secret_deed"] == "deed1"
    assert before["result"]["standing"] == [] and before["result"]["secret_deeds"][0]["subject"] == "Дом Ликвора"
    assert exposed["ok"] and exposed["result"]["changes"][0]["tier"] == "настороже (-1)"
    assert not again["ok"] and "нет тайного поступка" in again["error"]


def test_inspiration_gives_advantage_once(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin)

    check = {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "x"}
    check["inspiration"] = True

    async def go(ctx):
        none = await execute(ctx, "roll_check", check)
        got = await execute(ctx, "grant_inspiration", {"character_id": ch["id"], "reason": "прикрыл товарища"})
        twice = await execute(ctx, "grant_inspiration", {"character_id": ch["id"], "reason": "ещё"})
        used = await execute(ctx, "roll_check", check)
        return none, got, twice, used

    none, got, twice, used = play(settings, c["id"], [3, 18], go)
    assert not none["ok"] and "нет вдохновения" in none["error"]
    assert got["ok"] and not twice["ok"] and "не копится" in twice["error"]
    assert used["ok"] and used["result"]["inspiration_spent"]
    assert "преимущество: вдохновение" in used["result"]["reasons"]
    assert used["result"]["total"] >= 18  # из двух кубиков взят больший
    sheet = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=admin))
    assert sheet["resources"]["inspiration"] is False


def _at_old_mother(ctx):
    return execute(
        ctx,
        "create_location",
        {"name": "Старая Мать", "template_id": "location.old_mother", "make_current": True},
    )


def test_encounter_by_place_knows_the_party_standing(client, admin, settings, worlds):  # noqa: F811
    cid, _, _ = echo_party(client, admin)

    async def go(ctx):
        await _at_old_mother(ctx)
        # отряд уже насолил Синдикатам: −6 очков, «враждебны»
        subj = {"kind": "faction", "name": "Синдикаты Крови", "points": -6, "deeds": []}
        ctx.world.scene.state = {"standing": {"subjects": {"faction.syndicates": subj}}}
        return await execute(ctx, "roll_fortune", {"kind": "encounter", "reason": "идут по улицам"})

    # бросок таблицы Старой Матери 1 и число стражников 1d3 + 1
    r = play(settings, cid, [1, 2], go)
    assert r["ok"], r
    res = r["result"]
    assert res["table"] == "Старая Мать" and res["roll"] == 1
    guards = res["creatures"][0]
    assert guards["template"] == "creature.syndicate_guard" and guards["count"] == 3
    assert guards["party_standing"] == "враждебны (-2)" and guards["attitude"] == "neutral"
    assert "spawn_entity creature_template_id=creature.syndicate_guard count=3 attitude=neutral" in res["next"]


def test_find_lies_in_scene_and_may_bite(client, admin, settings, worlds):  # noqa: F811
    cid, _, _ = echo_party(client, admin)

    async def go(ctx):
        await _at_old_mother(ctx)
        r = await execute(
            ctx, "roll_fortune", {"kind": "find", "table_id": "loot_table.tier1_carcass", "reason": "обыск выработки"}
        )
        items = [e for e in ctx.world.in_scene_entities() if (e.state or {}).get("item")]
        return r, [(e.name, e.state["qty"]) for e in items]

    r, items = play(settings, cid, [9, 6], go)  # грязный ликвор, подвох 6 — заражено
    assert r["ok"], r
    assert r["result"]["placed_in_scene"][0]["item"] == "Грязный ликвор" and items == [("Грязный ликвор", 1)]
    catch = r["result"]["catch"]
    assert catch["tone"] == "беда" and catch["hazard"] == "hazard.infected_blood"
    assert any(x.startswith("apply_hazard hazard.infected_blood") for x in catch["next"])


def test_watch_rolls_while_time_passes(client, admin, settings, worlds):  # noqa: F811
    cid, _, _ = echo_party(client, admin)

    async def go(ctx):
        await _at_old_mother(ctx)
        first = await fortune.run_watch(ctx)  # первый раз только засекает время
        await execute(ctx, "advance_time", {"amount": 4, "unit": "hour", "reason": "ждут"})
        second = await fortune.run_watch(ctx)
        return first, second

    # d6 = 1 по расписанию туши (раз в 4 часа, 1 на d6), вид d6 = 2 — встреча, таблица d8 = 3 — грабители
    first, second = play(settings, cid, [1, 2, 3], go)
    assert first == ""
    assert "Случайность" in second and "Грабитель слобод" in second and "spawn_entity" in second


def test_manual_mode_keeps_the_world_quiet(client, admin, settings, worlds):  # noqa: F811
    cid, _, _ = echo_party(client, admin)
    ok(client.patch(f"/api/campaigns/{cid}", json={"random_events": "manual"}, headers=admin))

    async def go(ctx):
        await _at_old_mother(ctx)
        await fortune.run_watch(ctx)
        await execute(ctx, "advance_time", {"amount": 12, "unit": "hour", "reason": "ждут"})
        return await fortune.run_watch(ctx)

    assert play(settings, cid, [1, 1, 1, 1], go) == ""
