from typing import Dict
from app.emotion.interfaces import IStateManager
from app.emotion.schemas import EmotionState

class InMemoryStateManager(IStateManager):
    """
    Простая in-memory реализация трекера состояния эмоций для сессий.
    В будущем может быть заменена на RedisStateManager.
    """
    def __init__(self):
        # Хранилище: session_id -> EmotionState
        self._states: Dict[str, EmotionState] = {}

    async def get_state(self, session_id: str) -> EmotionState:
        if session_id not in self._states:
            self._states[session_id] = EmotionState()
        return self._states[session_id]

    async def update_state(self, session_id: str, delta: EmotionState) -> EmotionState:
        current = await self.get_state(session_id)
        
        # Прибавляем дельту и жестко ограничиваем значения диапазоном [0.0, 10.0]
        new_state = EmotionState(
            anger=max(0.0, min(10.0, current.anger + delta.anger)),
            joy=max(0.0, min(10.0, current.joy + delta.joy)),
            suspicion=max(0.0, min(10.0, current.suspicion + delta.suspicion)),
            boredom=max(0.0, min(10.0, current.boredom + delta.boredom))
        )
        self._states[session_id] = new_state
        return new_state

    async def apply_decay(self, session_id: str, decay_rate: float = 0.5) -> EmotionState:
        """
        Механика естественного «затухания» эмоций. 
        Плавно возвращает все эмоции к нейтральному состоянию (0.0).
        """
        current = await self.get_state(session_id)
        
        new_state = EmotionState(
            anger=max(0.0, current.anger - decay_rate),
            joy=max(0.0, current.joy - decay_rate),
            suspicion=max(0.0, current.suspicion - decay_rate),
            boredom=max(0.0, current.boredom - decay_rate)
        )
        self._states[session_id] = new_state
        return new_state
