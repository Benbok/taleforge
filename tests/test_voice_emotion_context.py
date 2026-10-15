# ruff: noqa: F811 -- shared integration fixtures
"""Контекст короткой реплики: характер кампании и публичные результаты хода."""

import asyncio
from types import SimpleNamespace

import pytest

from app.agents.master.helpers import _render_results
from app.agents.master.narration import NarrationMixin
from app.emotion import EmotionState, LLMAnalyzer, PlayerActionContext, SystemPromptInjector
from app.emotion import game as mood
from tests.test_tools import game, play  # noqa: F401


@pytest.mark.parametrize(
    "temper",
    [
        "sadist",
        "tired_mentor",
        "kind_mentor",
        "sarcastic_skeptic",
        "enthusiastic_storyteller",
        "daring_gambler",
        "calm_arbiter",
        "grim_fatalist",
        "dark_comedian",
        None,
        "unknown",
    ],
)
def test_voice_line_uses_selected_temper_even_without_mood(temper):
    requests = []

    class Narrator(NarrationMixin):
        async def _ask(self, calls, cfg, cid, seat_id, turn_id, purpose, messages, tools, **kwargs):
            requests.append(messages)
            return SimpleNamespace(text="Ну что ж, попытка была смелой.")

    cfg = SimpleNamespace(settings={"emotion_persona": temper}, persona="Классический мастер")
    asyncio.run(
        Narrator()._voice_line(
            [],
            cfg,
            SimpleNamespace(id="campaign"),
            "seat",
            "turn",
            "Классический мастер",
            SimpleNamespace(events=[]),
            [],
            news="Пытаюсь перепрыгнуть ручей",
        )
    )
    prompt = requests[0][1]["content"]
    selected = mood.persona_of(temper)
    if temper and temper != "unknown":
        from app.emotion.analyzers import PERSONAS

        assert temper in PERSONAS
    assert selected.name in prompt
    assert selected.description in prompt
    assert "Пытаюсь перепрыгнуть ручей" in prompt
    assert "Текущее настроение" in prompt


def test_emotion_analysis_uses_campaign_persona():
    analyzer = LLMAnalyzer(persona_description="Тёплый трактирщик, без насмешек над неудачами.")
    messages = analyzer.messages(PlayerActionContext(player_id="p1", character_name="Бран", action_text="Прыгаю"))
    assert "Тёплый трактирщик, без насмешек над неудачами." in messages[1]["content"]


def test_voice_results_exclude_hidden_rolls_and_plot():
    def event(tool, text, hidden=False):
        return SimpleNamespace(tool=tool, payload={"result": {"text": text}}, hidden=hidden)

    ctx = SimpleNamespace(
        events=[
            event("auto_success", "Герой перепрыгнул"),
            event("roll_check", "Скрытая проверка", hidden=True),
            event("threat_clock", "Тайный план злодея"),
        ]
    )
    public = _render_results(ctx, public_only=True)
    assert "Герой перепрыгнул" in public
    assert "Скрытая проверка" not in public
    assert "Тайный план злодея" not in public
    # Основной рассказчик по-прежнему получает скрытые результаты с пометками.
    assert "Скрытая проверка" in _render_results(ctx)


def test_mood_only_controls_delivery():
    prompt = SystemPromptInjector().inject(EmotionState(anger=8, suspicion=8))
    assert "Персонажи мира видят в героях прямую угрозу" not in prompt
    assert "требуй строгих проверок" not in prompt
    assert "не меняет" in prompt
    assert "выбранный характер" in prompt


def test_compact_voice_keeps_persona_mood_public_results_and_small_limit(game):
    from app.db.models import AgentConfig, CampaignSecret, Event

    settings, cid, hero = game
    captured = {}

    class Narrator(NarrationMixin):
        async def _ask(self, *args, **options):
            captured.update(messages=args[6], **options)
            return SimpleNamespace(text="«Отлично!»")

    async def check(ctx):
        ctx.campaign.settings = {**ctx.campaign.settings, "llm_optimization": {"compact_voice": True}}
        secret = await ctx.session.get(CampaignSecret, cid)
        secret.setting = {"hidden": "VOICE_SECRET"}
        ctx.events = [
            Event(tool="auto_success", hidden=False, payload={"result": {"text": "PUBLIC_RESULT"}}),
            Event(tool="roll_check", hidden=True, payload={"result": {"text": "PRIVATE_RESULT"}}),
        ]
        cfg = AgentConfig(
            persona="VOICE_STYLE", settings={"emotion_persona": "sadist", "voice_line_model": "gemini/gemini-2.5-flash"}
        )
        text = await Narrator()._voice_line(
            [], cfg, ctx.campaign, "s", None, "PRIVATE_SYSTEM", ctx, ["PRIVATE_COMBAT_NOTE"], news="PLAYER_NEWS"
        )
        prompt = str(captured["messages"])
        assert all(item in prompt for item in ("VOICE_STYLE", "PUBLIC_RESULT", "PLAYER_NEWS", "Текущее настроение"))
        assert all(
            item not in prompt for item in ("VOICE_SECRET", "PRIVATE_RESULT", "PRIVATE_SYSTEM", "PRIVATE_COMBAT_NOTE")
        )
        assert captured["max_tokens"] == 512 and captured["thinking"] is False
        assert sum(len(m["content"]) for m in captured["messages"]) / 4 <= 2000
        assert text == "Отлично!"

    play(settings, cid, [], check)
