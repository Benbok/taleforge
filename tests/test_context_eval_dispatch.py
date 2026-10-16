"""Evaluator-only receiver checks; activated by the isolated child driver."""
# ruff: noqa: F811 -- shared integration fixtures

import os
from collections import Counter

import pytest

from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401


@pytest.mark.parametrize("scenario", ["attack", "native"])
def test_received_inputs_match_measurements(request, game_client, admin_g, llm, dice, settings, monkeypatch, scenario):
    if not os.environ.get("TALEFORGE_EVAL_RESULT"):
        pytest.skip("isolated evaluator child only")
    from app.core.llm_diagnostics import message_sizes
    from tests.test_turn_efficiency import test_paired_scripted_turn
    from tools.context_eval_variants import package_for_variant
    from tools.eval_turn_efficiency import _RESULTS

    row = _RESULTS[request.node.nodeid]
    variant = row["effective_config"]["selected_variant"]
    requests = []
    original = llm.complete

    async def receiver(messages, **options):
        requests.append(package_for_variant(variant, {"messages": messages, "tools": options.get("tools")}))
        return await original(messages, **options)

    monkeypatch.setattr(llm, "complete", receiver)
    test_paired_scripted_turn(game_client, admin_g, llm, dice, settings, monkeypatch, scenario)
    received = Counter(package_for_variant(variant, packet)["digest"] for packet in requests)
    measurements = row["measured_inputs"] + row["parse_inputs"]
    measured = Counter(packet["digest"] for packet in measurements)
    assert measured and not (measured - received), [
        packet for packet in measurements if packet["digest"] not in received
    ]
    assert row["parse_inputs"]
    actual = {
        package_for_variant(variant, packet)["digest"]: message_sizes(packet["messages"], packet["tools"] or [])
        for packet in requests
    }
    assert all(packet["message_sizes"] == actual[packet["digest"]] for packet in measurements)
