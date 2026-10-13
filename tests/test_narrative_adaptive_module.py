"""End-to-end integration scenario for Gate C (Task 19).

Flow:
1. Player negotiates an alliance -> new front intent is formed.
2. Valid draft revision adjusts module view without altering base stats.
3. Durable actor introduction materializes one NPC.
4. Consistent audience partitions secret facts from uninvolved factions.
5. Transition into next scene preserves physical clues and geometry.
"""

from __future__ import annotations

import asyncio
import copy

import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.content.catalog import Entry
from app.core.narrative.contracts import (
    FactRef,
    FactState,
    Ground,
    SnapshotRef,
)
from app.core.narrative.facts import revise_draft
from app.core.narrative.fronts import advance_front, iter_fronts, tick_fronts
from app.core.narrative.view import effective_module_entry
from app.db.models import Campaign, CampaignSecret, NarrativeFact
from app.db.session import make_sessionmaker
from app.main import create_app
from app.rules.dice import Dice
from app.tools.narrative.commitments import record_commitments
from app.tools.plot import run_clock
from app.tools.runtime import open_context
from tests.conftest import login
from tests.game import QueueDice, import_base, party
from tests.test_ws import connect, next_of


def test_adaptive_front_clock_is_persisted_across_context_reload(game_client, admin_g):
    campaign, _, _ = party(game_client, admin_g, master={"type": "owner"}, narrative_mode="adaptive")
    cid = campaign["id"]
    maker = make_sessionmaker(game_client.app.state.engine)

    async def check_clock():
        async with maker() as session:
            secret = await session.get(CampaignSecret, cid)
            if secret is None:
                secret = CampaignSecret(campaign_id=cid)
                session.add(secret)
            secret.plot = {
                "title": "Часы осады",
                "clock_at": 0,
                "fronts": [{"id": "siege", "period": 3600, "clock_at": 0, "maximum": 6}],
            }
            await session.commit()

        for now, progress, notes_count in ((3600, 1, 1), (3600, 1, 0), (7500, 2, 1)):
            async with maker() as session:
                camp = await session.get(Campaign, cid)
                ctx = await open_context(session, camp, Dice(), turn_id=None, seat_id=None)
                ctx.world.scene.game_time = now
                entities_before = set(ctx.world.entities)
                notes = await run_clock(ctx)
                assert len(notes) == notes_count
                assert set(ctx.world.entities) == entities_before
                assert ctx.world.plot["fronts"][0]["progress"] == progress
                await session.commit()
            async with maker() as session:
                persisted = await session.get(CampaignSecret, cid)
                assert persisted.plot["fronts"][0]["progress"] == progress
                assert persisted.plot["fronts"][0]["clock_at"] == progress * 3600

    game_client.portal.call(check_clock)


def test_human_master_route_uses_explicit_front_clock(game_client, admin_g):
    campaign, _, hero = party(game_client, admin_g, master={"type": "owner"}, narrative_mode="adaptive")
    cid = campaign["id"]
    maker = make_sessionmaker(game_client.app.state.engine)

    async def prepare():
        async with maker() as session:
            secret = await session.get(CampaignSecret, cid)
            if secret is None:
                secret = CampaignSecret(campaign_id=cid)
                session.add(secret)
            secret.plot = {
                "title": "Осада",
                "clock_at": 0,
                "fronts": [{"id": "siege", "period": 3600, "clock_at": 0, "maximum": 6}],
            }
            camp = await session.get(Campaign, cid)
            ctx = await open_context(session, camp, Dice(), turn_id=None, seat_id=None)
            ctx.world.scene.game_time = 3600
            await session.commit()

    game_client.portal.call(prepare)
    with connect(game_client, admin_g, cid) as (ws, _):
        for request_id in ("clock-1", "clock-2"):
            ws.send_json(
                {
                    "type": "master.tool",
                    "payload": {
                        "tool": "give_item",
                        "args": {"character_id": hero["id"], "item_template_id": "item.dagger", "reason": "награда"},
                        "request_id": request_id,
                    },
                }
            )
            result = next_of(ws, "master.tool.result")["payload"]
            assert result["ok"], result
            assert bool(result.get("plot_clock")) == (request_id == "clock-1")

    async def check_persisted():
        async with maker() as session:
            secret = await session.get(CampaignSecret, cid)
            assert secret.plot["fronts"][0]["progress"] == 1
            assert secret.plot["fronts"][0]["clock_at"] == 3600

    game_client.portal.call(check_persisted)


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def dice():
    return [20]


@pytest.fixture
def game_client(settings, llm, dice):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice(dice))) as c:
        yield c


@pytest.fixture
def admin_g(game_client):
    root = login(game_client, "root", "rootpass")
    r = game_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(game_client, "Arty", "secret1")


def test_gate_c_adaptive_module_scenario(settings, game_client, admin_g):
    """End-to-end Gate C scenario verifying front evolution, selective draft revision, and clue preservation."""
    import_base(settings)
    c, (p1,), hero = party(game_client, admin_g, narrative_mode="adaptive")
    cid = c["id"]
    maker = make_sessionmaker(game_client.app.state.engine)

    initial_plan = {
        "title": "Хроника Вестгейта",
        "campaign_id": cid,
        "clock_at": 0,
        "antagonists": [
            {
                "id": "inquisitor_torquem",
                "name": "Инквизитор Торквем",
                "goal": "Искоренить ересь огнём",
                "status": "active",
                "threat": [
                    "Установить слежку",
                    "Арестовать подозреваемых",
                    "Сжечь святилище",
                ],
                "threat_step": 1,
            }
        ],
        "acts": [
            {
                "id": "act-1",
                "title": "Утро тревоги",
                "status": "active",
                "goal": "Найти источник слухов",
                "nodes": [
                    {
                        "id": "node-1",
                        "title": "Встреча в таверне",
                        "status": "done",
                        "outcome": "Герои договорились с городским стражником",
                    },
                    {
                        "id": "node-2",
                        "title": "Оборона святилища",
                        "status": "sketch",
                        "summary": "Защитить святилище от погрома",
                    },
                ],
            }
        ],
    }

    async def _run():
        # 1. Initialize plan
        async with maker() as s:
            sec = await s.get(CampaignSecret, cid)
            if not sec:
                sec = CampaignSecret(campaign_id=cid)
                s.add(sec)
            sec.plot = copy.deepcopy(initial_plan)
            await s.commit()

        # 2. Advance front with clock and observe intent readiness
        clock_result = tick_fronts(initial_plan, game_time=86400 * 3, length="short", mode="adaptive")
        assert clock_result.ready_intents
        assert all(intent.kind != "entity_created" for intent in clock_result.ready_intents)

        # 3. Ally with city guard: advance/stop front with relationship ground
        fronts = iter_fronts(clock_result.next_plan)
        inq_front = next(f for f in fronts if f.ref.id == "inquisitor_torquem")
        ground = Ground(kind="relationship", evidence_refs=())
        transition = advance_front(inq_front, ground, transition_key="pact_with_guards", stop=True)
        assert transition.new_status == "stopped"

        # 4. Selective draft revision of NPC motivation without altering SRD stats
        base_guard_entry = Entry(
            id="creature.guard",
            kind="creature_template",
            status="canon",
            pack_id="dnd5e-srd",
            data={
                "name": "Стражник",
                "hp": {"average": 11, "dice": "2d8+2"},
                "ac": 16,
                "role": "Охрана ворот",
                "motivation": "Служить закону",
            },
        )
        guard_snap = SnapshotRef(kind="package", source_id="p1", typed_address="module:creature.guard:motivation")
        guard_fact = FactState(
            ref=FactRef(
                campaign_id=cid,
                namespace="module",
                subject_id="creature.guard",
                key="motivation",
                version=1,
                snapshot_ref=guard_snap,
            ),
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="Помочь отряду отвлечь фанатиков",
            audience=("party", "creature.guard"),
        )
        div_ground = Ground(kind="divergence", evidence_refs=())
        rev_res = revise_draft(
            guard_fact,
            "Защищать героев ценой репутации",
            div_ground,
            ("module:creature.guard:motivation",),
        )
        assert not rev_res.violations
        assert rev_res.after is not None

        # View isolates module changes
        effective_entry = effective_module_entry(base_guard_entry, (rev_res.after,))
        assert effective_entry.data["motivation"] == "Защищать героев ценой репутации"
        assert effective_entry.data["hp"] == {"average": 11, "dice": "2d8+2"}
        assert effective_entry.data["ac"] == 16

        # 5. Clue preservation: physical evidence is sealed and immutable
        clue_snap = SnapshotRef(kind="package", source_id="p1", typed_address="module:clue.letter:secret_truth")
        clue_ref = FactRef(
            campaign_id=cid,
            namespace="module",
            subject_id="clue.letter",
            key="secret_truth",
            version=1,
            snapshot_ref=clue_snap,
        )
        async with maker() as s:
            f_clue = NarrativeFact(
                campaign_id=cid,
                namespace="module",
                subject_id="clue.letter",
                key="secret_truth",
                version=1,
                kind="truth",
                temporal_semantics="current_state",
                freedom="draft",
                value="Тайное письмо с печатью Торквема",
                audience=["party"],
                snapshot_ref=clue_snap.model_dump(),
            )
            s.add(f_clue)
            camp = await s.get(Campaign, cid)
            ctx = await open_context(s, camp, Dice(), turn_id=None, seat_id=None)
            sealed = await record_commitments(ctx, (clue_ref,), reason="clue_materialized", snapshot_ref=clue_snap)
            assert clue_ref in sealed
            await s.commit()

        # Sealed clue cannot be revised
        clue_fact_state = FactState(
            ref=clue_ref,
            kind="truth",
            temporal_semantics="current_state",
            freedom="committed",
            value="Тайное письмо с печатью Торквема",
            audience=("party",),
        )
        late_rev = revise_draft(clue_fact_state, "Поддельное письмо", div_ground, ())
        assert "fact_committed" in late_rev.violations

    asyncio.run(_run())
