"""Public narration follows applied events even when generated prose is unusable."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.master.narration import NarrationMixin
from app.db.models import Event


class Narrator(NarrationMixin):
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []

    async def _ask(self, *args):
        self.requests.append(args[6])
        return SimpleNamespace(text=next(self.replies))


@pytest.fixture
def narration_context(monkeypatch):
    import app.agents.master.narration as module

    hero = SimpleNamespace(id="ch_hero", name="Бран", seat_id="seat_player")
    world = SimpleNamespace(
        characters={hero.id: hero},
        entities={},
        catalog=None,
        scene_table=lambda: "Бран в камере",
        in_scene_entities=lambda: [],
    )
    monkeypatch.setattr(module.combat, "public_turn", lambda _: None)
    monkeypatch.setattr(module, "effect_names", lambda _: {})
    monkeypatch.setattr(module, "_narration_length", lambda *_: "два предложения")
    monkeypatch.setattr(module, "_check_only", lambda *_: False)
    return SimpleNamespace(world=world, events=[])


def narrate(ctx, replies, attempts=None):
    narrator = Narrator(replies)
    campaign = SimpleNamespace(id="campaign", seats=[SimpleNamespace(id="seat_player", occupant_type="human")])
    text, audit = asyncio.run(
        narrator._narrate(
            [],
            None,
            campaign,
            "master",
            "turn",
            "Мастер",
            "",
            "Превращаюсь в мышь",
            ctx,
            tool_attempts=attempts,
        )
    )
    return text, audit, narrator


def found_item():
    return Event(
        tool="keep_found_item",
        hidden=False,
        target_id="ch_hero",
        payload={"result": {"character": "Бран", "item": "Медная монета", "qty": 1, "inventory_id": "inv_private"}},
    )


def test_cancelled_action_cannot_be_narrated_as_success(narration_context):
    narration_context.events = [
        Event(
            tool="cancel_action",
            hidden=False,
            target_id="ch_hero",
            payload={
                "reason": "мастер не обработал действие",
                "result": {"character": "Бран", "cancelled": "мастер не обработал действие"},
            },
        )
    ]
    text, audit, narrator = narrate(narration_context, ["Бран превращается в мышь и выходит из камеры."])
    assert "превращается" not in text
    assert "не выполнено" in text
    assert audit["cancel_fallback"]
    prompt = narrator.requests[0][-1]["content"]
    assert "Обязательные исходы действий" in prompt
    assert "мастер не обработал действие" in prompt


def test_empty_narration_retries_once_before_public_factual_fallback(narration_context):
    narration_context.events = [found_item()]
    text, audit, narrator = narrate(narration_context, ["  ", ""])
    assert len(narrator.requests) == 2
    assert "Медная монета" in text
    assert "inv_private" not in text
    assert text != "…"
    assert audit["empty_fallback"]


def test_empty_narration_retry_can_supply_valid_prose(narration_context):
    text, audit, narrator = narrate(narration_context, ["", "В камере тихо."])
    assert text == "В камере тихо."
    assert len(narrator.requests) == 2
    assert audit["empty_retry"]


@pytest.mark.parametrize("tool", ["resolve_attack", "enter_room"])
def test_failed_action_keeps_other_applied_results_without_secret_errors(narration_context, tool):
    narration_context.events = [found_item(), Event(tool="learn_fact", hidden=True, payload={"fact": "secret plot"})]
    text, audit, _ = narrate(
        narration_context, ["Всё получилось."], [{"tool": tool, "result": {"ok": False, "error": "secret plot"}}]
    )
    assert "Медная монета" in text
    assert "secret" not in text
    assert "inv_private" not in text
    assert "не состоял" in text


def test_blocked_item_markup_keeps_other_applied_results(narration_context):
    narration_context.events = [found_item()]
    text, audit, _ = narrate(narration_context, ["Вы нашли [[item_fake|Серебряный ключ]]."] * 2)
    assert "Серебряный ключ" not in text
    assert "Медная монета" in text
    assert audit["blocked_refs"] == ["item_fake"]


def test_repeated_bare_unregistered_item_markup_is_blocked(narration_context):
    text, audit, _ = narrate(narration_context, ["Вы получили [[Серебряный ключ]]."] * 2)
    assert "Серебряный ключ" not in text
    assert audit["blocked_bare_names"] == ["Серебряный ключ"]


def test_fallback_preserves_public_fact_but_hides_other_group_fact(narration_context):
    from app.agents.master.outcomes import public_factual_fallback

    narration_context.world.crew = {"ch_hero"}
    narration_context.events = [
        Event(tool="learn_fact", hidden=False, actor_id="ch_hero", payload={"fact": "Из коридора слышны шаги."}),
        Event(tool="learn_fact", hidden=False, actor_id="ch_other", payload={"fact": "Чужая тайна."}),
    ]
    text = public_factual_fallback(narration_context)
    assert "Из коридора слышны шаги" in text
    assert "Чужая тайна" not in text


def test_cancel_fallback_keeps_spoiler_name_excluded(narration_context):
    narration_context.events = [
        Event(tool="keep_found_item", hidden=False, payload={"result": {"item": "Valar", "qty": 1}}),
        Event(tool="cancel_action", hidden=False, target_id="ch_hero", payload={"reason": "not processed"}),
    ]
    text, audit, _ = narrate(narration_context, ["[[ant_valar|Valar]] speaks.", "Valar speaks."])
    assert "Valar" not in text
    assert "не выполнено" in text


def test_fallback_does_not_publish_private_fact_to_new_listener(narration_context):
    narration_context.world.crew = {"ch_hero"}
    narration_context.narration_viewer_ids = {"ch_hero", "ch_new_listener"}
    narration_context.events = [
        Event(tool="learn_fact", hidden=False, actor_id="ch_hero", payload={"fact": "Тайна нового союзника."}),
        Event(tool="cancel_action", hidden=False, target_id="ch_hero", payload={"reason": "not processed"}),
    ]
    text, _, _ = narrate(narration_context, ["Мастер описывает сцену."])
    assert "Тайна нового союзника" not in text


@pytest.mark.parametrize("markup", ["[[inv_coin|Медная монета]]", "[[Медная монета]]"])
def test_registered_inventory_item_is_allowed_in_narration(narration_context, markup):
    narration_context.world.inventory = {"ch_hero": [SimpleNamespace(id="inv_coin", display_name="Медная монета")]}
    narration_context.world.item_name = lambda item: item.display_name
    text, audit, narrator = narrate(narration_context, [f"В инвентаре есть {markup}."] * 2)
    assert "Медная монета" in text
    assert "[[inv_coin|" not in text
    assert not audit["regenerated"]
    assert len(narrator.requests) == 1


def test_partly_handled_request_keeps_narration_and_notes_the_rest(narration_context):
    """Плейтест вдвоём: «приоткрываю дверь и подглядываю» разобрано на две части, мастер закрыл одну
    (auto_success), вторая отменена автоматически. Повествование о применённом не заменяется сухой сводкой."""
    narration_context.events = [
        Event(
            tool="auto_success",
            hidden=False,
            actor_id="ch_hero",
            target_id="ch_hero",
            payload={"result": {"character": "Бран", "success": "заглянул в караульную"}},
        ),
        Event(
            tool="cancel_action",
            hidden=False,
            target_id="ch_hero",
            payload={
                "reason": "мастер не обработал действие",
                "result": {"character": "Бран", "cancelled": "мастер не обработал действие"},
            },
        ),
    ]
    prose = "Сквозь щель видна разгромленная караульная и раненый стражник у стены."
    text, audit, _ = narrate(narration_context, [prose])
    assert prose in text
    assert "часть заявки" in text and "действие выполнено" not in text
    assert not audit.get("cancel_fallback") and audit.get("partial_cancel")
