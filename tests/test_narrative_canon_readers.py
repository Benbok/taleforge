# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Принятый канон доходит до реальных читателей, раскрытие — до правильных героев (F6: R9, R16)."""

from __future__ import annotations

from sqlalchemy import select

from app.core import adventure
from app.core.narrative.contracts import FactRef, NarrativeSource, SnapshotRef
from app.core.world import get_scene
from app.db.models import Entity, Knowledge, KnownFact, Message, NarrativeFact
from app.tools.narrative.executor import apply_in_context
from tests.game import import_base, ok, party, run
from tests.narrative_helpers import op, policy
from tests.test_adventure import publish_sample
from tests.test_map import _ok
from tests.test_master import DONE, act, admin_g, dice, game_client, llm  # noqa: F401 — фикстуры
from tests.test_narrative_executor import _make_prop
from tests.test_tools import play
from tests.test_ws import connect, next_of


def _npc(settings, cid: str, name: str = "Хромой Вик") -> str:
    async def go(s):
        sc = await get_scene(s, cid)
        e = Entity(
            campaign_id=cid,
            name=name,
            kind="creature",
            template_id="creature.bandit",
            location_id=sc.location_id,
            state={"attitude": "neutral"},
        )
        s.add(e)
        await s.commit()
        return e.id

    return run(settings, go)


def _src(cid: str, source_id: str, scope: str) -> NarrativeSource:
    kind = "turn" if scope == "scene" else "work"
    return NarrativeSource(campaign_id=cid, scope=scope, source_kind=kind, source_id=source_id, stable_part=0)


def _apply(settings, cid: str, hero_id: str, source_id: str, operations, actors=None, scope="scene"):
    async def scenario(ctx):
        if await ctx.session.get(Message, "msg-1") is None:
            ctx.session.add(Message(id="msg-1", campaign_id=cid, seq=9999, kind="speech", content="Игрок действует"))
            await ctx.session.flush()
        extra = {"actors": actors} if actors else {}
        prop = _make_prop(cid, hero_id, ctx.world.revision, _src(cid, source_id, scope), operations=operations, **extra)
        return await apply_in_context(ctx, prop, policy=policy())

    return play(settings, cid, [], scenario)


def _fact_row(settings, cid: str, subject_id: str, key: str):
    async def go(s):
        q = select(NarrativeFact).where(
            NarrativeFact.campaign_id == cid, NarrativeFact.subject_id == subject_id, NarrativeFact.key == key
        )
        return await s.scalar(q)

    return run(settings, go)


def _add_fact(settings, cid: str, subject_id: str, key: str, value: str, *, namespace="campaign", audience=()):
    async def go(s):
        s.add(
            NarrativeFact(
                campaign_id=cid,
                namespace=namespace,
                subject_id=subject_id,
                key=key,
                version=1,
                kind="truth",
                temporal_semantics="current_state",
                freedom="draft",
                value=value,
                audience=list(audience),
                depends_on=[],
                source_refs=[],
                snapshot_ref={"kind": "event", "source_id": "seed", "typed_address": f"{namespace}:{subject_id}:{key}"},
            )
        )
        await s.commit()

    run(settings, go)


def _ref(cid: str, subject_id: str, key: str, *, namespace="campaign", version=1) -> FactRef:
    return FactRef(
        campaign_id=cid,
        namespace=namespace,
        subject_id=subject_id,
        key=key,
        version=version,
        snapshot_ref=SnapshotRef(kind="event", source_id="seed", typed_address=f"{namespace}:{subject_id}:{key}"),
    )


def test_role_and_motive_reach_master_prompt_and_hero_card(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    cid = c["id"]
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    eid = _npc(settings, cid)
    res = _apply(
        settings,
        cid,
        hero["id"],
        "work-role",
        (op("develop_actor_role", entity_id=eid, new_role="Проводник отряда", new_motivation="Тайно ищет брата"),),
        actors=(hero["id"], eid),
        scope="future",
    )
    assert res.status == "applied", res
    motive = _fact_row(settings, cid, eid, "motivation")
    assert motive is not None and motive.audience == [] and motive.freedom == "draft"

    # обычный ход: следующий system prompt мастера читает принятый канон
    llm.replies += [DONE]
    act(game_client, p1, cid, "Расспрашиваю хромого незнакомца")
    systems = [m["content"] for r in llm.requests for m in r["messages"][:1] if m.get("role") == "system"]
    prompt = next(s for s in systems if "Хромой Вик" in s and "Проводник отряда" in s)
    assert "Тайно ищет брата" in prompt

    async def seen(s):  # герой видел незнакомца: карточка ему доступна
        s.add(Knowledge(character_id=hero["id"], entity_id=eid, level=0))
        await s.commit()

    run(settings, seen)

    # карточка героя: публичная роль есть, скрытого мотива нет
    with connect(game_client, p1, cid) as (ws, _):
        ws.send_json({"type": "entity.inspect", "payload": {"entity_id": eid}})
        card = next_of(ws, "entity.card")["payload"]
    assert card.get("role") == "Проводник отряда"
    assert "Тайно ищет брата" not in str(card)


def test_module_override_reaches_book_reader_and_stays_in_its_campaign(client, admin, settings):
    import_base(settings)
    mid = publish_sample(settings)
    c1, _, _ = party(client, admin, module_id=mid, module_hook="board")
    c2 = ok(
        client.post(
            "/api/campaigns",
            json={"name": "Вторая", "master": {"type": "agent", "provider": "claude", "model": "x"}, "module_id": mid},
            headers=admin,
        ),
        201,
    )
    client.portal.call(client.app.state.master.wait_idle, None)  # вступление открыло первую комнату книги
    _add_fact(settings, c1["id"], "creature.skeleton", "role", "Стражи праха Давоса", namespace="module")

    async def block(ctx):
        rec = ctx.world.catalog.find("creature.skeleton", "creature_template")
        assert "Стражи праха Давоса" not in str(rec.data)  # общий каталог пакета не мутирован
        room = await _ok(ctx, "enter_room", {"room": "2"})  # Восточная крипта: два скелета по книге
        return room["book"], adventure.master_block(ctx.world)

    book, text = play(settings, c1["id"], [], block)
    assert "Стражи праха Давоса" in book and "Стражи праха Давоса" in text

    async def other(ctx):
        view = ctx.world.narrative_view
        return [] if view is None else view.facts_for(("creature.skeleton",))

    assert not play(settings, c2["id"], [], other)


def test_reveal_fact_teaches_exact_heroes_and_seals_exact_ref(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin, players=2)
    cid = c["id"]
    eid = _npc(settings, cid)
    _add_fact(settings, cid, eid, "secret_truth", "Вик служит культу пепла")
    _add_fact(settings, cid, eid, "motivation", "Хочет выкупить долг")

    res = _apply(
        settings,
        cid,
        hero["id"],
        "work-reveal",
        (op("reveal_fact", fact_ref=_ref(cid, eid, "secret_truth"), audience=(hero["id"],)),),
        actors=(hero["id"], eid),
    )
    assert res.status == "applied", res

    async def known(s):
        return (await s.scalars(select(KnownFact).where(KnownFact.campaign_id == cid))).all()

    rows = run(settings, known)
    assert [(r.character_id, r.subject_id, r.text) for r in rows] == [(hero["id"], eid, "Вик служит культу пепла")]
    assert _fact_row(settings, cid, eid, "secret_truth").freedom == "committed"
    assert _fact_row(settings, cid, eid, "motivation").freedom == "draft"  # несвязанный мотив не закреплён


def test_reveal_fact_rejects_foreign_audience_and_stale_ref(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    eid = _npc(settings, cid)
    _add_fact(settings, cid, eid, "secret_truth", "Вик служит культу пепла")

    for i, (audience, ref) in enumerate(
        [
            ((eid,), _ref(cid, eid, "secret_truth")),  # NPC — не герой
            ((hero["id"], "ch_foreign"), _ref(cid, eid, "secret_truth")),  # лишний чужой адресат
            ((hero["id"],), _ref(cid, eid, "secret_truth", version=7)),  # неточная версия
            ((hero["id"],), _ref(cid, eid, "secret_truth", namespace="module")),  # другой namespace
        ]
    ):
        res = _apply(
            settings,
            cid,
            hero["id"],
            f"work-bad-{i}",
            (op("reveal_fact", fact_ref=ref, audience=audience),),
            actors=(hero["id"], eid),
        )
        assert res.status == "denied", (i, res)

    async def known(s):
        return (await s.scalars(select(KnownFact).where(KnownFact.campaign_id == cid))).all()

    assert run(settings, known) == []
    assert _fact_row(settings, cid, eid, "secret_truth").freedom == "draft"


def test_revise_after_reveal_is_refused(settings, client, admin):
    """Гонка reveal-vs-revise: пересмотр, подготовленный по прежней версии, не переписывает раскрытую истину."""
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]
    eid = _npc(settings, cid)
    _add_fact(settings, cid, eid, "secret_truth", "Вик служит культу пепла")
    ref = _ref(cid, eid, "secret_truth")

    revealed = _apply(
        settings,
        cid,
        hero["id"],
        "work-reveal-first",
        (op("reveal_fact", fact_ref=ref, audience=(hero["id"],)),),
        actors=(hero["id"], eid),
    )
    assert revealed.status == "applied", revealed
    revised = _apply(
        settings,
        cid,
        hero["id"],
        "work-revise-late",
        (op("revise_draft_fact", target_ref=ref, new_value="Вик невиновен"),),
        actors=(hero["id"], eid),
    )
    assert revised.status in ("denied", "stale", "failed"), revised
    row = _fact_row(settings, cid, eid, "secret_truth")
    assert row.value == "Вик служит культу пепла" and row.freedom == "committed"


def test_turn_reserves_public_claims_before_narration(game_client, admin_g, llm, settings):
    """Публичная роль, принятая в фазе решения, закрепляется до LLM и передаётся рассказчику; мотив — нет."""
    c, (p1,), hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    eid = _npc(settings, cid)
    adapt = {
        "slot_ref": 0,
        "grounds": [
            {
                "kind": "divergence",
                "evidence_refs": [{"campaign_id": cid, "kind": "message", "source_id": "current"}],
                "confidence": "explicit",
            }
        ],
        "summary": "Хромой Вик соглашается вести отряд",
        "operations": [
            {
                "kind": "develop_actor_role",
                "entity_id": eid,
                "new_role": "Проводник отряда",
                "new_motivation": "Тайно ищет брата",
            }
        ],
    }
    llm.replies += [{"tool_calls": [("adapt_story", adapt)]}, DONE, {"text": "Вик кивает и берёт фонарь."}]
    act(game_client, p1, cid, "Предлагаю Вику провести нас")

    role = _fact_row(settings, cid, eid, "role")
    assert role is not None and role.freedom == "committed"
    assert _fact_row(settings, cid, eid, "motivation").freedom == "draft"
    # допустимые утверждения рассказчика: адресованное слушателям, не скрытый мотив из контекста мастера
    narrate = "\n".join(str(m.get("content")) for m in llm.requests[-1]["messages"])
    claims = narrate.split("Перемены сюжета и новые возможности этого хода", 1)[1].split("Сцена после хода", 1)[0]
    assert "Проводник отряда" in claims
    assert "Тайно ищет брата" not in claims


def test_enabling_adaptive_initializes_plan_metadata(client, admin, settings):
    from tests.test_lead import checked, set_plan

    import_base(settings)
    c, _heads, _hero = party(client, admin, narrative_mode="strict")
    cid = c["id"]
    plan = checked()
    set_plan(settings, cid, plan)

    async def plan_facts(s):
        q = select(NarrativeFact).where(NarrativeFact.campaign_id == cid, NarrativeFact.namespace == "plan")
        return (await s.scalars(q)).all()

    assert run(settings, plan_facts) == []
    ok(client.patch(f"/api/campaigns/{cid}", json={"narrative_mode": "adaptive"}, headers=admin))
    rows = run(settings, plan_facts)
    nodes = {n["id"] for a in plan["acts"] for n in a.get("nodes") or []}
    assert nodes and nodes <= {r.subject_id for r in rows if r.key == "situation_premise"}
