
from app.core.layout.intent import LayoutIntent
from app.core.layout.spatial import Mandate, default_spatial, obligations
from app.core.layout.template_catalog import load_catalog
from app.core.layout.template_roles import infer_role
from app.core.layout.template_selection import TemplateContext, select_template


def test_role_inference_is_conservative_for_location_parts():
    assert infer_role('part_warehouse', 'Склад контрабандистов', '') == 'warehouse'
    assert infer_role('part_flooded_pier', 'Затопленный край пирса', 'Глубокая вода') == 'harbor'
    assert infer_role('part_pier', 'Pier', 'Water beside the pier') == 'pier'
    assert infer_role('part_unknown', 'Таинственное место', '') is None


def _greihall_port() -> Mandate:
    from app.core.layout.spatial import SpatialApproach, SpatialPart, SpatialPlan
    return Mandate(
        place='Порт Грейхолла',
        spatial=SpatialPlan(
            environment='mixed', scale='medium',
            parts=[
                SpatialPart(ref='part_pier', name='Причал с лодками', outdoor=True, required=True,
                            purpose='Швартовка рыбацких баркасов.'),
                SpatialPart(ref='part_market', name='Рыбный рынок', outdoor=True,
                            purpose='Прилавки под навесами.'),
                SpatialPart(ref='part_warehouse', name='Склад контрабандистов', outdoor=False,
                            purpose='Запертый склад с бочками.'),
                SpatialPart(ref='part_flooded_pier', name='Затопленный край пирса', outdoor=True,
                            purpose='Глубокая вода у деревянного пирса.'),
                SpatialPart(ref='part_alley', name='Переулок', outdoor=True,
                            purpose='Переулок к складу.'),
                SpatialPart(ref='part_cache', name='Тайник', outdoor=False, secret=True,
                            purpose='Скрытый тайник.'),
            ],
            approaches=[SpatialApproach(name='Дорога к порту', kind='path')],
        ),
    )


def test_generated_port_plan_uses_template_details_and_keeps_extra_parts():
    result = select_template(
        _greihall_port(), TemplateContext(template_id='location.port'), 22325528, load_catalog()
    )
    assert result['outcome'] == 'selected'
    assert result['id'] == 'port_quay_warehouse'
    assert {p['part_ref'] for p in result['intent']['parts']} == {
        'part_pier', 'part_market', 'part_warehouse', 'part_flooded_pier', 'part_alley', 'part_cache'
    }
    pier = next(p for p in result['intent']['parts'] if p['part_ref'] == 'part_pier')
    assert pier['material'] == 'wood'
    assert pier['details']
    market = next(p for p in result['intent']['parts'] if p['part_ref'] == 'part_market')
    assert any(d['detail_ref'] == 'market_stalls' for d in market['details'])
    warehouse = next(p for p in result['intent']['parts'] if p['part_ref'] == 'part_warehouse')
    assert any(d['detail_ref'] == 'crate_stacks' for d in warehouse['details'])


def test_runtime_catalog_contains_twelve_valid_templates():
    catalog = load_catalog()
    assert len(catalog) == 12
    assert len({t.id for t in catalog}) == 12
    assert all(len(t.checksum) == 64 for t in catalog)


def test_selection_preserves_mandate_and_is_repeatable():
    mandate = Mandate(place='Лес', spatial=default_spatial('Лес', ['wild'], template_id='location.forest'))
    context = TemplateContext(template_id='location.forest')
    result = select_template(mandate, context, 42, load_catalog())
    assert result['outcome'] == 'selected'
    assert result == select_template(mandate, context, 42, load_catalog())
    assert not obligations(LayoutIntent.model_validate(result['intent']), mandate)


def test_unknown_type_uses_fallback():
    mandate = Mandate(place='Неизвестное место', spatial=default_spatial('Место'))
    result = select_template(mandate, TemplateContext(template_id='location.unknown'), 1, load_catalog())
    assert result['outcome'] == 'not_selected'


def test_invalid_record_does_not_disable_valid_records(tmp_path):
    (tmp_path/'broken.json').write_text('{', encoding='utf-8')
    assert load_catalog(tmp_path) == ()


def test_secret_template_cannot_add_unrequested_secret():
    mandate = Mandate(place='Кабак', spatial=default_spatial('Кабак', template_id='location.tavern'))
    result = select_template(mandate, TemplateContext(template_id='location.tavern'), 42, load_catalog())
    if result['outcome'] == 'selected':
        assert not any(p['secret'] for p in result['intent']['parts'])


def test_explicit_constraints_and_unknown_refs_are_never_weakened():
    catalog = load_catalog()
    context = TemplateContext(template_id='location.forest')
    for change in ('shape', 'material', 'ref', 'scale'):
        mandate = Mandate(place='Лес', spatial=default_spatial('Лес', ['wild'], template_id='location.forest'))
        if change == 'scale':
            mandate.spatial.scale = 'large'
        else:
            setattr(mandate.spatial.parts[1], change, {'shape':'rect', 'material':'wood', 'ref':'unknown'}[change])
        assert select_template(mandate, context, 42, catalog)['outcome'] == 'not_selected'


def test_all_resources_build_and_roundtrip_on_five_seeds():
    from app.core.layout.contracts import Blueprint
    from app.core.layout.geometry import build_area
    from app.core.layout.provider import DeterministicLayoutProvider
    provider = DeterministicLayoutProvider()
    for template in load_catalog():
        for seed in (1, 7, 42, 99, 123):
            bp = provider.propose(template.intent, seed=seed, root_id='root')
            assert bp == Blueprint.from_json(bp.to_json())
            for area in bp.areas:
                build_area(bp, area)


def test_plot_anchors_and_residents_survive_remapping():
    from app.core.layout.spatial import Holder
    mandate = Mandate(place='Лес', spatial=default_spatial('Лес', template_id='location.forest'),
                     anchors=[Holder(key='clue', name='След')], residents=[Holder(key='npc:guide', name='Проводник')])
    result = select_template(mandate, TemplateContext(template_id='location.forest'), 42, load_catalog())
    assert result['outcome'] == 'selected'
    intent = LayoutIntent.model_validate(result['intent'])
    assert not obligations(intent, mandate)
    assert next(p for p in intent.parts if p.part_ref == intent.entry).anchors == ['npc:guide']
    assert sum('clue' in p.anchors for p in intent.parts) == 1


def test_incompatible_candidates_do_not_consume_provider_limit():
    import hashlib
    template = next(t for t in load_catalog() if t.id == 'forest_clearing_trail')
    candidates = [template.model_copy(update={'id': f'candidate_{i}'}) for i in range(4)]
    candidates.sort(key=lambda t: hashlib.sha256(f'42:{t.id}:{t.version}'.encode()).hexdigest())
    for candidate in candidates[:3]:
        candidate.scale = 'small'
    mandate = Mandate(place='Лес', spatial=default_spatial('Лес', template_id='location.forest'))
    result = select_template(mandate, TemplateContext(template_id='location.forest'), 42, tuple(candidates))
    assert result['outcome'] == 'selected' and result['id'] == candidates[3].id
