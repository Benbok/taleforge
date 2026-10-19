"""Мастер не пишет, что стражник съел ягоды, если use_item не прошёл: плейтест 19.10, хиты не менялись."""

from app.agents import intent as intents
from app.agents.master.continuity import unconfirmed_item_use

BERRIES = ["Добрая ягода", "Длинный меч"]
TEXT = (
    "Пупкинатор участливо смотрит на раненого стражника. Стражник косится на охапку лесных даров, "
    "но послушно отправляет в рот пару ягод, чувствуя тепло. В камерах тихо."
)


def test_consumption_without_a_successful_tool_is_flagged():
    assert unconfirmed_item_use(TEXT, BERRIES, []) == [
        "Стражник косится на охапку лесных даров, но послушно отправляет в рот пару ягод, чувствуя тепло."
    ]
    failed = [{"tool": "use_item", "result": {"ok": False}}]
    assert unconfirmed_item_use(TEXT, BERRIES, failed)


def test_successful_use_item_confirms_the_description():
    done = [{"tool": "use_item", "result": {"ok": True}}]
    assert unconfirmed_item_use(TEXT, BERRIES, done) == []


def test_unrelated_prose_is_not_flagged():
    assert unconfirmed_item_use("Стражник съел бы целого быка. Гоблин жуёт сухарь.", BERRIES, []) == []
    assert unconfirmed_item_use("Герой берёт ягоду и кладёт её в карман.", BERRIES, []) == []


def test_marked_up_names_are_read_as_plain_text():
    text = "[[en_1|Стражник]] съедает три ягоды."
    assert unconfirmed_item_use(text, BERRIES, [])


def test_feeding_an_npc_is_routed_straight_to_use_item():
    it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "use_item", "target_id": "en_guard", "instrument_id": "inv_berry"}],
    }
    assert intents.routable_tool_call(it) == (
        "use_item",
        {"character_id": "ch1", "inventory_id": "inv_berry", "target_id": "en_guard"},
    )


def test_parser_is_told_that_ordering_an_npc_to_eat_is_use_item():
    assert "use_item" in intents.PARSER_SYSTEM and "велит, просит или заставляет NPC съесть" in intents.PARSER_SYSTEM
