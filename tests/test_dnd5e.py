import pytest

from app.rules import FixedDice, RollMode, get_engine
from app.rules.base import DeathSaves, HitPoints
from app.rules.dnd5e import Dnd5eEngine
from app.rules.dnd5e.engine import RulesError

E = Dnd5eEngine()


def test_get_engine():
    assert get_engine("dnd5e").ruleset_id == "dnd5e"
    with pytest.raises(KeyError):
        get_engine("gurps")


@pytest.mark.parametrize(("score", "mod"), [(1, -5), (8, -1), (9, -1), (10, 0), (11, 0), (15, 2), (20, 5), (30, 10)])
def test_ability_modifier(score, mod):
    assert E.ability_modifier(score) == mod


@pytest.mark.parametrize(("level", "pb"), [(1, 2), (4, 2), (5, 3), (8, 3), (9, 4), (13, 5), (17, 6), (20, 6)])
def test_proficiency_bonus(level, pb):
    assert E.proficiency_bonus(level) == pb


def test_out_of_range():
    with pytest.raises(RulesError):
        E.ability_modifier(0)
    with pytest.raises(RulesError):
        E.proficiency_bonus(21)
    with pytest.raises(RulesError):
        E.check(FixedDice([10]), 0, 0)


def test_check_modifier_and_passive():
    assert E.check_modifier(14, 5, proficient=True) == 2 + 3
    assert E.check_modifier(14, 5, expertise=True) == 2 + 6
    assert E.passive_score(3) == 13
    assert E.passive_score(3, RollMode.DISADVANTAGE) == 8
    assert E.skill_ability("stealth") == "dex"
    assert E.spell_save_dc(16, 1) == 8 + 2 + 3


def test_roll_mode_combine():
    assert RollMode.combine(True, False) is RollMode.ADVANTAGE
    assert RollMode.combine(False, True) is RollMode.DISADVANTAGE
    assert RollMode.combine(True, True) is RollMode.NORMAL


def test_check_meets_dc_and_margin():
    r = E.check(FixedDice([12]), 3, 15)
    assert r.success and r.margin == 0
    r = E.check(FixedDice([4]), 3, 15)
    assert not r.success and r.margin == -8


def test_natural_20_on_check_is_not_auto_success():
    assert not E.check(FixedDice([20]), 0, 25).success


def test_advantage_and_disadvantage_pick_die():
    assert E.roll_d20(FixedDice([3, 17]), 0, RollMode.ADVANTAGE).natural == 17
    assert E.roll_d20(FixedDice([3, 17]), 0, RollMode.DISADVANTAGE).natural == 3


def test_attack_crit_and_fumble():
    a = E.attack(FixedDice([20]), 0, 30)
    assert a.hit and a.critical
    a = E.attack(FixedDice([1]), 20, 5)
    assert not a.hit
    a = E.attack(FixedDice([10]), 5, 15)
    assert a.hit and not a.critical


def test_damage_critical_and_defenses():
    d = E.damage(FixedDice([3, 4]), "1d6+2", "slashing", critical=True)
    assert d.roll.text == "2d6+2" and d.final == 9
    d = E.damage(FixedDice([5]), "1d6", "fire", resistances=frozenset({"fire"}))
    assert d.final == 2 and d.applied == ("resistance",)
    d = E.damage(FixedDice([5]), "1d6", "cold", vulnerabilities=frozenset({"cold"}))
    assert d.final == 10
    d = E.damage(FixedDice([5]), "1d6", "poison", immunities=frozenset({"poison"}))
    assert d.final == 0
    with pytest.raises(RulesError):
        E.damage(FixedDice([1]), "1d6", "banana")


def test_temp_hp_absorb_first_and_do_not_stack():
    hp = HitPoints(current=10, maximum=10, temp=5)
    ch = E.apply_damage(hp, 7)
    assert (hp.temp, hp.current) == (0, 8) and ch.temp_before == 5
    E.add_temp_hp(hp, 4)
    E.add_temp_hp(hp, 3)
    assert hp.temp == 4


def test_drop_to_zero_and_instant_death():
    hp = HitPoints(current=6, maximum=12)
    ch = E.apply_damage(hp, 10)
    assert ch.dropped_to_zero and not ch.dead and hp.dying
    hp = HitPoints(current=6, maximum=12)
    ch = E.apply_damage(hp, 18)
    assert ch.instant_death and hp.dead


def test_damage_at_zero_hp_adds_failures():
    hp = HitPoints(current=0, maximum=20)
    E.apply_damage(hp, 3)
    assert hp.death_saves.failures == 1
    E.apply_damage(hp, 3, critical=True)
    assert hp.death_saves.failures == 3 and hp.dead


def test_damage_at_zero_massive_kills():
    hp = HitPoints(current=0, maximum=10)
    assert E.apply_damage(hp, 10).instant_death


def test_stable_creature_hit_again_starts_dying():
    hp = HitPoints(current=0, maximum=10, death_saves=DeathSaves(successes=3))
    assert not hp.dying
    E.apply_damage(hp, 1)
    assert hp.dying and hp.death_saves.successes == 0 and hp.death_saves.failures == 1


def test_death_saves():
    hp = HitPoints(current=0, maximum=10)
    E.death_save(FixedDice([10]), hp)
    E.death_save(FixedDice([9]), hp)
    assert (hp.death_saves.successes, hp.death_saves.failures) == (1, 1)
    E.death_save(FixedDice([1]), hp)
    assert hp.dead
    hp = HitPoints(current=0, maximum=10)
    r = E.death_save(FixedDice([20]), hp)
    assert r.regained_hp == 1 and hp.current == 1 and not hp.dying
    hp = HitPoints(current=0, maximum=10)
    for _ in range(3):
        E.death_save(FixedDice([15]), hp)
    assert hp.death_saves.stable and not hp.dying
    with pytest.raises(RulesError):
        E.death_save(FixedDice([15]), hp)


def test_heal():
    hp = HitPoints(current=0, maximum=10, death_saves=DeathSaves(1, 2))
    E.heal(hp, 4)
    assert hp.current == 4 and hp.death_saves == DeathSaves()
    E.heal(hp, 100)
    assert hp.current == 10
    dead = HitPoints(current=0, maximum=10, dead=True)
    E.heal(dead, 5)
    assert dead.current == 0


def test_armor_class():
    assert E.armor_class(3) == 13
    assert E.armor_class(3, {"ac_base": 11, "dex_cap": None}) == 14
    assert E.armor_class(3, {"ac_base": 14, "dex_cap": 2}, shield_bonus=2) == 18
    assert E.armor_class(3, {"ac_base": 18, "dex_cap": 0}) == 18
    assert E.armor_class(-1, {"ac_base": 18, "dex_cap": 0}) == 17


def test_hit_points_max():
    assert E.hit_points_max(10, 2, 1) == 12
    assert E.hit_points_max(10, 2, 3) == 12 + 2 * 8
    assert E.hit_points_max(6, -3, 2) == 3 + 1


def test_initiative_order_ties():
    a = E.initiative(FixedDice([12]), 2)
    b = E.initiative(FixedDice([11]), 3)
    c = E.initiative(FixedDice([14]), 0)
    assert E.initiative_order([("a", a, 2), ("b", b, 3), ("c", c, 0)]) == ["b", "a", "c"]
