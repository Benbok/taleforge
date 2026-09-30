from app.emotion.interfaces import IEmotionAnalyzer
from app.emotion.schemas import EmotionState, PlayerActionContext, GMPersona
import json

# Временно хардкодим профили характеров для тестирования в изоляции
PERSONAS = {
    "sadist": GMPersona(
        name="Садист",
        description="Обожает страдания игроков. Искренне веселится, когда они ошибаются, и злится на их успехи.",
        on_crit_fail=EmotionState(joy=3.0, anger=0.0, suspicion=0.0, boredom=0.0),
        on_crit_success=EmotionState(anger=2.0, suspicion=1.0, joy=0.0, boredom=0.0)
    ),
    "tired_mentor": GMPersona(
        name="Уставший наставник",
        description="Строгий, справедливый, но уставший. Раздражается от глупостей и скучает при очевидных провалах.",
        on_crit_fail=EmotionState(boredom=2.0, anger=1.0, joy=0.0, suspicion=0.0),
        on_crit_success=EmotionState(joy=1.0, anger=0.0, suspicion=0.0, boredom=0.0)
    )
}

class RuleBasedAnalyzer(IEmotionAnalyzer):
    def __init__(self, persona_id: str = "tired_mentor"):
        self.persona = PERSONAS.get(persona_id, PERSONAS["tired_mentor"])
        
    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        delta = EmotionState()
        
        # Реакция теперь берется из характера Мастера, а не захардкожена
        if context.is_critical_failure:
            delta.anger += self.persona.on_crit_fail.anger
            delta.joy += self.persona.on_crit_fail.joy
            delta.boredom += self.persona.on_crit_fail.boredom
            delta.suspicion += self.persona.on_crit_fail.suspicion
            
        elif context.is_critical_success:
            delta.anger += self.persona.on_crit_success.anger
            delta.joy += self.persona.on_crit_success.joy
            delta.boredom += self.persona.on_crit_success.boredom
            delta.suspicion += self.persona.on_crit_success.suspicion
            
        return delta


class LLMAnalyzer(IEmotionAnalyzer):
    def __init__(self, llm_client=None, persona_id: str = "tired_mentor"):
        self.llm_client = llm_client
        self.persona = PERSONAS.get(persona_id, PERSONAS["tired_mentor"])
        
    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        if not context.action_text or not self.llm_client:
            return EmotionState()

        # Промпт теперь фокусируется на оценке ПОВЕДЕНИЯ и логики игрока
        prompt = f"""
        Характер Мастера: {self.persona.name}. {self.persona.description}
        
        Твоя задача — как психологический анализатор оценить семантику действий игрока.
        Насколько это действие влияет на эмоции Мастера (оценка от 0.0 до 4.0)?
        
        Критерии для анализа:
        1. Глупость и нерациональность: Игрок делает откровенную чушь, ломает логику мира или игнорирует здравый смысл? (Вызывает anger или boredom).
        2. Изобретательность и интеллект: Игрок придумал хитрый, нестандартный или изящный план? (Вызывает joy).
        3. Героизм и отыгрыш: Поступок эпичен, драматичен или идеально вписывается в характер персонажа? (Вызывает joy).
        4. Бессмысленный хаос: Игрок убивает без причины или ломает сюжет? (Вызывает anger или suspicion).
        
        Действие игрока: "{context.action_text}"
        
        Отвечай строго в JSON. Ключи: anger, joy, suspicion, boredom.
        """
        
        # Заглушка для компиляции
        data = {"anger": 0.0, "joy": 0.0, "suspicion": 0.0, "boredom": 0.0}
        
        return EmotionState(
            anger=data.get("anger", 0.0),
            joy=data.get("joy", 0.0),
            suspicion=data.get("suspicion", 0.0),
            boredom=data.get("boredom", 0.0)
        )


class HybridAnalyzer(IEmotionAnalyzer):
    def __init__(self, llm_client=None, persona_id: str = "tired_mentor"):
        self.rule_based = RuleBasedAnalyzer(persona_id)
        self.llm_based = LLMAnalyzer(llm_client, persona_id)
        
    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        rule_delta = await self.rule_based.analyze(context)
        llm_delta = await self.llm_based.analyze(context)
        
        return EmotionState(
            anger=rule_delta.anger + llm_delta.anger,
            joy=rule_delta.joy + llm_delta.joy,
            suspicion=rule_delta.suspicion + llm_delta.suspicion,
            boredom=rule_delta.boredom + llm_delta.boredom
        )
