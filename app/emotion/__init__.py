from app.emotion.analyzers import (
    PERSONAS,
    HybridAnalyzer,
    LLMAnalyzer,
    RuleBasedAnalyzer,
)
from app.emotion.injector import SystemPromptInjector
from app.emotion.schemas import EmotionState, GMPersona, PlayerActionContext
from app.emotion.state_manager import InMemoryStateManager


class EmotionEngine:
    """
    Единая точка входа для эмоционального движка Мастера.
    Инкапсулирует анализаторы, менеджер состояния и генератор инструкций.
    """

    def __init__(
        self,
        llm_client=None,
        persona_id: str = "tired_mentor",
        model: str = "",
    ):
        self.persona_id = persona_id
        self.persona = PERSONAS.get(persona_id, PERSONAS["tired_mentor"])
        self.analyzer = HybridAnalyzer(llm_client=llm_client, persona_id=persona_id, model=model)
        self.state = InMemoryStateManager()
        self.injector = SystemPromptInjector()

    async def process(self, session_id: str, context: PlayerActionContext) -> str:
        """
        Главный пайплайн:
        1. Анализирует действие игрока (эвристика + LLM)
        2. Обновляет накопленные эмоции в сессии
        3. Формирует строку инструкции для системного промпта
        """
        delta = await self.analyzer.analyze(context)
        new_state = await self.state.update_state(session_id, delta)
        return self.injector.inject(new_state)

    async def get_state(self, session_id: str) -> EmotionState:
        """Получить текущее состояние эмоций сессии."""
        return await self.state.get_state(session_id)

    async def decay(self, session_id: str) -> EmotionState:
        """
        Применить затухание эмоций согласно профилю текущего характера Мастера.
        """
        return await self.state.apply_decay(session_id, self.persona.decay_rates)


__all__ = [
    "EmotionEngine",
    "EmotionState",
    "GMPersona",
    "PlayerActionContext",
    "PERSONAS",
    "HybridAnalyzer",
    "RuleBasedAnalyzer",
    "LLMAnalyzer",
    "InMemoryStateManager",
    "SystemPromptInjector",
]
