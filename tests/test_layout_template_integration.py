import pytest

from app.agents.llm import ScriptedLLM
from app.core.layout import store
from app.core.layout.spatial import Mandate, default_spatial
from app.core.layout.template_selection import TemplateContext
from app.core.world_generation import storage
from app.db.models import Campaign, WorldGenerationState
from tests.game import run
from tests.test_layout_model_phase import _flags, _orch
from tests.test_layout_preparation import _setup
from tests.test_map import _ok, _play
from tests.test_world_generation import _prepare, _row


def reserve_forest(settings, cid):
    async def go(ctx):
        root = (await _ok(ctx, 'create_location', {'name': 'Лес'}))['location_id']
        campaign = await ctx.session.get(Campaign, cid)
        mandate = Mandate(place='Лес', spatial=default_spatial('Лес', ['wild'], template_id='location.forest'))
        row = await store.reserve_plan_layout(ctx.session, campaign, ctx.world.entities[root], mandate,
            template_context=TemplateContext(template_id='location.forest'))
        storage.activate(row)
        return row.id
    return _play(settings, cid, go)


@pytest.mark.parametrize('llm_enabled', [True, False])
def test_template_avoids_model_even_at_spend_limit(client, admin, settings, llm_enabled):
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layout_templates=True, location_layouts_llm=llm_enabled, spend_limit_usd=0)
    ref = reserve_forest(settings, cid)
    assert _row(settings, ref).reservation['template_selection']['outcome'] == 'selected'
    llm = ScriptedLLM([])
    assert _prepare(settings, cid, ref, _orch(llm)) == 'ready'
    row = _row(settings, ref)
    assert row.quality == 'normal' and row.llm_attempt_count == 0 and llm.requests == []
    assert row.result_manifest['source'].startswith('source:template:')


def test_snapshot_survives_catalog_change(client, admin, settings, monkeypatch):
    from app.core.layout import template_catalog
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layout_templates=True, location_layouts_llm=False)
    ref = reserve_forest(settings, cid)
    monkeypatch.setattr(template_catalog, 'load_catalog', lambda: ())
    assert _prepare(settings, cid, ref) == 'ready'
    assert _row(settings, ref).result_manifest['source'].startswith('source:template:')


def test_corrupt_snapshot_falls_back_without_lowering_quality(client, admin, settings):
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layout_templates=True, location_layouts_llm=False)
    ref = reserve_forest(settings, cid)
    async def corrupt(session):
        row = await session.get(WorldGenerationState, ref)
        selection = {**row.reservation['template_selection'], 'intent': {}}
        row.reservation = {**row.reservation, 'template_selection': selection}
        await session.commit()
    run(settings, corrupt)
    assert _prepare(settings, cid, ref) == 'ready'
    assert _row(settings, ref).quality == 'normal'
    assert _row(settings, ref).result_manifest['template_fallback'] == 'snapshot_invalid'


def test_disabled_templates_keep_previous_pipeline(client, admin, settings):
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layout_templates=False, location_layouts_llm=False)
    ref = reserve_forest(settings, cid)
    assert 'template_selection' not in _row(settings, ref).reservation
    assert _prepare(settings, cid, ref) == 'ready'


def test_architect_plan_develop_uses_catalog_without_owner_selection(client, admin, settings):
    from sqlalchemy import select

    from tests.layout_plan_pilot import temple_plan
    from tests.test_layout_develop import _campaign, _develop
    plan = temple_plan()
    plan['locations'][0]['template_id'] = 'location.forest'
    plan['locations'][0]['spatial'] = default_spatial('Лес', template_id='location.forest').model_dump(mode='json')
    cid = _campaign(client, admin, settings, plan=plan,
                    location_layouts=True, location_layout_templates=True, location_layouts_llm=True)
    _develop(settings, cid)
    async def find(session):
        return (await session.scalars(select(WorldGenerationState).where(
            WorldGenerationState.campaign_id == cid, WorldGenerationState.phase == 'location_layout'))).one()
    row = run(settings, find)
    assert row.reservation['template_selection']['outcome'] == 'selected'
    llm = ScriptedLLM([])
    assert _prepare(settings, cid, row.id, _orch(llm)) == 'ready'
    assert llm.requests == []


def test_old_campaign_without_setting_keeps_previous_behavior(client, admin, settings):
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts_llm=False)
    async def remove_flag(session):
        campaign = await session.get(Campaign, cid)
        campaign.settings = {k: v for k, v in campaign.settings.items() if k != 'location_layout_templates'}
        await session.commit()
    run(settings, remove_flag)
    ref = reserve_forest(settings, cid)
    assert 'template_selection' not in _row(settings, ref).reservation
    assert _prepare(settings, cid, ref) == 'ready'


def test_repeated_reservation_does_not_reselect(client, admin, settings, monkeypatch):
    from app.core.layout import template_catalog
    cid, _, _ = _setup(client, admin, settings)
    _flags(settings, cid, location_layout_templates=True)
    ref = reserve_forest(settings, cid)
    original = _row(settings, ref).reservation
    monkeypatch.setattr(template_catalog, 'load_catalog', lambda: (_ for _ in ()).throw(AssertionError('reselect')))
    async def again(ctx):
        campaign = await ctx.session.get(Campaign, cid)
        mandate = Mandate.model_validate(original['mandate'])
        row = await store.reserve_plan_layout(ctx.session, campaign, ctx.world.entities[original['root_id']], mandate)
        return row.id
    assert _play(settings, cid, again) == ref
    assert _row(settings, ref).reservation == original
