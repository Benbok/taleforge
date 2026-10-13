"""Мандат и лестница детерминированных замыслов (спецификация 2026-10-12, §3.2, §8)."""

import itertools

import pytest
from pydantic import ValidationError

from app.core.layout.contracts import LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Holder, Mandate, SpatialPlan, intent_candidates, obligations
from tests.layout_plan_pilot import model_layout, temple_mandate

HOLDERS = dict(
    anchors=[Holder(key="a1", name="Письмо"), Holder(key="a2", name="Перстень")],
    residents=[Holder(key="npc:x", name="Смотритель"), Holder(key="npc:y", name="Сторож")],
)


def _variants(n: int, env: str):
    base = [{"ref": f"p{i}", "name": f"Часть {i}"} for i in range(n)]
    if env == "outdoor":
        base = [p | {"outdoor": True} for p in base]
    if env == "mixed":
        base[0]["outdoor"] = True
    yield base
    if n >= 3:
        yield base[:-1] + [base[-1] | {"secret": True, "outdoor": False}]
        yield base[:-1] + [base[-1] | {"below": True, "outdoor": False}]
        yield base[:-2] + [
            base[-2] | {"secret": True, "outdoor": False},
            base[-1] | {"below": True, "outdoor": False},
        ]
        yield (base[:1] + [base[1] | {"required": True}] + base[2:-1] + [base[-1] | {"secret": True, "outdoor": False}])
    if env == "mixed" and n >= 2:  # вход — помещение, двор дальше
        yield [{"ref": f"p{i}", "name": f"Часть {i}", "outdoor": i == n - 1} for i in range(n)]


def _cases():
    for env, scale, n, nap, kind in itertools.product(
        ("indoor", "outdoor", "mixed"),
        ("small", "medium", "large"),
        range(1, 7),
        (1, 2, 3),
        ("road", "door"),
    ):
        for parts in _variants(n, env):
            if env == "mixed" and {p.get("outdoor", False) for p in parts} != {True, False}:
                continue
            yield {
                "environment": env,
                "scale": scale,
                "parts": parts,
                "approaches": [{"name": f"Подход {k}", "kind": kind} for k in range(nap)],
            }


def test_every_spatial_plan_lays_out_and_keeps_obligations():
    provider = DeterministicLayoutProvider()
    total = 0
    for raw in _cases():
        m = Mandate(place="Место", spatial=SpatialPlan.model_validate(raw), **HOLDERS)
        built = None
        for intent in intent_candidates(m):
            assert obligations(intent, m) == [], (raw, obligations(intent, m))
            for fallback in (False, True):
                try:
                    built = provider.propose(intent, seed=12345, root_id="root", fallback=fallback)
                    break
                except LayoutError:
                    continue
            if built is not None:
                break
        assert built is not None, raw
        total += 1
    assert total > 1000


def test_candidates_put_holders_where_the_plan_expects():
    m = temple_mandate()
    first = intent_candidates(m)[0]
    by = {p.part_ref: p for p in first.parts}
    assert first.entry == "road" and by["chapel"].anchors == ["clue_relic"] and by["road"].anchors == ["npc:npc_warden"]
    assert by["vault"].secret and by["crypt"].level == -1 and by["chapel"].required
    assert all(a.outside_id is None for a in first.approaches)
    assert [b.kind for b in first.bands] == ["road"] and not intent_candidates(m)[1].bands


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda r: r.update(parts=[p for p in r["parts"] if p["part_ref"] != "crypt"]), "нет обязательной части crypt"),
        (lambda r: next(p for p in r["parts"] if p["part_ref"] == "vault").update(secret=False), "vault: тайность"),
        (lambda r: next(p for p in r["parts"] if p["part_ref"] == "chapel").update(anchors=[]), "clue_relic"),
        (lambda r: r.update(entry="narthex"), "вход — часть road"),
        (lambda r: r["approaches"][0].update(outside_id="en_x"), "подход"),
    ],
)
def test_obligations_name_what_the_model_broke(mutate, text):
    m = temple_mandate()
    raw = model_layout(["clue_relic", "npc:npc_warden"])
    mutate(raw)
    errors = obligations(LayoutIntent.model_validate(raw), m)
    assert any(text in e for e in errors), errors


def test_model_layout_fixture_keeps_obligations():
    m = temple_mandate()
    assert obligations(LayoutIntent.model_validate(model_layout(["clue_relic", "npc:npc_warden"])), m) == []


def test_mandate_limits_holders():
    many = [Holder(key=f"a{i}", name="x") for i in range(9)]
    with pytest.raises(ValidationError):
        Mandate(place="Место", spatial=temple_mandate().spatial, anchors=many)
