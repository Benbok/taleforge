"""The supported application must boot without the retired D&D implementation."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_active_application_has_no_legacy_rule_imports():
    imports = []
    for path in (ROOT / "app").rglob("*.py"):
        if "dnd5e" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("app.rules.dnd5e"):
                imports.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.module}")
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names if alias.name.startswith("app.rules.dnd5e"))
    assert imports == [], "Retired rules still imported:\n" + "\n".join(imports)


def test_universal_app_imports_with_retired_modules_unavailable():
    script = """
import importlib.abc
import sys

class Retired(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith('app.rules.dnd5e') or fullname in {'app.tools.rest', 'app.tools.spells'}:
            raise ModuleNotFoundError('Retired gameplay dependency: ' + fullname)

sys.meta_path.insert(0, Retired())
from app.main import create_app
from app.config import Settings
app = create_app(Settings(database_url='sqlite+aiosqlite:///:memory:', jwt_secret='test-secret-' * 5))
assert not any('dnd5e' in name for name in sys.modules)
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr


def test_retired_implementation_files_are_absent():
    assert not list((ROOT / "app/rules/dnd5e").glob("*.py"))
    assert not (ROOT / "app/tools/rest.py").exists()
    assert not (ROOT / "app/tools/spells.py").exists()


def test_new_campaign_model_defaults_to_universal():
    from app.db.models import Campaign

    assert Campaign.__table__.c.ruleset_id.default.arg == "universal"


def test_shared_arithmetic_retains_roll_modes_and_death_saves_without_level_caps():
    from app.rules.base import HitPoints, RollMode
    from app.rules.common import ScalarRules
    from app.rules.dice import FixedDice

    rules = ScalarRules()
    assert rules.ability_modifier(1000) == 495
    assert rules.roll_d20(FixedDice([3, 17]), 2, RollMode.ADVANTAGE).total == 19
    assert rules.roll_d20(FixedDice([3, 17]), 2, RollMode.DISADVANTAGE).total == 5
    hp = HitPoints(0, 22)
    assert rules.death_save(FixedDice([20]), hp).regained_hp == 1
    assert hp.current == 1


def test_shared_damage_preserves_death_and_stabilization_arithmetic():
    from app.rules.base import DeathSaves, HitPoints
    from app.rules.common import ScalarRules

    rules = ScalarRules()
    dead = HitPoints(0, 10, temp=5, dead=True)
    rules.apply_damage(dead, 7)
    assert dead.temp == 5
    dying = HitPoints(0, 10, death_saves=DeathSaves(2, 0))
    rules.apply_damage(dying, 1)
    assert dying.death_saves == DeathSaves(2, 1)
    stable = HitPoints(0, 10, death_saves=DeathSaves(3, 0))
    rules.apply_damage(stable, 1)
    assert stable.death_saves == DeathSaves(0, 1)
    massive = HitPoints(0, 10)
    assert rules.apply_damage(massive, 10).instant_death and massive.dead


def test_stat_explanation_uses_universal_rules_without_class_tables(tmp_path):
    import asyncio

    from app.content.catalog import Catalog
    from app.core.explain import explain_for
    from app.db.models import Character
    from tests.test_universal_resolution import setup

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as session:
            hero = await session.get(Character, "hero")
            ac = await explain_for(session, hero, Catalog({}).view(False), "ac")
            assert str(ac["value"]) == "12"
            hp = await explain_for(session, hero, Catalog({}).view(False), "hp")
            assert str(hp["value"]) == "22"
        await engine.dispose()

    asyncio.run(run())


def test_registered_routes_and_tools_have_no_retired_gameplay():
    from app.config import Settings
    from app.main import create_app
    from app.tools.registry import REGISTRY

    app = create_app(Settings(database_url="sqlite+aiosqlite:///:memory:", jwt_secret="test-secret-" * 5))
    routes = {
        (path, method.upper())
        for path, spec in app.openapi()["paths"].items()
        for method in spec
        if method in {"get", "post", "put", "patch", "delete"}
    }
    prefix = "/api/campaigns/{campaign_id}"
    forbidden = {
        (prefix + "/character-options", "GET"),
        (prefix + "/character-preview", "POST"),
        (prefix + "/characters", "POST"),
        (prefix + "/characters/{character_id}", "PUT"),
        (prefix + "/characters/{character_id}/submit", "POST"),
        (prefix + "/characters/{character_id}/spells", "PUT"),
        (prefix + "/characters/{character_id}/equipment", "PUT"),
    }
    assert not routes & forbidden
    assert not (
        {
            "short_rest",
            "long_rest",
            "cast_spell",
            "grant_level",
            "resolve_attack",
            "roll_initiative",
            "review_character",
        }
        & REGISTRY.keys()
    )
    assert (prefix + "/characters/{character_id}/universal-actions", "POST") in routes
    assert ("/api/hero-creation/dialogues", "POST") in routes
