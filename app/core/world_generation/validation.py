"""Сверка предложения с планом (§4.3): только выданные слоты, роли и шаблоны; механические слоты обязательны,
обстановку можно опустить. Реальные id, состояние, числа, количество и геометрию предложение задать не может —
в контракте для них нет полей."""

from __future__ import annotations

from app.core.world_generation.contracts import Blocked, Plan, Proposal

MAX_NAME = 128
MAX_DESCRIPTION = 500


def validate(plan: Plan, proposal: Proposal) -> None:
    if proposal.schema_version != 1:
        raise Blocked("invalid_proposal", "неизвестная версия предложения")
    if len(proposal.objects) > len(plan.slots):
        raise Blocked("invalid_proposal", "объектов больше, чем слотов плана")
    seen: set[str] = set()
    for obj in proposal.objects:
        slot = plan.slot(obj.slot_ref)
        if slot is None or obj.slot_ref in seen:
            raise Blocked("invalid_proposal", f"слот {obj.slot_ref} не выдан планом или повторён")
        seen.add(obj.slot_ref)
        if obj.role != slot.role or obj.template_id != slot.template_id:
            raise Blocked("invalid_proposal", f"слот {obj.slot_ref}: роль или шаблон не совпадают с планом")
        if not obj.name or len(obj.name) > MAX_NAME or len(obj.description) > MAX_DESCRIPTION:
            raise Blocked("invalid_proposal", f"слот {obj.slot_ref}: имя или описание вне лимитов")
    missing = [s.slot_ref for s in plan.slots if s.role != "prop" and s.slot_ref not in seen]
    if missing:
        raise Blocked("invalid_proposal", f"не заполнены механические слоты: {', '.join(missing)}")
