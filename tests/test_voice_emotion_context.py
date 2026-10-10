"""Контекст короткой реплики: характер кампании и публичные результаты хода."""

from types import SimpleNamespace

from app.agents.master.helpers import _render_results
from app.emotion import EmotionState, LLMAnalyzer, PlayerActionContext, SystemPromptInjector


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
