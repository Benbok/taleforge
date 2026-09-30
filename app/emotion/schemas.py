from pydantic import BaseModel, Field
from typing import Optional, List

class EmotionState(BaseModel):
    anger: float = Field(default=0.0, ge=0.0, le=10.0, description="Гнев/Раздражение")
    joy: float = Field(default=0.0, ge=0.0, le=10.0, description="Радость/Веселье")
    suspicion: float = Field(default=0.0, ge=0.0, le=10.0, description="Подозрительность")
    boredom: float = Field(default=0.0, ge=0.0, le=10.0, description="Скука/Усталость")


class GMPersona(BaseModel):
    """
    Характер Мастера. Определяет, как именно он реагирует на происходящее.
    """
    name: str
    description: str
    
    # Векторы реакций на события механики (можно настраивать для каждого характера)
    on_crit_fail: EmotionState
    on_crit_success: EmotionState


class PlayerActionContext(BaseModel):
    player_id: str
    character_name: str
    action_text: str
    dice_result: Optional[int] = None
    is_critical_success: bool = False
    is_critical_failure: bool = False
    tags: List[str] = Field(default_factory=list)
