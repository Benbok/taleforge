import pytest

from app.rules.dice import Dice, DiceError, FixedDice, parse


def test_parse_and_render():
    e = parse("2d6 + 3")
    assert e.text == "2d6+3"
    assert e.modifier == 3
    assert parse("d20").text == "1d20"
    assert parse("1d8-1").modifier == -1
    assert parse("1").text == "1"


@pytest.mark.parametrize("bad", ["", "2d7", "d", "1d6+x", "0d6", "101d6", "2d6++1", None])
def test_parse_rejects(bad):
    with pytest.raises(DiceError):
        parse(bad)


def test_critical_doubles_dice_not_modifier():
    assert parse("2d6+3").doubled_dice().text == "4d6+3"
    assert parse("1d8+1d6+2").doubled_dice().text == "2d8+2d6+2"


def test_seeded_rolls_repeat():
    a = [Dice(seed=42).roll("3d6").total for _ in range(3)]
    b = [Dice(seed=42).roll("3d6").total for _ in range(3)]
    assert a == b
    r = Dice(seed=1).roll("4d6+2")
    assert len(r.rolls) == 4
    assert r.total == sum(v for _, v in r.rolls) + 2
    assert all(1 <= v <= 6 for _, v in r.rolls)


def test_fixed_dice():
    d = FixedDice([5, 6])
    assert d.roll("2d6+1").total == 12
    with pytest.raises(DiceError):
        d.d20()
    with pytest.raises(DiceError):
        FixedDice([7]).die(6)
