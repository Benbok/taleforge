import asyncio
import sys
import os

# Добавляем корневую папку в sys.path для корректных импортов
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.emotion.schemas import PlayerActionContext
from app.emotion.state_manager import InMemoryStateManager
from app.emotion.analyzers import RuleBasedAnalyzer
from app.emotion.injector import SystemPromptInjector

async def main():
    print("=== Запуск Эмоционального Движка (Изолированный тест) ===\n")
    
    # 1. Инициализация (Профиль: "Уставший наставник")
    state_manager = InMemoryStateManager()
    analyzer = RuleBasedAnalyzer(persona_id="tired_mentor") 
    injector = SystemPromptInjector()
    
    session_id = "test_session_1"
    
    async def process_action(turn_num: int, context: PlayerActionContext):
        print(f"--- Действие {turn_num} ---")
        print(f"Игрок: {context.action_text}")
        if context.is_critical_failure:
            print("[Система: Выпал Критический Провал!]")
            
        # Анализ -> Обновление -> Инъекция
        delta = await analyzer.analyze(context)
        new_state = await state_manager.update_state(session_id, delta)
        prompt = injector.inject(new_state)
        
        print(f"Эмоции Мастера: Гнев={new_state.anger:.1f}, Скука={new_state.boredom:.1f}")
        if prompt:
            print(f"Промпт: {prompt.strip()}\n")
        else:
            print("Промпт: (Пусто, состояние нейтральное)\n")

    # 2. Ход событий
    await process_action(1, PlayerActionContext(
        player_id="p1", character_name="Эльф", action_text="Осматриваю таверну."
    ))
    
    # Игроки начинают жестко тупить (3 крит провала подряд)
    for i in range(3):
        await process_action(2 + i, PlayerActionContext(
            player_id="p2", character_name="Гном", action_text="Пытаюсь украсть кружку у трактирщика.",
            is_critical_failure=True
        ))

    # 3. Затухание после сцены
    print("--- Конец сцены: Применяем затухание (Decay) ---")
    decayed_state = await state_manager.apply_decay(session_id, decay_rate=2.0)
    prompt_after = injector.inject(decayed_state)
    print(f"Эмоции после отдыха: Гнев={decayed_state.anger:.1f}, Скука={decayed_state.boredom:.1f}")
    print(f"Промпт после отдыха: {prompt_after.strip() if prompt_after else '(Пусто)'}\n")
    
if __name__ == "__main__":
    asyncio.run(main())
