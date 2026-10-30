import json

from app.agents.master.exploration import SYSTEM
from app.agents.master.prompting.messages import decide_messages, request_size
from app.rules.universal.exploration import exploration_capabilities


def test_decide_messages_match_the_previous_request():
    context = {"source": "иду", "scene": {}}
    assert decide_messages(context, "x") == [
        {"role": "system", "content": SYSTEM},
        {
            "role": "user",
            "content": json.dumps(
                {**context, "capabilities": exploration_capabilities(), "repair": "x"}, ensure_ascii=False
            ),
        },
    ]
    assert context == {"source": "иду", "scene": {}}


def test_request_size_counts_every_context_key():
    messages = decide_messages({"source": "иду", "scene": {}})
    counts = request_size(messages, {"type": "object"})
    assert {"context.source", "context.scene", "context.capabilities", "context.repair"} <= counts.keys()
    assert sum(v for k, v in counts.items() if k != "total") == counts["total"]
    assert counts["system"] == len(SYSTEM)
    assert counts["total"] == sum(len(message["content"]) for message in messages) + len(
        json.dumps({"type": "object"}, ensure_ascii=False)
    )
