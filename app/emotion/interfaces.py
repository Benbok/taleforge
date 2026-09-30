from abc import ABC, abstractmethod
from app.emotion.schemas import EmotionState, PlayerActionContext

class IEmotionAnalyzer(ABC):
    """Интерфейс для анализаторов действий (эвристика или LLM)."""
    
    @abstractmethod
    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        """Возвращает дельту эмоций (насколько нужно изменить текущие параметры)."""
        pass


class IStateManager(ABC):
    """Интерфейс для хранения и обновления эмоций."""
    
    @abstractmethod
    async def get_state(self, session_id: str) -> EmotionState:
        """Получить текущее состояние для конкретной игровой сессии."""
        pass

    @abstractmethod
    async def update_state(self, session_id: str, delta: EmotionState) -> EmotionState:
        """Применить дельту и вернуть обновленное состояние."""
        pass


class IEmotionInjector(ABC):
    """Интерфейс для конвертации состояния в системный промпт."""
    
    @abstractmethod
    def inject(self, state: EmotionState) -> str:
        """Генерирует текстовую инструкцию для Мастера на основе эмоций."""
        pass
