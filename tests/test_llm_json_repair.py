from app.agents.llm import _parse_args, repair_json

GLITCH = (
    '{"source": "mundane", "effects": [{"kind": "move", "destination_id": "en_1", "required_by": ["req_1"]}], '
    '"public_reason":: '
)


def test_stray_token_after_complete_fields_keeps_the_fields_before_it():
    args = _parse_args(GLITCH)
    assert args["effects"][0]["destination_id"] == "en_1" and "public_reason" not in args


def test_truncated_nested_output_is_closed():
    assert repair_json('{"a": [1, 2, {"b": "x"') == {"a": [1, 2, {"b": "x"}]}


def test_hopeless_text_is_still_reported_invalid():
    assert "__invalid_json__" in _parse_args("не json")
