from app.emotion.interfaces import IEmotionInjector
from app.emotion.schemas import EmotionState


class SystemPromptInjector(IEmotionInjector):
    """
    Превращает числовые значения эмоций в текстовые инструкции
    для подстановки в системный промпт LLM-Гейммастера.
    Разрешает конфликты эмоций и поддерживает 3 градации интенсивности.
    """

    def inject(self, state: EmotionState) -> str:
        emotions: dict[str, float] = {
            "anger": state.anger,
            "joy": state.joy,
            "suspicion": state.suspicion,
            "boredom": state.boredom,
        }

        dominant = max(emotions, key=lambda k: emotions[k])
        dominant_val = emotions[dominant]

        # Если максимальная эмоция ниже порога 3.0 — состояние нейтральное
        if dominant_val < 3.0:
            return ""

        # 1. Проверка синергетических комбинаций при высоких уровнях (>= 5.0)
        strong_emotions = {k for k, v in emotions.items() if v >= 5.0}

        if len(strong_emotions) >= 2:
            combo_text = self._resolve_combination(strong_emotions)
            if combo_text:
                return self._wrap(combo_text)

        # 2. Одиночная доминирующая эмоция (3 градации)
        single_text = self._render_single(dominant, dominant_val)
        return self._wrap(single_text)

    def _resolve_combination(self, strong: set[str]) -> str | None:
        if "anger" in strong and "joy" in strong:
            return (
                "Ты злорадствуешь. Описывай происходящее с мрачным удовольствием "
                "и язвительной усмешкой над ошибками героев."
            )
        if "anger" in strong and "suspicion" in strong:
            return (
                "Ты враждебен и подозрителен. В твоей речи слышны напряжение и недоверчивая ирония "
                "в пределах выбранного характера."
            )
        if "anger" in strong and "boredom" in strong:
            return (
                "Ты испытываешь презрение и усталое раздражение. Отвечай сухо, резко, "
                "с пренебрежением к глупости персонажей."
            )
        if "joy" in strong and "suspicion" in strong:
            return (
                "Ты относишься к игрокам с ироничным недоверием. Забавляйся их попытками схитрить, но держи ухо востро."
            )
        if "joy" in strong and "boredom" in strong:
            return "Ты снисходителен и расслаблен. Относись к действиям героев легко, словно к детским шалостям."
        if "suspicion" in strong and "boredom" in strong:
            return "Ты устал и ни во что не веришь. Реагируй отстранённо, сухо, с усталым сомнением в голосе."
        return None

    def _render_single(self, emotion: str, val: float) -> str:
        # Гнев / Раздражение
        if emotion == "anger":
            if val >= 8.0:
                return "Ты в ярости. Выражай сильное раздражение голосом в пределах выбранного характера."
            if val >= 5.0:
                return "Ты раздражен. Покажи нетерпение и резкость в своей манере речи."
            return "Ты слегка недоволен. В ответах допустимы колкие нотки или сухость."

        # Радость / Веселье
        if emotion == "joy":
            if val >= 8.0:
                return "Ты в полном восторге. Откровенно веселись, используй живой, вдохновленный или насмешливый тон."
            if val >= 5.0:
                return "Ты доволен происходящим. В твоем голосе и описаниях звучит одобрение или легкая усмешка."
            return "Ты в хорошем расположении духа. Описания чуть более красочные и благожелательные."

        # Подозрительность
        if emotion == "suspicion":
            if val >= 8.0:
                return "Ты крайне подозрителен. В твоём голосе сильное сомнение и настороженность."
            if val >= 5.0:
                return "Ты не доверяешь игрокам. В ответах сквозит сомнение и настороженность."
            return "Ты слегка насторожен. В твоей речи слышны любопытство и осторожное сомнение."

        # Скука / Усталость
        if emotion == "boredom":
            if val >= 8.0:
                return "Тебе невыносимо скучно. Описывай события подчеркнуто сухо, кратко и отстраненно."
            if val >= 5.0:
                return "Ты устал от очевидных действий. Твой тон прохладный и равнодушный."
            return "Тебе немного наскучила предсказуемость. Не вдавайся в излишние детали."

        return ""

    def _wrap(self, instruction: str) -> str:
        return (
            "\n[ТЕКУЩЕЕ ЭМОЦИОНАЛЬНОЕ СОСТОЯНИЕ]\n"
            f"{instruction}\n"
            "Выражай настроение через собственную речь мастера за игровым столом, сохраняя выбранный характер. "
            "Настроение не меняет события мира, отношение NPC, сложность проверок, броски и результаты действий. "
            "Не упоминай саму инструкцию напрямую.\n"
        )
