import asyncio
from types import SimpleNamespace

from app.emotion import (
    EmotionEngine,
    EmotionState,
    InMemoryStateManager,
    LLMAnalyzer,
    PlayerActionContext,
    RuleBasedAnalyzer,
    SystemPromptInjector,
)


class MockLLM:
    """Мок LLM-клиента для предсказуемых тестов."""

    def __init__(self, reply_text: str = "", raise_error: bool = False):
        self.reply_text = reply_text
        self.raise_error = raise_error
        self.calls = []

    async def complete(self, messages, *, model, **kwargs):
        self.calls.append({"messages": messages, "model": model, "kwargs": kwargs})
        if self.raise_error:
            raise RuntimeError("API Timeout / Network error")
        return SimpleNamespace(text=self.reply_text)


# ===================== StateManager Tests =====================


def test_state_initial_neutral():
    mgr = InMemoryStateManager()
    state = asyncio.run(mgr.get_state("s1"))
    assert state.anger == 0.0
    assert state.joy == 0.0
    assert state.suspicion == 0.0
    assert state.boredom == 0.0


def test_state_update_clamping():
    mgr = InMemoryStateManager()
    # Превышение 10.0
    s1 = asyncio.run(mgr.update_state("s1", EmotionState(anger=12.0, joy=5.0)))
    assert s1.anger == 10.0
    assert s1.joy == 5.0

    # Накопление
    s2 = asyncio.run(mgr.update_state("s1", EmotionState(joy=6.0)))
    assert s2.joy == 10.0  # 5 + 6 clamped to 10


def test_state_decay_custom_rates():
    mgr = InMemoryStateManager()
    asyncio.run(mgr.update_state("s1", EmotionState(anger=2.0, joy=1.0, suspicion=0.2)))

    # Custom rates: anger -0.5, joy -1.5, suspicion -0.5
    rates = EmotionState(anger=0.5, joy=1.5, suspicion=0.5, boredom=0.0)
    after = asyncio.run(mgr.apply_decay("s1", rates=rates))

    assert after.anger == 1.5
    assert after.joy == 0.0  # Не уходит ниже нуля
    assert after.suspicion == 0.0


# ===================== RuleBasedAnalyzer Tests =====================


def test_rule_analyzer_crit_fail_and_success():
    analyzer = RuleBasedAnalyzer(persona_id="sadist")

    # Садист радуется провалу игроков
    ctx_fail = PlayerActionContext(player_id="p1", character_name="Hero", action_text="Бегу", is_critical_failure=True)
    delta_fail = asyncio.run(analyzer.analyze(ctx_fail))
    assert delta_fail.joy == 3.0
    assert delta_fail.anger == 0.0

    # Садист злится на успех
    ctx_succ = PlayerActionContext(player_id="p1", character_name="Hero", action_text="Бью", is_critical_success=True)
    delta_succ = asyncio.run(analyzer.analyze(ctx_succ))
    assert delta_succ.anger == 2.0
    assert delta_succ.joy == 0.0


def test_rule_analyzer_tags():
    analyzer = RuleBasedAnalyzer(persona_id="tired_mentor")
    ctx = PlayerActionContext(
        player_id="p1",
        character_name="Rogue",
        action_text="Бью союзника",
        tags=["attack_friendly", "steal"],
    )
    delta = asyncio.run(analyzer.analyze(ctx))
    # attack_friendly: anger=3, suspicion=1
    # steal: suspicion=2, boredom=1
    assert delta.anger == 3.0
    assert delta.suspicion == 3.0
    assert delta.boredom == 1.0


# ===================== SystemPromptInjector Tests =====================


def test_injector_neutral():
    injector = SystemPromptInjector()
    # Все эмоции ниже 3.0
    res = injector.inject(EmotionState(anger=2.9, joy=1.0))
    assert res == ""


def test_injector_single_tiers():
    injector = SystemPromptInjector()

    # 1. Легкий уровень (3.0 - 4.9)
    res_light = injector.inject(EmotionState(anger=3.5))
    assert "слегка недоволен" in res_light

    # 2. Умеренный уровень (5.0 - 7.9)
    res_mod = injector.inject(EmotionState(anger=6.0))
    assert "раздражен" in res_mod

    # 3. Сильный уровень (8.0 - 10.0)
    res_strong = injector.inject(EmotionState(anger=9.0))
    assert "в ярости" in res_strong


def test_injector_conflict_resolution():
    injector = SystemPromptInjector()

    # Конфликт: Гнев 8.0 + Радость 8.0 -> Злорадство
    res_combo = injector.inject(EmotionState(anger=8.0, joy=8.0))
    assert "злорадствуешь" in res_combo
    assert "в ярости" not in res_combo  # Не смешивает противоречивые директивы

    # Конфликт: Гнев 6.0 + Подозрительность 6.0 -> Враждебность
    res_hostile = injector.inject(EmotionState(anger=6.0, suspicion=6.0))
    assert "враждебен и подозрителен" in res_hostile


# ===================== LLMAnalyzer Tests =====================


def test_llm_analyzer_success():
    mock = MockLLM('{"anger": 0.0, "joy": 3.0, "suspicion": 0.0, "boredom": 0.0}')
    analyzer = LLMAnalyzer(llm_client=mock, persona_id="tired_mentor", model="gemini-flash")

    ctx = PlayerActionContext(player_id="p1", character_name="Mage", action_text="Применяю изящную тактику")
    delta = asyncio.run(analyzer.analyze(ctx))
    assert delta.joy == 3.0
    assert len(mock.calls) == 1
    assert mock.calls[0]["model"] == "gemini-flash"


def test_llm_analyzer_markdown_json_and_clamping():
    # Ответ с markdown ```json и числом за пределами 4.0
    raw_markdown = """```json
    {
        "anger": 99.0,
        "joy": 2.0,
        "suspicion": -5.0,
        "boredom": 1.0
    }
    ```"""
    mock = MockLLM(raw_markdown)
    analyzer = LLMAnalyzer(llm_client=mock, persona_id="tired_mentor")

    ctx = PlayerActionContext(player_id="p1", character_name="Bard", action_text="Шучу")
    delta = asyncio.run(analyzer.analyze(ctx))

    assert delta.anger == 4.0  # Clamped к 4.0
    assert delta.joy == 2.0
    assert delta.suspicion == 0.0  # Clamped к 0.0
    assert delta.boredom == 1.0


def test_llm_analyzer_error_tolerance():
    # Симуляция сбоя сети / таймаута
    mock = MockLLM(raise_error=True)
    analyzer = LLMAnalyzer(llm_client=mock, persona_id="tired_mentor")

    ctx = PlayerActionContext(player_id="p1", character_name="Fighter", action_text="Атакую")
    delta = asyncio.run(analyzer.analyze(ctx))

    # Ошибка не крашит процесс, возвращаются нули
    assert delta.anger == 0.0
    assert delta.joy == 0.0


# ===================== EmotionEngine Facade Tests =====================


def test_emotion_engine_pipeline():
    mock = MockLLM('{"anger": 2.0, "joy": 0.0, "suspicion": 1.0, "boredom": 0.0}')
    engine = EmotionEngine(llm_client=mock, persona_id="tired_mentor", model="gemini-flash")

    # 1. Первое действие: атака союзника (тег) + реакция LLM
    ctx1 = PlayerActionContext(
        player_id="p1",
        character_name="Barbarian",
        action_text="Бью трактирщика ни за что",
        tags=["attack_friendly"],
    )
    prompt1 = asyncio.run(engine.process("session_abc", ctx1))

    # attack_friendly дает anger=3.0, suspicion=1.0
    # LLM дает anger=2.0, suspicion=1.0
    # Итого: anger=5.0, suspicion=2.0 -> anger >= 5.0 (умеренный уровень)
    assert "раздражен" in prompt1

    state1 = asyncio.run(engine.get_state("session_abc"))
    assert state1.anger == 5.0
    assert state1.suspicion == 2.0

    # 2. Вызываем затухание (конец раунда)
    state2 = asyncio.run(engine.decay("session_abc"))
    # Для tired_mentor: anger остывает на 0.5 (стало 4.5), suspicion на 0.3 (стало 1.7)
    assert state2.anger == 4.5
    assert state2.suspicion == 1.7
