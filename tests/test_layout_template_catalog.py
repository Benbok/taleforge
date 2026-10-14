
from app.core.layout.intent import LayoutIntent
from app.core.layout.spatial import Mandate, default_spatial, obligations
from app.core.layout.template_catalog import load_catalog
from app.core.layout.template_selection import TemplateContext, select_template


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
