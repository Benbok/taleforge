# Context revision baseline

Дата: 2026-10-16. Рабочая ветка: `main`.

Исходный коммит: `86f0f7e` (`test: validate turn efficiency and quality gates`).
В рабочем дереве до пересмотра уже находилась незавершённая always-on интеграция:

- `app/agents/master/optimization.py`
- `app/api/campaigns.py`, `app/api/schemas.py`
- тесты action refs/completion
- сгенерированные `web/openapi.json` и `web/src/lib/api.gen.ts`

Эти изменения сохранены и не считаются частью новой реализации контекста.
`.tmp_exec_probe` — существующий пользовательский файл, сохранён.

Команда из плана:

```text
.venv\Scripts\python.exe -m pytest tests/test_decision_action_refs.py tests/test_decision_completion.py tests/test_compact_review.py tests/test_master_prompt_context.py tests/test_voice_emotion_context.py tests/test_character_admission.py -n 4 -q
```

Результат: процесс дошёл до `bringing up nodes...` и не выдал итогового отчёта;
запуск без xdist (`-n 0`) также завис на инициализации и был остановлен после
проверки отсутствия прогресса в журнале. Это инфраструктурный сбой baseline,
а не PASS/FAIL отдельных тестов. Ранее зафиксированный ориентир — 14 failures
на незавершённой интеграции; он не подменяет повторное измерение.

## Матрица вариантов evaluator

| Вариант | Механика | Сборка контекста | Живой прогон |
|---|---|---|---|
| `legacy` | текущая | полный legacy prompt | не запускался |
| `v1` | текущая | role-context-v1 | не запускался |
| `revised` | одинаковая с `v1` | отбор обязательных фактов (этот план) | не запускался |

До завершения задач 2–5 нет достоверных чисел экономии или качества. Платные
прогоны не выполнялись.
