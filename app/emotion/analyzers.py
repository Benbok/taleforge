import json
import re
from typing import Any

from app.emotion.interfaces import IEmotionAnalyzer
from app.emotion.schemas import EmotionState, GMPersona, PlayerActionContext

# Профили характеров Мастера
PERSONAS: dict[str, GMPersona] = {
    "sadist": GMPersona(
        name="Садист",
        description="Обожает страдания игроков. Искренне веселится, когда они ошибаются, и злится на их успехи.",
        on_crit_fail=EmotionState(joy=3.0, anger=0.0, suspicion=0.0, boredom=0.0),
        on_crit_success=EmotionState(anger=2.0, suspicion=1.0, joy=0.0, boredom=0.0),
        tag_reactions={
            "attack_friendly": EmotionState(joy=3.0),
            "steal": EmotionState(joy=1.5),
            "heroic": EmotionState(anger=2.0),
            "clever_plan": EmotionState(anger=1.0, suspicion=2.0),
            "nonsense": EmotionState(joy=2.0),
        },
        decay_rates=EmotionState(anger=0.6, joy=0.4, suspicion=0.3, boredom=0.8),
    ),
    "tired_mentor": GMPersona(
        name="Уставший наставник",
        description="Строгий, справедливый, но уставший. Раздражается от глупостей и скучает при очевидных провалах.",
        on_crit_fail=EmotionState(boredom=2.0, anger=1.0, joy=0.0, suspicion=0.0),
        on_crit_success=EmotionState(joy=1.5, anger=0.0, suspicion=0.0, boredom=0.0),
        tag_reactions={
            "attack_friendly": EmotionState(anger=3.0, suspicion=1.0),
            "steal": EmotionState(suspicion=2.0, boredom=1.0),
            "heroic": EmotionState(joy=2.5),
            "clever_plan": EmotionState(joy=3.0),
            "nonsense": EmotionState(boredom=2.5, anger=1.5),
        },
        decay_rates=EmotionState(anger=0.5, joy=0.8, suspicion=0.3, boredom=1.0),
    ),
}


class RuleBasedAnalyzer(IEmotionAnalyzer):
    """
    Эвристический анализатор: критические броски и теги игровой механики.
    """
    def __init__(self, persona_id: str = "tired_mentor"):
        self.persona = PERSONAS.get(persona_id, PERSONAS["tired_mentor"])

    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        delta = EmotionState()

        # 1. Реакция на критические успехи и провалы
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

        # 2. Реакция на семантические теги действий
        for tag in context.tags:
            reaction = self.persona.tag_reactions.get(tag)
            if reaction:
                delta.anger += reaction.anger
                delta.joy += reaction.joy
                delta.boredom += reaction.boredom
                delta.suspicion += reaction.suspicion

        return delta


class LLMAnalyzer(IEmotionAnalyzer):
    """
    Анализатор семантики поведения игрока с использованием реального LLM-клиента.
    """
    def __init__(self, llm_client=None, persona_id: str = "tired_mentor", model: str = ""):
        self.llm_client = llm_client
        self.persona = PERSONAS.get(persona_id, PERSONAS["tired_mentor"])
        self.model = model

    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        if not context.action_text or not self.llm_client:
            return EmotionState()

        prompt = f"""
Характер Мастера: {self.persona.name}. {self.persona.description}

Твоя задача — как психологический анализатор оценить семантику действий игрока.
Насколько это действие влияет на эмоции Мастера (оценка от 0.0 до 4.0)?

Критерии для анализа:
1. Глупость: Игрок делает откровенную чушь или игнорирует здравый смысл? (Вызывает anger или boredom).
2. Изобретательность и интеллект: Игрок придумал хитрый, нестандартный или изящный план? (Вызывает joy).
3. Героизм и отыгрыш: Поступок эпичен, драматичен или идеально вписывается в характер персонажа? (Вызывает joy).
4. Бессмысленный хаос: Игрок убивает без причины или ломает сюжет? (Вызывает anger или suspicion).

Действие игрока: "{context.action_text}"

Отвечай СТРОГО в формате JSON без какого-либо дополнительного текста.
Пример: {{"anger": 0.0, "joy": 2.5, "suspicion": 0.0, "boredom": 0.0}}
"""
        messages = [
            {"role": "system", "content": "Ты — анализатор эмоций. Отвечай строго валидным JSON-объектом."},
            {"role": "user", "content": prompt.strip()},
        ]

        try:
            reply = await self.llm_client.complete(
                messages,
                model=self.model,
                max_tokens=128,
                temperature=0.2,
            )
            raw_text = reply.text.strip() if hasattr(reply, "text") else str(reply)

            # Удаление markdown-блоков ```json ... ``` при наличии
            match = re.search(r"\{.*\}", raw_text, re.DOTALL)
            if match:
                raw_text = match.group(0)

            data = json.loads(raw_text)
        except Exception:
            # При любой ошибке (таймаут, парсинг, ошибка сети) не прерываем ход
            return EmotionState()

        def clamp(v: Any) -> float:
            try:
                return max(0.0, min(4.0, float(v)))
            except (ValueError, TypeError):
                return 0.0

        return EmotionState(
            anger=clamp(data.get("anger", 0.0)),
            joy=clamp(data.get("joy", 0.0)),
            suspicion=clamp(data.get("suspicion", 0.0)),
            boredom=clamp(data.get("boredom", 0.0)),
        )


class HybridAnalyzer(IEmotionAnalyzer):
    """
    Комбинирует эвристику (броски + теги) и семантический анализ LLM.
    """
    def __init__(self, llm_client=None, persona_id: str = "tired_mentor", model: str = ""):
        self.rule_based = RuleBasedAnalyzer(persona_id)
        self.llm_based = LLMAnalyzer(llm_client=llm_client, persona_id=persona_id, model=model)

    async def analyze(self, context: PlayerActionContext) -> EmotionState:
        rule_delta = await self.rule_based.analyze(context)
        llm_delta = await self.llm_based.analyze(context)

        return EmotionState(
            anger=rule_delta.anger + llm_delta.anger,
            joy=rule_delta.joy + llm_delta.joy,
            suspicion=rule_delta.suspicion + llm_delta.suspicion,
            boredom=rule_delta.boredom + llm_delta.boredom,
        )
