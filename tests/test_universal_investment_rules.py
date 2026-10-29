import pytest

from app.rules.dice import FixedDice
from app.rules.universal.investment import (
    INVEST_COST_FACTOR,
    INVEST_MAX_SHORTFALL,
    INVEST_TIMEOUT_SECONDS,
    invest_price,
    shortfall,
)
from app.rules.universal.profiles import CheckProof, resolve_check


def test_constants_are_the_agreed_balance():
    assert (INVEST_COST_FACTOR, INVEST_MAX_SHORTFALL, INVEST_TIMEOUT_SECONDS) == (3, 5, 45)


@pytest.mark.parametrize(
    "natural, total, dc, expected",
    [(10, 9, 12, 3), (1, 11, 12, 0), (20, 15, 40, 0), (15, 15, 12, 0)],
)
def test_shortfall_is_zero_when_investment_cannot_help(natural, total, dc, expected):
    assert shortfall(natural, total, dc) == expected


@pytest.mark.parametrize("level, price", [(1, 9), (10, 90)])
def test_price_scales_with_level(level, price):
    assert invest_price(3, level) == price


def test_bonus_turns_a_near_miss_into_a_plain_success():
    result = resolve_check(FixedDice([10]), 8, False, 12, bonus=3)
    assert result.success and result.total == 12 and not result.critical


def test_bonus_never_rescues_a_natural_one():
    result = resolve_check(FixedDice([1]), 8, False, 12, bonus=100)
    assert not result.success and result.critical_failure


def test_check_proof_defaults_to_no_investment():
    proof = CheckProof(target_id="a", attribute="cha", natural=10, modifier=-1, total=9, success=False)
    assert proof.invested == 0
