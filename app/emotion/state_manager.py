from app.emotion.interfaces import IStateManager
from app.emotion.schemas import EmotionState


class InMemoryStateManager(IStateManager):
    """
    In-memory реализация трекера состояния эмоций для сессий.
    """

    def __init__(self):
        # Хранилище: session_id -> EmotionState
        self._states: dict[str, EmotionState] = {}

    async def get_state(self, session_id: str) -> EmotionState:
        if session_id not in self._states:
            self._states[session_id] = EmotionState()
        return self._states[session_id]

    async def update_state(self, session_id: str, delta: EmotionState) -> EmotionState:
        current = await self.get_state(session_id)

        # Прибавляем дельту и ограничиваем диапазон [0.0, 10.0]
        new_state = EmotionState(
            anger=max(0.0, min(10.0, current.anger + delta.anger)),
            joy=max(0.0, min(10.0, current.joy + delta.joy)),
            suspicion=max(0.0, min(10.0, current.suspicion + delta.suspicion)),
            boredom=max(0.0, min(10.0, current.boredom + delta.boredom)),
        )
        self._states[session_id] = new_state
        return new_state

    async def apply_decay(self, session_id: str, rates: EmotionState | None = None) -> EmotionState:
        """
        Естественное затухание эмоций.
        Если rates не передан, используются дефолтные скорости затухания.
        """
        current = await self.get_state(session_id)
        r = rates or EmotionState(anger=0.5, joy=0.8, suspicion=0.3, boredom=1.0)

        new_state = EmotionState(
            anger=max(0.0, current.anger - r.anger),
            joy=max(0.0, current.joy - r.joy),
            suspicion=max(0.0, current.suspicion - r.suspicion),
            boredom=max(0.0, current.boredom - r.boredom),
        )
        self._states[session_id] = new_state
        return new_state
