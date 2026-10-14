"""Small deterministic decorations for authored parts absent from a template."""
from __future__ import annotations

from app.core.layout.intent import LayoutIntent
from app.core.layout.spatial import Mandate
from app.core.layout.template_roles import infer_role

_DETAILS = {
    'market': ('market_stalls', 'Рыночные прилавки', 'furniture', False),
    'warehouse': ('warehouse_crates', 'Штабели ящиков', 'cover', True),
    'cache': ('cache_marker', 'Спрятанный тайник', 'object', True),
    'alley': ('alley_lantern', 'Портовый фонарь', 'light', False),
}


def enrich_intent(intent: LayoutIntent, mandate: Mandate) -> LayoutIntent:
    parts = intent.model_dump(mode='json')
    for part in parts['parts']:
        requested = next((p for p in mandate.spatial.parts if p.ref == part['part_ref']), None)
        if requested is None:
            continue
        role = infer_role(requested.ref, requested.name, requested.purpose)
        detail = _DETAILS.get(role)
        if detail is not None:
            detail_ref, name, kind, hidden = detail
            if any(d['detail_ref'] == detail_ref for d in part['details']):
                continue
            part['details'].append({
                'detail_ref': detail_ref, 'name': name, 'kind': kind,
                'cells': [[1, 1, 2, 1]], 'solid': False, 'hidden': hidden,
            })
        elif role == 'harbor' and requested.material is None:
            part['material'] = 'water'
    return LayoutIntent.model_validate(parts)
