"""Offline catalog stays compatible with production geometry and movement."""
import json
from pathlib import Path

import pytest

from app.core import reach, sketch
from app.core.layout.contracts import Blueprint, rect_cells
from app.core.layout.geometry import build_area
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider

CATALOG = Path(__file__).parents[1] / 'experiments/location-layout-templates/templates'
TEMPLATES = sorted(CATALOG.glob('*/intent.json'))


@pytest.mark.parametrize('path', TEMPLATES, ids=lambda p: p.parent.name)
@pytest.mark.parametrize('seed', [1, 7, 42, 99, 123])
def test_catalog_geometry_and_visuals_agree(path, seed):
    intent = LayoutIntent.model_validate_json(path.read_text(encoding='utf-8'))
    provider = DeterministicLayoutProvider()
    root = 'tpl_' + path.parent.name
    bp = provider.propose(intent, seed=seed, root_id=root)
    assert bp == Blueprint.from_json(bp.to_json())
    assert bp == provider.propose(intent, seed=seed, root_id=root)
    ids = {a.area_ref: a.area_ref for a in bp.areas}
    for area in bp.areas:
        geometry = build_area(bp, area, root_id=root, ids=ids)
        solid = set().union(*(rect_cells(d.cells) for d in area.details if d.solid))
        assert solid <= sketch.solid_cells(geometry)
        assert solid <= reach.blocked_cells(geometry)
        assert len(geometry['features']) == len(area.details)
        assert all(e['to'] in {*ids.values(), root} for e in geometry['exits'])
        assert not sketch.check(geometry, {*ids.values(), root})
    meta = json.loads((path.parent/'metadata.json').read_text(encoding='utf-8'))
    if seed == meta['selected_seed']:
        assert bp.to_json() == json.loads((path.parent/'blueprint.json').read_text(encoding='utf-8'))


def test_catalog_covers_six_archetypes_with_four_variants():
    assert len(TEMPLATES) == 24
    entries = [json.loads((p.parent/'metadata.json').read_text(encoding='utf-8')) for p in TEMPLATES]
    for archetype in ('tavern', 'temple', 'cave', 'forest', 'port', 'ruins'):
        assert {e['variant'] for e in entries if e['archetype'] == archetype} == {'A', 'B', 'C', 'D'}
