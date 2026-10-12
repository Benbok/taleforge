"""Unified read-view for campaign narrative and plan overlays."""

from __future__ import annotations

import copy
from typing import Any

from app.content.catalog import Entry
from app.core.narrative.contracts import (
    FactRef,
    FactState,
)


class CampaignNarrativeView:
    """Unified read-view over campaign plan, module overlays, and campaign facts."""

    def __init__(
        self,
        plan: dict[str, Any],
        facts: tuple[FactState, ...],
        content_chain: tuple[Any, ...],
    ) -> None:
        self._plan = plan
        self._facts_by_key: dict[tuple[str, str, str], FactState] = {
            (f.ref.namespace, f.ref.subject_id, f.ref.key): f for f in facts
        }
        self._content_chain = content_chain

    def plan_data(self) -> dict[str, Any]:
        """Return raw plan dictionary."""
        return self._plan

    def permitted_subjects(self) -> tuple[str, ...]:
        """Return all valid subject IDs in plan and facts."""
        subjects: set[str] = set()

        # From antagonists
        for ant in self._plan.get("antagonists", []):
            if isinstance(ant, dict) and "id" in ant:
                subjects.add(ant["id"])

        # From acts and nodes
        for act in self._plan.get("acts", []):
            if isinstance(act, dict):
                if "id" in act:
                    subjects.add(act["id"])
                for node in act.get("nodes", []):
                    if isinstance(node, dict) and "id" in node:
                        subjects.add(node["id"])

        # From npcs
        for npc in self._plan.get("npcs", []):
            if isinstance(npc, dict) and "id" in npc:
                subjects.add(npc["id"])

        # From locations
        for loc in self._plan.get("locations", []):
            if isinstance(loc, dict) and "id" in loc:
                subjects.add(loc["id"])

        # From secrets
        plot = self._plan.get("plot") or {}
        secrets = plot.get("secrets") or self._plan.get("secrets") or []
        for sec in secrets:
            if isinstance(sec, dict) and "id" in sec:
                subjects.add(sec["id"])

        # From narrative facts
        for f in self._facts_by_key.values():
            subjects.add(f.ref.subject_id)

        return tuple(sorted(subjects))

    def _extract_plan_value(self, subject_id: str, key: str) -> str | None:
        """Extract live value for a plan property."""
        for ant in self._plan.get("antagonists", []):
            if isinstance(ant, dict) and ant.get("id") == subject_id:
                if key in ("motivation", "goal"):
                    return ant.get("goal") or ant.get("want")
                if key == "role":
                    return ant.get("role") or ant.get("name")

        for act in self._plan.get("acts", []):
            if not isinstance(act, dict):
                continue
            if act.get("id") == subject_id:
                if key in ("motivation", "goal"):
                    return act.get("goal")
                if key in ("situation_premise", "role"):
                    return act.get("title")
            for node in act.get("nodes", []):
                if isinstance(node, dict) and node.get("id") == subject_id:
                    if key in ("situation_premise", "goal", "motivation"):
                        return node.get("summary") or node.get("goal")

        for npc in self._plan.get("npcs", []):
            if isinstance(npc, dict) and npc.get("id") == subject_id:
                if key in ("motivation", "goal"):
                    return npc.get("want") or npc.get("goal")
                if key == "role":
                    return npc.get("role")

        plot = self._plan.get("plot") or {}
        secrets = plot.get("secrets") or self._plan.get("secrets") or []
        for sec in secrets:
            if isinstance(sec, dict) and sec.get("id") == subject_id:
                if key == "secret_truth":
                    return sec.get("truth") or sec.get("title")

        return None

    def resolve(self, ref: FactRef) -> FactState:
        """Resolve fact state using live plan priority for namespace=plan."""
        if ref.namespace == "plan":
            live_val = self._extract_plan_value(ref.subject_id, ref.key)
            meta = self._facts_by_key.get((ref.namespace, ref.subject_id, ref.key))
            if meta is not None:
                return FactState(
                    ref=meta.ref,
                    kind=meta.kind,
                    temporal_semantics=meta.temporal_semantics,
                    freedom=meta.freedom,
                    value=live_val if live_val is not None else meta.value,
                    audience=meta.audience,
                    depends_on=meta.depends_on,
                )
            return FactState(
                ref=ref,
                kind="intent",
                temporal_semantics="current_state",
                freedom="draft",
                value=live_val or "",
                audience=("party",),
                depends_on=(),
            )

        meta = self._facts_by_key.get((ref.namespace, ref.subject_id, ref.key))
        if meta is not None:
            return meta

        raise KeyError(f"FactRef not found in narrative view: {ref}")


def compose_view(
    plan: dict[str, Any],
    facts: tuple[FactState, ...],
    content_chain: tuple[Any, ...],
) -> CampaignNarrativeView:
    """Pure constructor building unified CampaignNarrativeView."""
    return CampaignNarrativeView(plan, facts, content_chain)


def effective_module_entry(
    base_entry: Entry,
    view: CampaignNarrativeView | None,
) -> Entry:
    """Return an immutable Entry representation with narrative fact overrides applied without mutating base."""
    if view is None:
        return base_entry

    data = copy.deepcopy(base_entry.data)
    overridden = False

    field_map: dict[str, list[str]] = {
        "motivation": ["want", "motivation", "goal"],
        "role": ["role"],
        "relationship": ["relationship"],
        "secret_truth": ["truth", "secret_truth"],
        "situation_premise": ["premise", "situation_premise"],
    }

    for fact_key, target_fields in field_map.items():
        for ns in ("module", "campaign", "plan"):
            fact_state = view._facts_by_key.get((ns, base_entry.id, fact_key))
            if fact_state is not None:
                val = fact_state.value
                matched = False
                for fld in target_fields:
                    if fld in data:
                        data[fld] = val
                        matched = True
                        overridden = True
                if not matched:
                    data[target_fields[0]] = val
                    overridden = True
                break

    if not overridden:
        return base_entry

    return Entry(
        id=base_entry.id,
        kind=base_entry.kind,
        status=base_entry.status,
        pack_id=base_entry.pack_id,
        data=data,
    )
