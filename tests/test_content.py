from pathlib import Path
from textwrap import dedent

import pytest

from app.content import ContentRegistry, PackError, load_pack, load_with_dependencies
from app.content.__main__ import main as cli
from app.content.manifest import version_satisfies
from app.content.yaml_io import loads

CONTENT = Path(__file__).resolve().parents[1] / "content"
BASE = CONTENT / "dnd5e-srd"


def write_pack(root: Path, files: dict[str, str], manifest: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "pack.yaml").write_text(
        dedent(
            manifest
            or """
            id: test-world
            name: Тестовый мир
            version: 0.1.0
            ruleset: dnd5e
            ruleset_base: srd-5.1
            """
        )
    )
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(dedent(text))
    return root


def world(tmp_path: Path, files: dict[str, str], manifest: str | None = None, strict: bool = False):
    """Пакет мира рядом с копией базового: как в content/ репозитория."""
    packs = tmp_path / "content"
    packs.mkdir(exist_ok=True)
    (packs / "dnd5e-srd").symlink_to(BASE, target_is_directory=True)
    root = write_pack(packs / "world", files, manifest)
    return load_with_dependencies(root, packs, strict=strict)


EFF = "kind: effect_template\nitems:\n"

EFFECT = """
kind: effect_template
items:
  - id: effect.rot
    name: Гниль
    status: canon
    modifiers:
      - {op: condition, condition: poisoned}
      - {op: custom, text: "не формализовано", draft: {op: teleport_everyone}}
    triggers:
      - {on: turn_start, do: [{op: resource, stat: hp, delta: -1}]}
"""


def test_base_pack_is_valid():
    pack, report = load_pack(BASE)
    assert report.ok, report.errors
    assert pack.manifest.provides == "srd-5.1"
    assert report.counts["effect_template"] == 16
    assert report.counts["item_template"] == 64  # оружие, доспехи, снаряжение и зелья
    assert report.counts["creature_template"] == 334
    assert report.counts["class"] == 12
    assert report.counts["origin"] == 9
    assert report.counts["hazard_template"] == 1
    assert report.customs == []


def test_registry_dc_scale_and_conditions():
    pack, _ = load_pack(BASE)
    reg = ContentRegistry([pack])
    assert [r.data["value"] for r in reg.dc_scale()] == [5, 10, 15, 20, 25, 30]
    assert reg.dc("dc.medium") == 15
    assert reg.condition("poisoned").data["name"] == "Отравленный"
    with pytest.raises(KeyError):
        reg.dc("item.longsword")


def test_world_pack_on_top_of_base(tmp_path):
    chain, report = world(tmp_path, {"data/effects.yaml": EFFECT})
    assert report.ok, report.errors
    assert [p.id for p in chain] == ["dnd5e-srd", "test-world"]
    assert report.counts == {"effect_template": 1}
    assert len(report.customs) == 1
    reg = ContentRegistry(chain)
    assert reg.get("effect.rot").data["triggers"][0]["on"] == "turn_start"


def test_yaml_on_key_stays_string():
    assert loads("on: turn_start") == {"on": "turn_start"}
    assert loads("x: yes") == {"x": "yes"}
    assert loads("x: true") == {"x": True}


def test_strict_turns_custom_into_error(tmp_path):
    _, report = world(tmp_path, {"data/effects.yaml": EFFECT}, strict=True)
    assert not report.ok and "--strict" in report.errors[-1]


@pytest.mark.parametrize(
    ("files", "needle"),
    [
        ({"data/x.yaml": "kind: dragon_lair\nitems: []\n"}, "неизвестный вид"),
        ({"data/x.yaml": "items: []\n"}, "{kind, items}"),
        (
            {"data/x.yaml": EFF + "  - {id: effect.a, name: A, status: canon, modifiers: [{op: teleport}]}\n"},
            "движок не умеет op 'teleport'",
        ),
        (
            {
                "data/x.yaml": EFF + "  - {id: effect.a, name: A, status: canon, modifiers: [],"
                " cure_refs: [item.nope]}\n"
            },
            "несуществующий id item.nope",
        ),
        (
            {
                "data/x.yaml": EFF + "  - {id: effect.a, name: A, status: canon, modifiers: "
                "[{op: condition, condition: sleepy}]}\n"
            },
            "нет состояния 'sleepy'",
        ),
        (
            {
                "data/x.yaml": EFF + "  - {id: effect.a, name: A, status: canon, modifiers: []}\n"
                "  - {id: effect.a, name: B, status: canon, modifiers: []}\n"
            },
            "дубликат id",
        ),
        ({"data/x.yaml": EFF + "  - {id: effect.a, name: A, status: final}\n"}, "status"),
        ({"data/x.yaml": "kind: dc_scale\nitems:\n  - {id: dc.x, name: X, status: canon, value: 99}\n"}, "value"),
    ],
)
def test_errors_are_reported(tmp_path, files, needle):
    _, report = world(tmp_path, files)
    assert not report.ok
    assert any(needle in e for e in report.errors), report.errors


def test_override_and_excludes(tmp_path):
    manifest = """
    id: test-world
    name: Тестовый мир
    version: 0.1.0
    ruleset: dnd5e
    ruleset_base: srd-5.1
    excludes: [item.longbow]
    """
    files = {
        "data/items.yaml": """
        kind: item_template
        items:
          - {id: item.longsword, name: Хитиновый меч, status: canon, category: weapon, price: {fk: 150}}
          - {id: item.bow_user, name: Лучник, status: canon, category: gear, price: {fk: 1}, needs_ref: item.longbow}
        """
    }
    chain, report = world(tmp_path, files, manifest)
    assert report.overrides == ["item.longsword"]
    assert any("исключённую запись item.longbow" in e for e in report.errors)
    reg = ContentRegistry(chain)
    assert reg.get("item.longsword").data["name"] == "Хитиновый меч"
    assert "item.longbow" not in reg


def test_own_schema_is_stricter(tmp_path):
    files = {
        "schema/schema.yaml": "kinds:\n  location_template: {required: [belt]}\n",
        "data/loc.yaml": "kind: location_template\nitems:\n  - {id: location.pier, name: Пирс, status: canon}\n",
    }
    _, report = world(tmp_path, files)
    assert any("belt" in e for e in report.errors)


def test_engine_requirements(tmp_path):
    manifest = """
    id: test-world
    name: Тестовый мир
    version: 0.1.0
    ruleset: dnd5e
    engine: {min_version: 9.0.0, ops: [add, teleport]}
    depends: {some-other-world: ">=1.0.0"}
    """
    _, report = world(tmp_path, {"data/x.yaml": "kind: dc_scale\nitems: []\n"}, manifest)
    joined = "\n".join(report.errors)
    assert "движок 9.0.0" in joined and "teleport" in joined and "some-other-world" in joined


def test_bad_manifest(tmp_path):
    root = write_pack(tmp_path / "w", {}, "id: Bad Id\nname: x\nversion: 1\nruleset: dnd5e\n")
    with pytest.raises(PackError):
        load_pack(root)


def test_version_constraints():
    assert version_satisfies("1.2.3", ">=1.2.0")
    assert not version_satisfies("1.1.9", ">=1.2.0")
    assert version_satisfies("1.2.3", "1.2.3") and version_satisfies("1.2.3", "*")


def test_cli(capsys):
    assert cli(["validate", str(BASE)]) == 0
    assert "OK" in capsys.readouterr().out
