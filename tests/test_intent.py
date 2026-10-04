# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Парсер намерений: отказы, уточнения, лимит действий в бою, пропавший предмет, маршрутизатор атаки."""

from sqlalchemy import select

from app.agents import intent as intents
from app.db.models import Campaign, InventoryItem, LlmCall, MasterTurn, Message
from app.tools.runtime import open_context
from tests.game import QueueDice, ok, party, run
from tests.test_combat import _fight, scene  # noqa: F401
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def intent(*actions, confidence=0.95, problem="none", question=None):
    return {
        "tool_calls": [
            (
                "submit_intent",
                {
                    "kind": "action",
                    "actions": list(actions),
                    "confidence": confidence,
                    "problem": problem,
                    "question": question,
                },
            )
        ]
    }


def send(client, head, cid, text):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": text}})
        e = ws.receive_json()
        while e["type"] not in ("message.rejected", "message.new"):
            e = ws.receive_json()
        return e


def goblin_in_melee(settings, cid, hero, *, fight=False):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice([]), turn_id=None, seat_id=None)
        if fight:
            gob = await _fight(ctx, hero, "creature.goblin", zone="melee", first="hero")
            from app.core import combat

            combat._begin_hero_turn(ctx, ctx.world.characters[hero])
        else:
            from app.tools.registry import execute

            r = await execute(
                ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "melee"}
            )
            gob = r["result"]["spawned"][0]["id"]
        sword = (
            await s.scalars(
                select(InventoryItem).where(
                    InventoryItem.character_id == hero, InventoryItem.item_template_id == "item.longsword"
                )
            )
        ).first()
        await s.commit()
        return gob, sword.id

    return run(settings, go)


def test_rejects_offtopic_and_unclear(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [intent(confidence=0.9, problem="offtopic")]
    e = send(game_client, p1, c["id"], "а кто смотрел вчера футбол?")
    assert e["type"] == "message.new" and e["payload"]["kind"] == "ooc"  # оффтоп сам уходит во внеигровой чат
    llm.replies += [intent({"verb": "custom"}, confidence=0.3, question="Кого именно вы хотите позвать?")]
    e = send(game_client, p1, c["id"], "зову его")
    assert e["payload"]["reason"] == "Кого именно вы хотите позвать?"
    llm.replies += [intent({"verb": "attack"}, problem="other_character")]
    e = send(game_client, p1, c["id"], "Гимли бьёт орка топором")
    assert "чужого героя" in e["payload"]["reason"]
    assert rows(settings, Message, Message.kind == "action") == []
    assert [x.purpose for x in rows(settings, LlmCall)] == ["parse"] * 3


def send_auto(client, head, cid, text, **extra):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"text": text, **extra}})
        e = ws.receive_json()
        while e["type"] not in ("message.rejected", "message.new"):
            e = ws.receive_json()
        return e


def test_native_chat_kind_from_parser(game_client, admin_g, llm, settings):
    """Игрок не выбирает тип реплики: речь, действие и оффтоп различает парсер, шёпот — отдельный флаг."""
    c, (p1,), hero = party(game_client, admin_g)
    speech = {"tool_calls": [("submit_intent", {"kind": "speech", "speech": "Кто здесь?", "confidence": 0.9})]}
    llm.replies += [speech, DONE, {"text": "Тишина."}]
    e = send_auto(game_client, p1, c["id"], "— Кто здесь? — шепчу в темноту")
    assert e["payload"]["kind"] == "speech"
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    llm.replies += [intent({"verb": "search"}), DONE, {"text": "Пыль и паутина."}]
    e = send_auto(game_client, p1, c["id"], "Обыскиваю сундук")
    assert e["payload"]["kind"] == "action"
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert send_auto(game_client, p1, c["id"], "// перерыв 5 минут")["payload"]["kind"] == "ooc"
    llm.replies += [DONE, {"text": "Мастер кивает."}]
    e = send_auto(game_client, p1, c["id"], "Прячу кольцо в сапог", kind="whisper")
    assert e["payload"]["kind"] == "whisper" and e["payload"]["whisper"]
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    # мастер-человек пишет повествование без выбора типа
    from tests.test_api import make_campaign

    c2 = make_campaign(game_client, admin_g, master={"type": "owner"})
    ok(game_client.post(f"/api/campaigns/{c2['id']}/session/start", headers=admin_g))
    assert send_auto(game_client, admin_g, c2["id"], "Ветер стихает.")["payload"]["kind"] == "narration"


def test_router_attack_and_intent_saved(game_client, admin_g, llm, dice, settings):
    c, (p1,), hero = party(game_client, admin_g)
    gob, sword = goblin_in_melee(settings, c["id"], hero["id"])
    llm.replies += [
        intent({"verb": "attack", "target_id": gob, "instrument_id": sword, "manner": "сверху"}),
        DONE,
        {"text": f"[[{hero['id']}|Бран]] рубит гоблина."},
    ]
    dice += [15, 8]
    n = act(game_client, p1, c["id"], "рублю гоблина мечом сверху")
    assert n["kind"] == "narration"
    (turn,) = rows(settings, MasterTurn, MasterTurn.status == "done")
    routed = [x for x in turn.trace["calls"] if x.get("routed")]
    assert routed and routed[0]["result"]["ok"], turn.trace
    decide = next(r for r in llm.requests if r["tools"] and r["tools"][0]["function"]["name"] != "submit_intent")
    prompt = decide["messages"][1]["content"]
    assert "намерение (разбор парсера): attack" in prompt and "уже выполнен сервером" in prompt
    (msg,) = rows(settings, Message, Message.kind == "action")
    assert msg.intent["character_id"] == hero["id"] and msg.intent["actions"][0]["target_id"] == gob


def test_combat_limit_and_missing_item(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    gob, _ = goblin_in_melee(settings, c["id"], hero["id"], fight=True)
    llm.replies += [
        intent(
            {"verb": "attack", "target_id": gob, "instrument_id": "inv_нет_такого"},
            {"verb": "move", "zone": "near"},
            {"verb": "use_item"},
        ),
        DONE,
        {"text": "Рука нащупывает пустые ножны."},
    ]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": "бью, отбегаю и пью зелье"}})
        notice = next_of(ws, "message.notice")["payload"]["text"]
    assert "атака, перемещение" in notice
    (msg,) = rows(settings, Message, Message.kind == "action")
    assert [a["verb"] for a in msg.intent["actions"]] == ["attack", "move"]
    assert msg.intent["actions"][0]["missing_item"]


def test_parser_garbage_passes_through(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [intent({"verb": "fly"}), DONE, DONE, {"text": "Ничего не происходит."}]
    n = act(game_client, p1, c["id"], "Лечу к луне")
    assert n["content"] == "Ничего не происходит."
    (msg,) = rows(settings, Message, Message.kind == "action")
    assert msg.intent is None


def test_describe_and_route_helpers():
    from app.agents.llm import parser_model_for

    assert parser_model_for("gemini", "gemini-2.5-flash") == "gemini/gemini-3.8-flash-lite"
    assert parser_model_for("claude", None) == "anthropic/claude-haiku-4-5"

    it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "attack", "target_id": "en1", "instrument_id": "inv1", "manner": ""}],
    }
    assert intents.routable_attack(it) == {"attacker_id": "ch1", "target_id": "en1", "attack": "inv1"}
    assert intents.routable_attack({**it, "confidence": 0.6}) is None
    assert "attack target_id=en1" in intents.describe(it)
    spec = intents.tool_spec({"target_id": ["en1"], "instrument_id": []})
    act_props = spec["function"]["parameters"]["properties"]["actions"]["items"]["properties"]
    assert act_props["target_id"]["anyOf"][0]["enum"] == ["en1"] and "$ref" not in str(spec)

    # routable_tool_call: use_item
    item_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "use_item", "instrument_id": "pot1", "manner": ""}],
    }
    assert intents.routable_tool_call(item_it) == ("use_item", {"character_id": "ch1", "inventory_id": "pot1"})

    # routable_tool_call: rest
    rest_short = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "rest", "manner": "короткий отдых"}],
    }
    assert intents.routable_tool_call(rest_short) == ("rest", {"character_ids": ["ch1"], "kind": "short"})
    rest_long = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "rest", "manner": "длинный отдых на ночь"}],
    }
    assert intents.routable_tool_call(rest_long) == ("rest", {"character_ids": ["ch1"], "kind": "long"})

    # routable_tool_call: skill checks
    hide_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "hide", "manner": "в тени"}],
    }
    assert intents.routable_tool_call(hide_it) == (
        "roll_check",
        {"character_id": "ch1", "stat": "stealth", "kind": "check", "difficulty": "dc.medium", "reason": "в тени"},
    )
    search_it = {
        "character_id": "ch1",
        "confidence": 0.9,
        "actions": [{"verb": "search", "skill": "investigation", "manner": "ищу тайник"}],
    }
    assert intents.routable_tool_call(search_it) == (
        "roll_check",
        {
            "character_id": "ch1",
            "stat": "investigation",
            "kind": "check",
            "difficulty": "dc.medium",
            "reason": "ищу тайник",
        },
    )


def test_litellm_prompt_caching_injection(monkeypatch):
    import litellm

    from app.agents.llm import LiteLLMClient

    captured_kwargs = {}

    async def mock_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        from unittest.mock import MagicMock

        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message = MagicMock(content="ok", tool_calls=[])
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return resp

    monkeypatch.setattr(litellm, "acompletion", mock_acompletion)

    client = LiteLLMClient()
    import asyncio

    # Для gemini с длинным system prompt добавляется cache_control
    long_sys = "Правила мира. " * 100
    msgs = [{"role": "system", "content": long_sys}, {"role": "user", "content": "Привет"}]
    asyncio.run(client.complete(msgs, model="gemini/gemini-2.5-flash"))
    sys_content = captured_kwargs["messages"][0]["content"]
    assert isinstance(sys_content, list)
    assert sys_content[0]["cache_control"] == {"type": "ephemeral"}

    # Для локальной модели — не трогаем (остаётся строкой)
    asyncio.run(client.complete(msgs, model="lm_studio/qwen2.5"))
    assert captured_kwargs["messages"][0]["content"] == long_sys
