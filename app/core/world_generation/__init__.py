"""Подготовка исследуемых сцен (спецификация 2026-10-11, §3; docs/world-objects-delivery3.md).

- ``contracts`` — план, слоты и предложение; без ORM и LLM;
- ``profiles`` — профили ``scene_profile`` из каталога кампании и ``minimal``;
- ``policy`` — детерминированный резерв, дерево бюджета и seed потомков;
- ``provider`` — детерминированное предложение по плану (fallback для будущей модели);
- ``validation`` — сверка предложения с планом;
- ``storage`` — резерв, lease/CAS, атомарная материализация в короткой ``world_write``;
- ``service`` — оркестратор: ``settle`` для хода, ``run_due`` для восстановителя.
"""

from app.core.world_generation.contracts import POLICY_VERSION, PRNG, Plan, Proposal, Slot
from app.core.world_generation.profiles import MINIMAL, ProfileError, SceneProfile, eligible, load_profile

__all__ = [
    "MINIMAL",
    "POLICY_VERSION",
    "PRNG",
    "Plan",
    "ProfileError",
    "Proposal",
    "SceneProfile",
    "Slot",
    "eligible",
    "load_profile",
]
