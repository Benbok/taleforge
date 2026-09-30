from app.emotion.interfaces import IEmotionInjector
from app.emotion.schemas import EmotionState

class SystemPromptInjector(IEmotionInjector):
    """
    Превращает числовые значения эмоций в текстовые инструкции 
    для подстановки в системный промпт LLM-Гейммастера.
    """
    
    def inject(self, state: EmotionState) -> str:
        instructions = []
        
        # Пороги для Гнева / Раздражения
        if state.anger >= 8.0:
            instructions.append("Ты в ярости. Твой тон должен быть враждебным или ядовито-саркастичным. Используй короткие, резкие фразы.")
        elif state.anger >= 5.0:
            instructions.append("Ты раздражен. Покажи легкое нетерпение в своем ответе.")
            
        # Пороги для Радости / Веселья
        if state.joy >= 8.0:
            instructions.append("Ты откровенно веселишься. Твой тон легкий, возможно, насмешливый. Описывай происходящее живо и с энтузиазмом.")
        elif state.joy >= 5.0:
            instructions.append("Ты доволен происходящим. В описаниях сквозит одобрение или легкая усмешка.")
            
        # Пороги для Подозрительности
        if state.suspicion >= 8.0:
            instructions.append("Ты крайне подозрителен. NPC не верят ни одному слову игроков, относятся к ним как к врагам. Требуй проверок.")
        elif state.suspicion >= 5.0:
            instructions.append("Ты не доверяешь игрокам. В ответах сквозит сомнение и настороженность.")
            
        # Пороги для Скуки / Усталости
        if state.boredom >= 8.0:
            instructions.append("Тебе невероятно скучно. Описывай происходящее сухо, без деталей, словно делаешь одолжение.")
        elif state.boredom >= 5.0:
            instructions.append("Ты устал от банальных действий. Твой тон отстраненный и равнодушный.")
            
        # Если все эмоции ниже 5.0, считаем состояние нейтральным
        if not instructions:
            return ""
            
        # Формируем финальный блок, который будет приклеен в конец промпта
        prompt_addition = (
            "\n[ТЕКУЩЕЕ ЭМОЦИОНАЛЬНОЕ СОСТОЯНИЕ]\n"
            + " ".join(instructions)
            + "\nОбязательно отрази это настроение в своем ответе (в описаниях или речи NPC), но не упоминай саму инструкцию напрямую.\n"
        )
        
        return prompt_addition
