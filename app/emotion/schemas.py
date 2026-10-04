from pydantic import BaseModel, Field


class EmotionState(BaseModel):
    """
    Вектор эмоционального состояния или дельты эмоций.
    Итоговое состояние в менеджере всегда нормализуется в диапазон [0.0, 10.0].
    """

    anger: float = Field(default=0.0, description="Гнев/Раздражение")
    joy: float = Field(default=0.0, description="Радость/Веселье")
    suspicion: float = Field(default=0.0, description="Подозрительность")
    boredom: float = Field(default=0.0, description="Скука/Усталость")


class GMPersona(BaseModel):
    """
    Характер Мастера. Определяет, как именно он реагирует на происходящее.
    """

    name: str
    description: str

    # Векторы реакций на события механики
    on_crit_fail: EmotionState
    on_crit_success: EmotionState

    # Реакции на семантические теги действий (например, "attack_friendly", "clever_plan")
    tag_reactions: dict[str, EmotionState] = Field(default_factory=dict)

    # Скорости естественного затухания каждой эмоции за раунд/сцену
    decay_rates: EmotionState = Field(
        default_factory=lambda: EmotionState(anger=0.5, joy=0.8, suspicion=0.3, boredom=1.0)
    )


class PlayerActionContext(BaseModel):
    player_id: str
    character_name: str
    action_text: str
    dice_result: int | None = None
    is_critical_success: bool = False
    is_critical_failure: bool = False
    tags: list[str] = Field(default_factory=list)
