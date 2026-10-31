"""What the writer is told when a check or an attack leaves nothing else to say."""

from types import SimpleNamespace

from app.agents.master.exploration import FLOOR_NOTE
from app.core.universal.exploration_resolution import _outcome_hint


def _action(resolution, outcomes=None):
    return SimpleNamespace(resolution=resolution, check_outcomes=outcomes, difficulty=12)


def _result(success, critical_failure=False):
    return SimpleNamespace(success=success, critical=False, critical_failure=critical_failure)


def test_missed_attack_says_the_target_is_unharmed():
    text = _outcome_hint(_action("attack"), _result(False))
    assert "не попал" in text and "не пострадал" in text
    assert "задуманные эффекты" not in text  # that wording reads as the actor's own setback


def test_fumbled_attack_is_the_attackers_miss_not_the_targets_wound():
    text = _outcome_hint(_action("attack"), _result(False, critical_failure=True))
    assert "не пострадал" in text


def test_failed_check_keeps_its_plain_statement():
    assert _outcome_hint(_action("check"), _result(False)) == "Попытка не удалась; задуманные эффекты не возникли."
    assert _outcome_hint(_action("check"), _result(True)).startswith("Проверка успешна")


def test_floor_note_is_a_neutral_fact_not_a_validator_message():
    assert "req_" not in FLOOR_NOTE and "effects" not in FLOOR_NOTE


def _talk(kinds, resolution="check", difficulty=12):
    return SimpleNamespace(
        difficulty=difficulty,
        resolution=resolution,
        operations=[SimpleNamespace(kind=k) for k in kinds],
        check_outcomes=SimpleNamespace(
            success="s", failure="f", critical_success="cs", critical_failure="Торвин ссадил ладонь"
        ),
    )


def test_a_failed_word_never_tells_of_a_wound():
    from app.core.universal.exploration_resolution import _told_outcome, is_talk_only

    assert is_talk_only(_talk(["speak"])) and is_talk_only(_talk(["speak", "wait"]))
    assert not is_talk_only(_talk(["observe"]))  # a look may still go wrong, as before
    assert not is_talk_only(_talk(["speak", "move"]))
    assert _told_outcome(_talk(["speak"]), _result(False, critical_failure=True)) == "f"  # no invented injury
    assert _told_outcome(_talk(["move"]), _result(False, critical_failure=True)) == "Торвин ссадил ладонь"


def test_the_deed_the_engine_shapes_itself_still_says_what_was_attempted():
    from app.agents.master.exploration import plain_outcomes

    told = plain_outcomes("Отпрыгнуть от стучальщика и спрятаться в зазоре")
    assert "спрятаться в зазоре" in told.failure and "спрятаться в зазоре" in told.success
    assert told.failure != told.success
    assert len(plain_outcomes("а" * 5000).failure) < 600  # a long text is cut, never rejected


def test_a_difficulty_written_as_digits_is_still_a_difficulty():
    """Found in play: a repair attempt that was otherwise right was thrown away over "difficulty": "10"."""
    import pytest
    from pydantic import ValidationError

    from app.rules.universal.exploration import EffectIntentV2, IntentV2

    def intent(difficulty):
        return IntentV2(source="mundane", difficulty=difficulty, effects=[EffectIntentV2(kind="observe")])

    assert intent("10").difficulty == 10 and intent(10).difficulty == 10
    for bad in ("10.5", "dix", 10.5, True, "0"):
        with pytest.raises(ValidationError):
            intent(bad)
