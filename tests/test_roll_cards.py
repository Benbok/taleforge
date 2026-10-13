"""Карточки бросков в чате: игрок отличает свой удар от автоматического."""

import pytest

from app.core.rolls import card, line
from app.db.models import Event

DICE = [{"sides": 20, "result": 3}]
ATTACK = {"attack": "Боевой посох", "attacker": "Пупкинатор", "target": "Зверь Гаррота", "hit": False, "roll": 3}


@pytest.mark.parametrize("key", ["t_1:combat:0:oa:ch_hero", "oa:en_wolf:2"])
def test_opportunity_attack_card_says_so(key):
    """Плейтест: удар вдогонку убегающему волку выглядел как второй удар игрока «с двух рук»."""
    c = card(
        Event(tool="resolve_attack", payload=ATTACK, idempotency_key=key, target_id="en_wolf", dice=DICE, hidden=False),
        set(),
    )
    assert c["title"] == "Атака по возможности: Боевой посох"
    assert "Атака по возможности" in line(c)


def test_regular_attack_card_is_unchanged():
    c = card(
        Event(
            tool="resolve_attack",
            payload=ATTACK,
            idempotency_key="t_1:call_9",
            target_id="en_wolf",
            dice=DICE,
            hidden=False,
        ),
        set(),
    )
    assert c["title"] == "Атака: Боевой посох"
