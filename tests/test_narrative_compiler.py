"""Tests for narrative operations compiler and execution tools (Task 8)."""

from __future__ import annotations

from app.core.narrative.contracts import (
    FactRef,
    FrontRef,
    FuturePlanEdit,
    FutureSituationPatch,
    SnapshotRef,
)
from app.tools.narrative.compiler import compile_operations
from app.tools.operation_group import run_operation_group
from tests.game import import_base, party
from tests.narrative_helpers import (
    fact,
    op,
    proposal,
    snapshot,
    thread,
)
from tests.test_tools import play


def test_compile_add_campaign_fact():
    snap = snapshot()
    f = fact()
    prop = proposal(snap, operations=(op("add_campaign_fact", fact=f),))
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    call = calls[0]
    assert call.tool == "apply_narrative_fact"
    assert call.args["subject_id"] == f.ref.subject_id
    assert call.args["key"] == f.ref.key
    assert call.args["value"] == f.value


def test_compile_develop_actor_role():
    snap = snapshot()
    prop = proposal(
        snap,
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="guide"),),
    )
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    call = calls[0]
    assert call.tool == "apply_narrative_fact"
    assert call.args["subject_id"] == "npc-1"
    assert call.args["key"] == "role"
    assert call.args["value"] == "guide"


def test_compile_upsert_and_transition_thread():
    snap = snapshot()
    t = thread(id="th-test", status="offered")
    prop = proposal(
        snap,
        operations=(
            op("upsert_thread", thread=t),
            op("transition_thread", thread_id="th-test", target_status="active"),
        ),
    )
    calls = compile_operations(snap, prop)
    assert len(calls) == 2
    assert calls[0].tool == "apply_narrative_thread"
    assert calls[0].args["thread"]["id"] == "th-test"
    assert calls[1].tool == "apply_narrative_thread"
    assert calls[1].args["thread_id"] == "th-test"
    assert calls[1].args["target_status"] == "active"


def test_compile_revise_future_situation():
    snap = snapshot()
    patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="update_open_node",
                act_id="act1",
                node_id="n1",
                fields={"summary": "Новая ситуация"},
            ),
        )
    )
    prop = proposal(snap, operations=(op("revise_future_situation", patch=patch),))
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    assert calls[0].tool == "apply_future_situation"
    assert "patch" in calls[0].args


def test_compile_change_front_intent():
    snap = snapshot()
    front = FrontRef(campaign_id="camp-1", source_kind="antagonist", source_id="villain")
    prop = proposal(
        snap,
        operations=(op("change_front_intent", front_ref=front, new_intent="Отступить"),),
    )
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    assert calls[0].tool == "apply_existing_front_intent"
    assert calls[0].args["new_intent"] == "Отступить"


def test_compile_reveal_fact():
    snap = snapshot()
    f_ref = FactRef(
        campaign_id="camp-1",
        namespace="campaign",
        subject_id="npc-1",
        key="motivation",
        version=1,
        snapshot_ref=SnapshotRef(kind="event", source_id="e1", typed_address="c:1"),
    )
    prop = proposal(
        snap,
        operations=(op("reveal_fact", fact_ref=f_ref, audience=("hero-1",)),),
    )
    calls = compile_operations(snap, prop)
    assert len(calls) == 1
    assert calls[0].tool == "learn_fact"


def test_compiled_calls_execute_successfully(settings, client, admin):
    import_base(settings)
    c, _heads, hero = party(client, admin)
    cid = c["id"]

    snap = snapshot(source=proposal(snapshot()).source.model_copy(update={"campaign_id": cid}))
    t = thread(id="th-caravan", status="offered")
    prop = proposal(
        snap,
        operations=(
            op("develop_actor_role", entity_id=hero["id"], new_role="scout"),
            op("upsert_thread", thread=t),
        ),
    )
    calls = compile_operations(snap, prop)

    async def scenario(ctx):
        from app.tools.registry import issue_internal_grant

        grant = issue_internal_grant(cid, calls)
        res = await run_operation_group(ctx, calls, grant=grant)
        assert res.ok
        assert len(res.event_ids) >= 2

    play(settings, cid, [], scenario)
