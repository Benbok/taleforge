"""Pure conservative matching: never weaken a campaign's spatial mandate."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from pydantic import ValidationError

from app.core.layout.contracts import LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Mandate, intent_candidates, obligations
from app.core.layout.template_catalog import LayoutTemplate


@dataclass(frozen=True)
class TemplateContext:
    template_id: str = ''
    tags: tuple[str, ...] = ()


def adapt_template(template: LayoutTemplate, mandate: Mandate) -> tuple[LayoutIntent, dict[str, str]]:
    if template.environment != mandate.spatial.environment or template.scale != mandate.spatial.scale:
        raise ValueError('environment_or_scale')
    source = {p.part_ref: p for p in template.intent.parts}
    bindings = {}
    for part in mandate.spatial.parts:
        target = template.part_bindings.get(part.ref, part.ref if part.ref in source else None)
        if target is None or target in bindings:
            raise ValueError('ambiguous_or_unknown_part')
        bindings[target] = part.ref
    if bindings.get(template.intent.entry) != mandate.spatial.parts[0].ref:
        raise ValueError('entry_mismatch')
    for p in template.intent.parts:
        if p.secret and p.part_ref not in bindings:
            raise ValueError('unrequested_secret')
    used = set(bindings.values())
    for p in template.intent.parts:
        if p.part_ref not in bindings:
            ref = p.part_ref
            while ref in used:
                ref = 'extra_' + hashlib.sha256(ref.encode()).hexdigest()[:12]
            bindings[p.part_ref] = ref
            used.add(ref)
    data = template.intent.model_dump(mode='json')
    requested = {p.ref: p for p in mandate.spatial.parts}
    base = intent_candidates(mandate)[0]
    anchors = {p.part_ref: p.anchors for p in base.parts}
    for p in data['parts']:
        original = p['part_ref']
        p['part_ref'] = bindings[original]
        if p['connects_to'] is not None:
            p['connects_to'] = bindings[p['connects_to']]
        sp = requested.get(p['part_ref'])
        if sp:
            if (p['environment'] != ('outdoor' if sp.outdoor else 'indoor') or p['secret'] != sp.secret
                or (sp.below and p['level'] >= 0) or (not sp.below and p['level'] < 0)
                or (sp.shape is not None and p['shape'] != sp.shape)
                or (sp.material is not None and p['material'] != sp.material)):
                raise ValueError('part_constraints')
            p.update(name=sp.name, public_name=sp.name, description=sp.purpose, required=sp.required)
        p['anchors'] = list(anchors.get(p['part_ref'], []))
    data['entry'] = bindings[data['entry']]
    if len(data['approaches']) != len(mandate.spatial.approaches):
        raise ValueError('approach_count')
    for approach, sp in zip(data['approaches'], mandate.spatial.approaches, strict=True):
        if approach['part_ref'] != template.intent.entry:
            raise ValueError('approach_entry')
        approach['part_ref'] = data['entry']
        approach['public_name'] = sp.name
        if mandate.spatial.parts[0].outdoor:
            if sp.kind not in ('road', 'path', 'gap', 'gate'):
                raise ValueError('approach_kind')
        elif approach['kind'] != sp.kind:
            raise ValueError('approach_kind')
        if sp.kind in ('road', 'path') and approach.get('band'):
            band = next(b for b in data['bands'] if b['band_ref'] == approach['band'])
            if band['kind'] != sp.kind:
                raise ValueError('approach_band')
    intent = LayoutIntent.model_validate(data)
    if obligations(intent, mandate):
        raise ValueError('mandate_obligations')
    return intent, bindings


def select_template(mandate: Mandate, context: TemplateContext, seed: int,
                    catalog: tuple[LayoutTemplate, ...]) -> dict:
    candidates = [t for t in catalog if context.template_id in t.template_ids
                  or (t.tags and set(t.tags) & set(context.tags))]
    reason = 'no_candidate'
    compatible = []
    for template in candidates:
        try:
            intent, bindings = adapt_template(template, mandate)
        except (ValueError, ValidationError) as error:
            reason = str(error)[:200]
            continue
        compatible.append((template, intent, bindings))
    compatible.sort(key=lambda entry: hashlib.sha256(
        f'{seed}:{entry[0].id}:{entry[0].version}'.encode()).hexdigest())
    for template, intent, bindings in compatible[:3]:
        try:
            DeterministicLayoutProvider().propose(intent, seed=seed, root_id='root')
        except (ValueError, ValidationError, LayoutError) as error:
            reason = str(error)[:200]
            continue
        return {'schema_version': 1, 'outcome': 'selected', 'id': template.id,
                'version': template.version, 'checksum': template.checksum,
                'bindings': bindings, 'intent': intent.model_dump(mode='json')}
    return {'schema_version': 1, 'outcome': 'not_selected', 'reason': reason}
