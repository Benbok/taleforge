"""Special furniture receives stable artwork without changing physical properties."""

import pytest

from app.core.layout.intent import DetailIntent


@pytest.mark.parametrize(
    "name,key",
    [
        ("Письменный стол", "feature:desk"),
        ("Оскверненный трон", "feature:defiled_throne"),
        ("Королевский трон", "feature:throne"),
        ("Стойка с орудиями", "feature:weapon_rack"),
        ("Стол для инструментов", "feature:tool_table"),
        ("Стол для пыток", "feature:torture_table"),
        ("Стол с оружием", "feature:weapon_table"),
        ("Кресло для допросов", "feature:torture_chair"),
    ],
)
def test_missing_visual_key_is_resolved_from_specific_furniture_purpose(name, key):
    d = DetailIntent(detail_ref="prop", name=name, kind="furniture", cells=[[0, 0, 1, 1]], solid=True)
    assert d.visual_key == key
    assert d.cells == [[0, 0, 1, 1]] and d.solid
    assert DetailIntent.model_validate(d.model_dump()) == d


def test_authored_visual_key_takes_precedence_over_name():
    d = DetailIntent(
        detail_ref="prop", name="Стол для пыток", kind="furniture", cells=[[0, 0, 1, 1]], visual_key="feature:altar"
    )
    assert d.visual_key == "feature:altar"
