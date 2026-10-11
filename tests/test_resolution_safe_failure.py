from app.rules.dice import DiceError
from app.tools.registry import execute
from tests.game import QueueDice
from tests.test_tools import game as game_fixture
from tests.test_tools import play

game = game_fixture


class UnavailableDice(QueueDice):
    def die(self, sides):
        raise DiceError("dice service unavailable")


def test_known_dice_failure_is_safe_only_after_check_rollback(game):
    settings, campaign_id, hero = game

    async def check(ctx):
        ctx.dice = UnavailableDice([])
        raw = await execute(
            ctx, "roll_check", {"character_id": hero, "stat": "persuasion", "difficulty": "dc.easy", "reason": "test"}
        )
        assert not raw["ok"]
        assert raw["failure"]["category"] == "technical_safe"
        assert raw["failure"]["code"] == "check_dice_failure"
        assert raw["failure"]["rolled_back"] is True
        assert not ctx.events

    play(settings, campaign_id, [], check)
