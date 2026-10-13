"""Storage and world guard integration tests for narrative persistence."""

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import world_tx
from app.db.models import NarrativeFact
from app.db.narrative import ensure_state, initialize_plan_metadata, load_subject_facts
from app.db.session import make_engine, make_sessionmaker
from tests.game import import_base, party, run


def metadata_guard_scenario(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(maker):
        # 1. Read revision before any changes
        async with maker() as s:
            before = await world_tx.read_revision(s, cid)

        # 2. Write narrative metadata in transaction -> should increment world_revision by 1
        async with maker() as s:
            st = await ensure_state(s, cid)
            st.mode = "adaptive"
            f = NarrativeFact(
                campaign_id=cid,
                namespace="campaign",
                subject_id="npc-1",
                key="role",
                version=1,
                kind="truth",
                temporal_semantics="current_state",
                freedom="draft",
                value="guide",
                audience=["party"],
                depends_on=[],
                source_refs=["evt-1"],
                snapshot_ref={"kind": "event", "source_id": "evt-1", "typed_address": "c:1"},
            )
            s.add(f)
            await s.commit()

        async with maker() as s:
            after = await world_tx.read_revision(s, cid)

        # 3. Rolled back transaction -> revision should not change
        async with maker() as s:
            try:
                async with s.begin():
                    f2 = NarrativeFact(
                        campaign_id=cid,
                        namespace="campaign",
                        subject_id="npc-2",
                        key="role",
                        version=1,
                        kind="truth",
                        temporal_semantics="current_state",
                        freedom="draft",
                        value="traitor",
                        audience=["party"],
                        depends_on=[],
                        source_refs=["evt-2"],
                        snapshot_ref={"kind": "event", "source_id": "evt-2", "typed_address": "c:2"},
                    )
                    s.add(f2)
                    await s.flush()
                    raise RuntimeError("Intentional rollback")
            except RuntimeError:
                pass

        async with maker() as s:
            rolled_back = await world_tx.read_revision(s, cid)

        return before, after, rolled_back

    engine = make_engine(settings.database_url)
    try:
        return asyncio.run(go(make_sessionmaker(engine)))
    finally:
        asyncio.run(engine.dispose())


def test_metadata_write_participates_in_world_guard(settings, client, admin):
    before, after, rolled_back = metadata_guard_scenario(settings, client, admin)
    assert after == before + 1
    assert rolled_back == after


def test_narrative_fact_unique_constraint(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(s):
        f1 = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="motivation",
            version=1,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="revenge",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref={"kind": "event", "source_id": "e1", "typed_address": "a:1"},
        )
        s.add(f1)
        await s.commit()

        f2 = NarrativeFact(
            campaign_id=cid,
            namespace="campaign",
            subject_id="npc-1",
            key="motivation",
            version=2,
            kind="intent",
            temporal_semantics="current_state",
            freedom="draft",
            value="peace",
            audience=["party"],
            depends_on=[],
            source_refs=[],
            snapshot_ref={"kind": "event", "source_id": "e2", "typed_address": "a:1"},
        )
        s.add(f2)
        with pytest.raises(IntegrityError):
            await s.commit()

    run(settings, go)


def test_load_subject_facts_and_initialize_plan_metadata(settings, client, admin):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    sample_plan = {
        "acts": [
            {
                "id": "act_1",
                "nodes": [
                    {"id": "node_1", "summary": "Встреча в таверне"},
                    {"id": "node_2", "summary": "Погоня за некромантом"},
                ],
            }
        ],
        "plot": {
            "secrets": [{"id": "sec_1", "truth": "Некромант невиновен", "revealed": False}],
            "fronts": [{"id": "front_1", "threat": "Нашествие нежити", "stopped": False}],
        },
    }

    async def go(s):
        await initialize_plan_metadata(s, cid, sample_plan, mode="adaptive")
        st = await ensure_state(s, cid)
        assert st.mode == "adaptive"

        facts = await load_subject_facts(s, cid, ("sec_1", "front_1"))
        assert len(facts) >= 1
        secret_fact = next((f for f in facts if f.ref.subject_id == "sec_1"), None)
        assert secret_fact is not None
        assert secret_fact.freedom == "committed"
        assert secret_fact.kind == "truth"

    run(settings, go)
