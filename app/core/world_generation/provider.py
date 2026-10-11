"""Детерминированный provider (§6.3): предложение строго по плану, без LLM. Станет fallback модели (поставка 5)
и разрешает зарезервированный мир, даже если генератор выключат."""

from __future__ import annotations

from app.content.catalog import CatalogView
from app.core.world_generation.contracts import Plan, Proposal, ProposedObject


class DeterministicProvider:
    name = "deterministic"

    def propose(self, plan: Plan, catalog: CatalogView) -> Proposal:
        objects = []
        for slot in plan.slots:
            name = slot.name
            if slot.role == "item":
                rec = catalog.find(slot.template_id or "", "item_template")
                name = rec.name if rec is not None else slot.template_id or "Предмет"
            objects.append(ProposedObject(slot.slot_ref, slot.role, name, slot.description, slot.template_id))
        return Proposal(schema_version=1, objects=tuple(objects))
