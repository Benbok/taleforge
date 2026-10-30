from tests.eval.cases import EvalCase, Expect
from tests.eval.checks import check


def intent(kind="move", **kwargs):
    return {"source": "mundane", "resolution": "automatic", "effects": [{"kind": kind, **kwargs}]}


def test_move_requires_the_right_effect_and_destination():
    case = EvalCase("move", "station", "иду в зал", Expect(effect_kinds={"move"}, destination="hall"))
    assert check(case, intent(destination_id="hall")) == []
    assert any("move" in issue for issue in check(case, intent("observe")))
    assert check(case, intent(destination_id="wrong"))


def test_quotes_must_come_from_this_players_source():
    case = EvalCase("quote", "station", "осматриваюсь", Expect())
    raw = intent("observe")
    raw["requirements"] = [{"id": "r", "quote": "иду в зал", "effect": "observe"}]
    assert any("quote" in issue for issue in check(case, raw))


def test_question_requires_speech_and_recipient():
    case = EvalCase("speech", "station", "спрашиваю техника", Expect(effect_kinds={"speak"}, recipient=True))
    assert check(case, intent("observe"))
    assert check(case, intent("speak"))
    assert check(case, intent("speak", recipient_id="technician")) == []


def test_pure_speech_is_automatic():
    case = EvalCase("speech", "station", "привет", Expect(resolution="automatic"))
    raw = intent("speak")
    raw["resolution"] = "check"
    assert any("resolution" in issue for issue in check(case, raw))


def test_invalid_schema_is_a_failure_and_does_not_raise():
    assert check(EvalCase("bad", "station", "жду", Expect()), {"effects": []})
