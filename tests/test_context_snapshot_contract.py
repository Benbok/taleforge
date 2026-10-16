"""Contracts for addressable live narrative facts in the master snapshot."""

from types import SimpleNamespace

from app.agents.master.context_selection import ContextFact, select_context
from app.agents.master.context_snapshot import collect_context_snapshot, fact_key
from app.core.narrative.contracts import FactRef, FactState, SnapshotRef
from app.core.narrative.view import compose_view


def _ref(subject_id, key, *, version=1, source_id="source"):
    return FactRef(
        campaign_id="campaign-1",
        namespace="campaign",
        subject_id=subject_id,
        key=key,
        version=version,
        snapshot_ref=SnapshotRef(
            kind="event",
            source_id=source_id,
            version=version,
            typed_address=f"event:{source_id}:{version}",
        ),
    )


def _world_with_facts(facts):
    view = compose_view({}, tuple(facts), ())
    place = SimpleNamespace(id="place-1", kind="location", name="Площадь", state={}, location_id=None)
    npc = SimpleNamespace(
        id="npc-1",
        kind="creature",
        name="Смотритель",
        location_id=place.id,
        template_id="npc-template-1",
        state={},
    )

    def narrative_facts(subject_ids, *, audience=None):
        return view.facts_for(tuple(subject_ids), audience=audience)

    world = SimpleNamespace(
        scene=SimpleNamespace(location_id=place.id),
        focus=None,
        characters={},
        entities={place.id: place, npc.id: npc},
        inventory={},
        effects=[],
        plot={},
        revealed={},
        crew=set(),
        narrative_view=view,
        narrative_facts=narrative_facts,
    )
    return SimpleNamespace(world=world, required_actions=())


def test_fact_key_preserves_full_semantic_identity():
    first = _ref("npc-1", "role", version=1, source_id="old")
    second = _ref("npc-1", "role", version=2, source_id="new")
    template = _ref("npc-template-1", "role", version=1, source_id="template")

    assert len({fact_key(first), fact_key(second), fact_key(template)}) == 3
    assert all(value.startswith("fact:") for value in (fact_key(first), fact_key(second), fact_key(template)))


def test_snapshot_keeps_instance_and_template_facts_and_closes_dependencies():
    remote = _ref("remote-resource", "situation_premise", version=3, source_id="remote")
    role = _ref("npc-1", "role", version=1, source_id="role")
    motivation = _ref("npc-1", "motivation", version=2, source_id="motivation")
    template_role = _ref("npc-template-1", "role", version=4, source_id="template")
    facts = (
        FactState(
            ref=remote,
            kind="truth",
            temporal_semantics="current_state",
            freedom="committed",
            value="Удалённый ресурс обязателен для решения",
        ),
        FactState(
            ref=role,
            kind="truth",
            temporal_semantics="current_state",
            freedom="committed",
            value="Смотритель охраняет мост",
        ),
        FactState(
            ref=motivation,
            kind="truth",
            temporal_semantics="current_state",
            freedom="committed",
            value="Смотритель ждёт обещание",
            depends_on=(remote,),
        ),
        FactState(
            ref=template_role,
            kind="truth",
            temporal_semantics="current_state",
            freedom="committed",
            value="Шаблонный архетип смотрителя",
        ),
    )
    context_facts = collect_context_snapshot(_world_with_facts(facts), None, messages=(), memory="", history="")
    by_value = {item.text: item for item in context_facts}

    assert "Смотритель охраняет мост" in by_value
    assert "Смотритель ждёт обещание" in by_value
    assert "Шаблонный архетип смотрителя" in by_value
    assert "Удалённый ресурс обязателен для решения" in by_value
    assert len({item.key for item in context_facts if item.section == "reactions"}) == 4
    assert fact_key(remote) in by_value["Смотритель ждёт обещание"].dependencies

    selected = select_context(
        tuple(context_facts),
        role="decide",
        subjects=frozenset({"npc-1"}),
        audience=frozenset({"master"}),
    )
    assert fact_key(remote) in {item.key for item in selected.facts}


def test_unknown_dependency_expands_its_section_with_reason():
    facts = (
        ContextFact(
            key="root",
            section="reactions",
            text="ROOT",
            subjects=frozenset({"npc-1"}),
            dependencies=frozenset({"missing-resource"}),
            audience=frozenset({"master"}),
        ),
        ContextFact(
            key="sibling",
            section="reactions",
            text="SIBLING",
            subjects=frozenset({"remote-resource"}),
            dependencies=frozenset(),
            audience=frozenset({"master"}),
        ),
    )

    selected = select_context(
        facts,
        role="decide",
        subjects=frozenset({"npc-1"}),
        audience=frozenset({"master"}),
    )

    assert {item.key for item in selected.facts} == {"root", "sibling"}
    assert selected.expansion_reasons == ("unknown_dependency:missing-resource",)


def test_structural_values_are_not_truncated_in_snapshot():
    place = SimpleNamespace(
        id="place-1", kind="location", name="Площадь", state={"layout": "x" * 7000}, location_id=None
    )
    world = SimpleNamespace(
        scene=SimpleNamespace(location_id=place.id),
        focus=None,
        characters={},
        entities={place.id: place},
        inventory={},
        effects=[],
        plot={"obligation": "y" * 7000},
        revealed={},
        crew=set(),
        narrative_facts=lambda _subjects, **_kwargs: (),
    )

    facts = collect_context_snapshot(
        SimpleNamespace(world=world, required_actions=()), None, messages=(), memory="", history=""
    )
    place_text = next(item.text for item in facts if item.key == "place:place-1")
    plot_text = next(item.text for item in facts if item.key == "plot:live")

    assert "x" * 7000 in place_text
    assert "y" * 7000 in plot_text
