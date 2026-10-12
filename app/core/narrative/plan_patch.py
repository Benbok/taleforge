"""Targeted patching of campaign future plan situations and nodes."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.core.narrative.contracts import (
    FactState,
    FutureSituationPatch,
)


class PlanPatchResult(BaseModel):
    """Result of applying a FutureSituationPatch to a campaign plan."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    plan: dict[str, Any]
    changed_refs: tuple[str, ...] = ()
    violations: tuple[str, ...] = ()


CLOSED_STATUSES = frozenset({"done", "skipped", "resolved", "failed", "closed"})


def patch_future_plan(
    plan: dict[str, Any],
    patch: FutureSituationPatch,
    facts: tuple[FactState, ...],
) -> PlanPatchResult:
    """Apply targeted edits to open nodes and acts in campaign plan."""
    new_plan = copy.deepcopy(plan)
    changed_refs: list[str] = []

    # Collect known IDs
    known_locs = {loc.get("id") for loc in new_plan.get("locations", []) if isinstance(loc, dict)}
    known_npcs = {npc.get("id") for npc in new_plan.get("npcs", []) if isinstance(npc, dict)}

    # Map acts by ID
    acts_map = {a.get("id"): a for a in new_plan.get("acts", []) if isinstance(a, dict)}

    for edit in patch.edits:
        act = acts_map.get(edit.act_id)
        if act is None:
            return PlanPatchResult(plan=plan, violations=(f"act_not_found:{edit.act_id}",))

        nodes_list = act.setdefault("nodes", [])

        if edit.kind == "update_open_node":
            if not edit.node_id:
                return PlanPatchResult(plan=plan, violations=("missing_node_id",))
            target_node = next((n for n in nodes_list if n.get("id") == edit.node_id), None)
            if target_node is None:
                return PlanPatchResult(plan=plan, violations=(f"node_not_found:{edit.node_id}",))

            if target_node.get("status") in CLOSED_STATUSES or target_node.get("outcome") is not None:
                return PlanPatchResult(plan=plan, violations=("cannot_modify_closed_node",))

            # Reference validation
            loc_id = edit.fields.get("location_id")
            if loc_id and loc_id not in known_locs and loc_id not in edit.verified_refs:
                return PlanPatchResult(plan=plan, violations=("dangling_reference",))

            npc_ids = edit.fields.get("npc_ids")
            if isinstance(npc_ids, list):
                for nid in npc_ids:
                    if nid not in known_npcs and nid not in edit.verified_refs:
                        return PlanPatchResult(plan=plan, violations=("dangling_reference",))

            # Apply fields
            for k in ("title", "summary", "location_id", "npc_ids", "exit"):
                if k in edit.fields:
                    target_node[k] = edit.fields[k]
            changed_refs.append(f"plan:node:{edit.node_id}")

        elif edit.kind == "add_open_node":
            if not edit.node_id:
                return PlanPatchResult(plan=plan, violations=("missing_node_id",))
            all_existing_node_ids = {
                n.get("id")
                for a in new_plan.get("acts", [])
                if isinstance(a, dict)
                for n in a.get("nodes", [])
                if isinstance(n, dict)
            }
            if edit.node_id in all_existing_node_ids:
                return PlanPatchResult(plan=plan, violations=(f"node_id_exists:{edit.node_id}",))

            loc_id = edit.fields.get("location_id")
            if loc_id and loc_id not in known_locs and loc_id not in edit.verified_refs:
                return PlanPatchResult(plan=plan, violations=("dangling_reference",))

            new_node = {
                "id": edit.node_id,
                "title": edit.fields.get("title", ""),
                "summary": edit.fields.get("summary", ""),
                "status": "sketch",
            }
            if loc_id:
                new_node["location_id"] = loc_id
            if "npc_ids" in edit.fields:
                new_node["npc_ids"] = edit.fields["npc_ids"]
            nodes_list.append(new_node)
            changed_refs.append(f"plan:node:{edit.node_id}")

        elif edit.kind == "bypass_open_node":
            if not edit.node_id:
                return PlanPatchResult(plan=plan, violations=("missing_node_id",))
            target_node = next((n for n in nodes_list if n.get("id") == edit.node_id), None)
            if target_node is None:
                return PlanPatchResult(plan=plan, violations=(f"node_not_found:{edit.node_id}",))

            if target_node.get("status") in CLOSED_STATUSES or target_node.get("outcome") is not None:
                return PlanPatchResult(plan=plan, violations=("cannot_modify_closed_node",))

            target_node["status"] = "skipped"
            if "summary" in edit.fields or "reason" in edit.fields:
                target_node["bypass_reason"] = edit.fields.get("summary") or edit.fields.get("reason")
            changed_refs.append(f"plan:node:{edit.node_id}")

        elif edit.kind == "update_open_act":
            if act.get("status") in ("done", "closed"):
                return PlanPatchResult(plan=plan, violations=("cannot_modify_closed_act",))
            for k in ("title", "goal", "exit"):
                if k in edit.fields:
                    act[k] = edit.fields[k]
            changed_refs.append(f"plan:act:{edit.act_id}")

        elif edit.kind == "retire_pending_act":
            if act.get("status") in ("active", "done", "closed"):
                return PlanPatchResult(plan=plan, violations=("cannot_retire_active_act",))
            act["status"] = "retired"
            changed_refs.append(f"plan:act:{edit.act_id}")

        elif edit.kind == "update_question":
            qid = edit.fields.get("id", edit.node_id or edit.act_id)
            questions = new_plan.setdefault("questions", [])
            q = next((q for q in questions if isinstance(q, dict) and q.get("id") == qid), None)
            if q is None:
                q = {"id": qid, "text": edit.fields.get("text", "")}
                questions.append(q)
            for k in ("text", "status", "outcome"):
                if k in edit.fields:
                    q[k] = edit.fields[k]
            changed_refs.append(f"plan:question:{qid}")

    return PlanPatchResult(plan=new_plan, changed_refs=tuple(changed_refs), violations=())
