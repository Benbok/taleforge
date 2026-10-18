# Проверка технической модели location_layout

Скрипты запускаются из корня репозитория с настроенным `.env` и `PYTHONPATH=.`.
Они вызывают настоящий API выбранной технической модели. Успешные вызовы тарифицируются;
кампании и БД не изменяются. Ключи не сохраняются в результатах.

```powershell
$env:PYTHONPATH = '.'
$env:PYTHONUTF8 = '1'
uv run python experiments/location-layout-model/benchmark.py --output experiments/location-layout-model/result.json
uv run python experiments/location-layout-model/e2e.py
```

`benchmark.py` проверяет пять мандатов: храм с привязками и без, таверну, пещеру и порт.
Для каждого по умолчанию два независимых прогона. Разбор ответа, `obligations()` и
`DeterministicLayoutProvider.propose()` настоящие; максимум попыток берётся из `LLM_LIMIT`.
Сохраняются результаты каждого вызова, ошибки, токены, стоимость и принятые замыслы.
Ошибки сети/API учитываются как непринятые прогоны, отдельно от ошибок самого замысла.
Доступны `--runs`, `--seed`, `--model` и повторяемый `--case`.

`e2e.py` и `repro_layout.py` перенесены из пользовательского scratchpad, чтобы они не пропали.
Первый повторяет исходный эксперимент с храмом, с привязками и без, по два прогона.
Второй сравнивает текущую схему (`original`), возвращённый проблемный лимит
`parts.maxItems=12` (`bounded_parts`) и варианты удаления ключевых слов из проблемной схемы.
Для проверки конкретных вариантов передайте их названия, чтобы не вызывать все варианты:

```powershell
uv run python experiments/location-layout-model/repro_layout.py original bounded_parts
```

`bounded_parts` нужен только для воспроизведения Gemini 400; не переносить его в production.
Сервер по-прежнему ограничивает `LayoutIntent.parts` двенадцатью частями.
Новые `maxItems` поверх вложенных ограниченных массивов в production-схему не добавлены.

## Замеры 2026-10-18

Модель: `gemini/gemini-3.5-flash-lite`. Пять одинаковых мандатов, два прогона каждого,
`seed=7`, максимум два вызова на прогон. Исходная точка — перенесённый `e1743ac`
(локальный cherry-pick `5d7273f`): ошибка схемы 400 уже исправлена, остальные изменения отсутствуют.

| Вариант | Приняты за 1–2 вызова | С первого вызова | Вызовов | Учтённая стоимость |
|---|---:|---:|---:|---:|
| Исходный (`baseline.json`) | 4/10 | 2/10 | 18 | $0.0383202 |
| Первое уточнение (`after-initial.json`) | 7/10 | 6/10 | 14 | $0.0317493 |
| Уточнение деталей и форм (`after-pre-review.json`) | 9/10 | 4/10 | 16 | $0.0419457 |
| Окончательный (`after.json`) | 10/10 | 9/10 | 11 | $0.0241391 |

Отдельный контроль исходным `e2e.py` на окончательном коде: принято 3/4, из них 3 с первого вызова.
Один прогон с привязками отклонён дважды: сначала нарушена тайность `vault`, затем
предложена лестница между одинаковыми уровнями. Его стоимость по округлённому выводу
скрипта, вместе с остальными тремя прогонами, около $0.0145.
Итого в двух окончательных сериях принято 13/14 (12 с первого вызова).

Это небольшие стохастические выборки, а не гарантия успешности на произвольном месте.
Неудачи не исключались из результатов. В окончательных сериях случались временные API 500,
которые штатно повторил `LiteLLMClient`; Gemini 400 от текущей схемы не было.

## Что изменено

- Без привязок поле `anchors` не предлагается в схеме: нет зависимости от передачи пустого `enum` адаптером.
- Промпт и описания полей объясняют ссылки `band_ref`, ключи привязок, уровни лестниц,
  свободную сторону внешнего подхода, размеры проходов, формы и координаты деталей.
- Мандат явно перечисляет окружение и тайность каждой обязательной части.
- Корректирующая попытка получает пояснения именно по ошибке, включая допустимые ключи,
  существующие полосы и уровни родителя/ребёнка. Замысел не исправляется скрыто сервером.
- Исполнитель прекращает цикл после исчерпания лимита: бюджет контекста для третьего,
  уже недопустимого вызова не подменяет причину отказа второго.

Все три слоя валидации, лимиты токенов, учёт расходов и детерминированный резерв сохранены.
Регрессии и успешная коррекция проверяются в `tests/test_layout_model.py` и
`tests/test_layout_model_phase.py`.

```powershell
uv run pytest tests/test_layout_model.py tests/test_layout_model_phase.py
uv run ruff check app/agents/layout_model.py app/core/layout/executor.py tests/test_layout_model.py experiments/location-layout-model
uv run ruff format --check app/agents/layout_model.py app/core/layout/executor.py tests/test_layout_model.py experiments/location-layout-model
```

## Результаты локальных проверок

- Профильные тесты модели и фазы: **30 passed**.
- `ruff check`, `ruff format --check` по изменённым файлам и `git diff --check`: успешно.
- `graphify update .`: завершён (AST, без модели).
- Общий `uv run pytest -q`: **1943 passed, 19 skipped, 10 failed**, 461.80 секунды.

Девять отказов общего прогона повторены в отдельном Python-процессе после загрузки
`layout_model.py` и `executor.py` из исходного `5d7273f`, без изменения файлов рабочего дерева:

- `tests/test_context_quality.py::test_context_quality_scenario_executes_complete_game_turn[unknown_parser]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[False-empty]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[False-error]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[False-timeout]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[True-empty]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[True-error]`
- `tests/test_context_quality.py::test_unknown_parser_recovery_variants[True-timeout]`
- `tests/test_map_migrations.py::test_location_map_migrations_match_metadata`
- `tests/test_llm_accounting.py::test_usage_coverage_migration_preserves_historical_unknown`

Первые семь относятся к ожиданиям восстановления парсера. Миграции имеют два `revision=0031`;
`upgrade head` неоднозначен, а выбранная миграция не добавляет `llm_calls.tokens_cached`.
Эти отказы воспроизводятся без текущего исправления `location_layout`.

Десятый сбой — падение worker `gw2` во время
`tests/test_turn_efficiency.py::test_paired_scripted_turn[unparsed]`;
отдельно на исходной версии он не воспроизводился, его причина здесь не установлена.
Общий прогон нельзя считать успешным. Изменения парсера и миграций в эту задачу не включены.
