"""Tests for targeted patching of open future campaign situations (Task 8)."""

from __future__ import annotations

from app.core.narrative.contracts import (
    FuturePlanEdit,
    FutureSituationPatch,
)
from app.core.narrative.plan_patch import patch_future_plan
from tests.narrative_helpers import fact
from tests.test_plan import good_plan


def partially_completed_plan_fixture():
    plan = good_plan()
    # Mark Act 0 partially completed: node 0 done, node 1 open
    plan["acts"][0]["status"] = "active"
    plan["acts"][0]["nodes"][0]["status"] = "done"
    plan["acts"][0]["nodes"][0]["outcome"] = "Корабль спасён"
    plan["acts"][0]["nodes"][1]["status"] = "open"

    patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="update_open_node",
                act_id=plan["acts"][0]["id"],
                node_id=plan["acts"][0]["nodes"][1]["id"],
                fields={"summary": "Защита кладбища"},
            ),
        )
    )
    facts = (fact(),)
    return plan, patch, facts


def test_open_node_changes_without_rewriting_closed_node():
    plan, patch, facts = partially_completed_plan_fixture()
    result = patch_future_plan(plan, patch, facts)
    assert result.violations == ()
    assert result.plan["acts"][0]["nodes"][0] == plan["acts"][0]["nodes"][0]
    assert result.plan["acts"][0]["nodes"][1]["summary"] == "Защита кладбища"
    assert f"plan:node:{plan['acts'][0]['nodes'][1]['id']}" in result.changed_refs


def test_cannot_modify_closed_node():
    plan, _patch, facts = partially_completed_plan_fixture()
    bad_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="update_open_node",
                act_id=plan["acts"][0]["id"],
                node_id=plan["acts"][0]["nodes"][0]["id"],
                fields={"summary": "Новое начало"},
            ),
        )
    )
    result = patch_future_plan(plan, bad_patch, facts)
    assert "cannot_modify_closed_node" in result.violations


def test_dangling_reference_rejected():
    plan, _patch, facts = partially_completed_plan_fixture()
    bad_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="update_open_node",
                act_id=plan["acts"][0]["id"],
                node_id=plan["acts"][0]["nodes"][1]["id"],
                fields={"location_id": "loc_non_existent_void"},
            ),
        )
    )
    result = patch_future_plan(plan, bad_patch, facts)
    assert "dangling_reference" in result.violations


def test_bypass_open_node_marks_skipped_and_preserves_id():
    plan, _patch, facts = partially_completed_plan_fixture()
    node_to_bypass = plan["acts"][0]["nodes"][1]["id"]
    bypass_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="bypass_open_node",
                act_id=plan["acts"][0]["id"],
                node_id=node_to_bypass,
                fields={"summary": "Герои обошли таверну стороной"},
            ),
        )
    )
    result = patch_future_plan(plan, bypass_patch, facts)
    assert result.violations == ()
    bypassed_node = result.plan["acts"][0]["nodes"][1]
    assert bypassed_node["id"] == node_to_bypass
    assert bypassed_node["status"] == "skipped"


def test_add_open_node_appends_to_act():
    plan, _patch, facts = partially_completed_plan_fixture()
    add_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="add_open_node",
                act_id=plan["acts"][0]["id"],
                node_id="n_graveyard",
                fields={
                    "title": "Ночное кладбище",
                    "summary": "Склеп осквернён культистами",
                    "location_id": "loc_port",
                },
            ),
        )
    )
    result = patch_future_plan(plan, add_patch, facts)
    assert result.violations == ()
    node_ids = [n["id"] for n in result.plan["acts"][0]["nodes"]]
    assert "n_graveyard" in node_ids


def test_update_open_act_changes_goal_and_exit():
    plan, _patch, facts = partially_completed_plan_fixture()
    act_id = plan["acts"][0]["id"]
    act_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="update_open_act",
                act_id=act_id,
                fields={"goal": "Найти портал", "exit": "Портал закрыт"},
            ),
        )
    )
    result = patch_future_plan(plan, act_patch, facts)
    assert result.violations == ()
    assert result.plan["acts"][0]["goal"] == "Найти портал"
    assert result.plan["acts"][0]["exit"] == "Портал закрыт"


def test_cannot_retire_active_act():
    plan, _patch, facts = partially_completed_plan_fixture()
    act_id = plan["acts"][0]["id"]  # this act is active
    retire_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="retire_pending_act",
                act_id=act_id,
            ),
        )
    )
    result = patch_future_plan(plan, retire_patch, facts)
    assert "cannot_retire_active_act" in result.violations


def test_retire_pending_act_succeeds():
    plan, _patch, facts = partially_completed_plan_fixture()
    act2_id = plan["acts"][1]["id"]  # pending act
    plan["acts"][1]["status"] = "pending"
    retire_patch = FutureSituationPatch(
        edits=(
            FuturePlanEdit(
                kind="retire_pending_act",
                act_id=act2_id,
            ),
        )
    )
    result = patch_future_plan(plan, retire_patch, facts)
    assert result.violations == ()
    assert result.plan["acts"][1]["status"] == "retired"
