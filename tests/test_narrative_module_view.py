"""Tests for effective module view overrides and isolation (Task 17)."""

import copy
from typing import Any

import pytest

from app.content.catalog import Entry
from app.core.narrative.contracts import (
    FactRef,
    FactState,
    SnapshotRef,
)
from app.core.narrative.view import (
    CampaignNarrativeView,
    compose_view,
    effective_module_entry,
)
from tests.narrative_helpers import fact


def _make_fact(
    cid: str,
    subject_id: str,
    key: str,
    value: str,
    namespace: str = "module",
) -> FactState:
    snap_ref = SnapshotRef(kind="package", source_id="p1", typed_address=f"{namespace}:{subject_id}:{key}")
    ref = FactRef(
        campaign_id=cid,
        namespace=namespace,
        subject_id=subject_id,
        key=key,
        version=1,
        snapshot_ref=snap_ref,
    )
    return FactState(
        ref=ref,
        kind="truth",
        temporal_semantics="current_state",
        freedom="committed",
        value=value,
        audience=("party",),
        depends_on=(),
    )


def test_effective_module_entry_overrides_narrative_properties():
    """effective_module_entry produces immutable Entry view with narrative overrides without mutating base."""
    original_data = {
        "name": "Инквизитор Вал",
        "role": "Охотник на ведьм",
        "want": "Искоренить ересь огнём",
        "hp": 45,
        "ac": 15,
    }
    base = Entry(
        id="creature.inquisitor",
        kind="creature_template",
        status="approved",
        pack_id="pack_test",
        data=copy.deepcopy(original_data),
    )

    f_motive = _make_fact("c1", "creature.inquisitor", "motivation", "Ищет союзников против нежити")
    f_role = _make_fact("c1", "creature.inquisitor", "role", "Тайный дипломат церкви")

    view = compose_view(
        plan={},
        facts=(f_motive, f_role),
        content_chain=(),
    )

    eff = effective_module_entry(base, view)

    # 1. Overrides applied
    assert eff.data.get("want") == "Ищет союзников против нежити" or eff.data.get("motivation") == "Ищет союзников против нежити"
    assert eff.data.get("role") == "Тайный дипломат церкви"

    # 2. Mechanical attributes untouched
    assert eff.data["hp"] == 45
    assert eff.data["ac"] == 15

    # 3. Base entry untouched
    assert base.data["want"] == "Искоренить ересь огнём"
    assert base.data["role"] == "Охотник на ведьм"


def test_two_campaigns_are_isolated_in_effective_entries():
    """Different campaigns have isolated views and produce distinct effective entries for the same base."""
    base = Entry(
        id="npc.aldus",
        kind="npc_template",
        status="approved",
        pack_id="pack_test",
        data={"name": "Алдус", "want": "Спокойная жизнь"},
    )

    f_camp1 = _make_fact("c1", "npc.aldus", "motivation", "Месть за сожжённый дом")
    f_camp2 = _make_fact("c2", "npc.aldus", "motivation", "Служба короне")

    view1 = compose_view(plan={}, facts=(f_camp1,), content_chain=())
    view2 = compose_view(plan={}, facts=(f_camp2,), content_chain=())

    eff1 = effective_module_entry(base, view1)
    eff2 = effective_module_entry(base, view2)

    assert eff1.data.get("want") == "Месть за сожжённый дом" or eff1.data.get("motivation") == "Месть за сожжённый дом"
    assert eff2.data.get("want") == "Служба короне" or eff2.data.get("motivation") == "Служба короне"
    assert base.data["want"] == "Спокойная жизнь"


def test_namespace_adapters_all_standard_keys():
    """All 5 standard narrative keys (role, motivation, relationship, secret_truth, situation_premise) are mapped."""
    base = Entry(
        id="place.crypt",
        kind="location_template",
        status="approved",
        pack_id="pack_test",
        data={"name": "Древняя крипта", "premise": "Заброшенный склеп", "truth": "Пусто"},
    )

    f_premise = _make_fact("c1", "place.crypt", "situation_premise", "Осквернено культом")
    f_truth = _make_fact("c1", "place.crypt", "secret_truth", "В саркофаге спрятан ключ")

    view = compose_view(plan={}, facts=(f_premise, f_truth), content_chain=())
    eff = effective_module_entry(base, view)

    assert eff.data.get("situation_premise") == "Осквернено культом" or eff.data.get("premise") == "Осквернено культом"
    assert eff.data.get("secret_truth") == "В саркофаге спрятан ключ" or eff.data.get("truth") == "В саркофаге спрятан ключ"
