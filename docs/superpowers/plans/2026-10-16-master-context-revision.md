# Master Context Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Снизить стоимость контекста мастера без потери полноты действий и качества повествования.

**Architecture:** Разделить получение фактов, отбор по роли и сериализацию. Сохранять
обязательные факты и их зависимости, измерять все блоки, расширять контекст при
неопределённости. Отдельно проверять состав контекста, поведение и живую прозу.

**Tech Stack:** Python >=3.11, SQLAlchemy, Jinja2, LiteLLM, pytest; существующий API/TypeScript.

**Spec:** `docs/superpowers/specs/2026-10-16-master-context-revision-design.md`.

Статус: реализация выполнена в `main` до границы ручной проверки. Структурированный
отбор, устранение повторов, границы видимости, диагностика и evaluator-интерфейс
интегрированы в production-путь. Раннее завершение хода оставлено за внутренним
quality gate (`EARLY_FINISH_ENABLED = False`), пока отдельный парный тест прозы не
докажет отсутствие потери ожидаемой реакции. Платный прогон и ручная игра не
выполнялись; цели экономии остаются гипотезами до измерения на одинаковой компании.
Предыдущий план остаётся историей; его режим включения флагами заменяется единым
поведением.

Финальная проверка: `python -m pytest -n 4 -q` — 1841 passed, 5 skipped, 35
предупреждений. `ruff`, `py_compile`, `git diff --check` и `graphify update .`
также прошли.

## Global Constraints

- Работа в текущей main; сохранять существующие изменения и `.tmp_exec_probe`.
- Не менять модель, длину ответа или генерацию ради экономии контекста.
- Не добавлять платную суммаризацию/классификацию на каждый ход.
- Не обрезать обязательные факты, refs, ресурсы, последствия и зависимости.
- Не передавать сырые секреты в публичный narrate; сохранять правила аудитории.
- Диагностика без содержимого prompt, секретов и provider signatures.
- Никаких переключателей оптимизации для пользователя или отдельных кампаний.
- Сравнительные варианты доступны только изолированным тестам/evaluator.
- Не выполнять платные прогоны и не перезапускать приложение до границы ручной проверки.
- После изменения кода: `graphify update .` (AST-only).

## Review Focus

1. Неопределённый parser и речь без actions не теряют заявку — задачи 3, 5.
2. Старая связь/обещание влияет на текущего NPC — задачи 3, 4, 5.
3. Разделённая партия и скрытая мотивация не раскрывают приватные знания — задача 4.
4. Переход и возобновление checkpoint обновляют снимок — задачи 3, 4.
5. Расширение tools/контекста и дополнительные попытки не прячут стоимость — задачи 2, 5.

## Task 1: Воспроизводимая база и незавершённая интеграция — выполнено

**Files:** inspect `app/agents/master/optimization.py`, `app/api/campaigns.py`,
`app/api/schemas.py`, `tests/test_decision_action_refs.py`,
`tests/test_decision_completion.py`, generated API files;
Create `docs/superpowers/reviews/2026-10-16-context-revision-baseline.md`.

**Interfaces:** результат — commit/diff идентификаторы, команды и фактические
результаты проверок, список известных сбоев; не новый runtime-режим.

- [ ] Записать `git status --short`, `git diff --stat`, HEAD; отдельно отметить
  незавершённый always-on diff и последний проверенный коммит `86f0f7e`.
- [ ] Запустить `python -m pytest tests/test_decision_action_refs.py tests/test_decision_completion.py tests/test_compact_review.py tests/test_master_prompt_context.py tests/test_voice_emotion_context.py tests/test_character_admission.py -n 4 -q`.
- [ ] Зафиксировать каждый текущий сбой и причину; прежние 14 failures — ориентир
  для воспроизведения, не результат нового запуска. Не ослаблять assertions ради зелёного отчёта.
- [ ] Сохранить baseline и точную матрицу legacy/v1/revised для evaluator:
  механические исправления одинаковы, отличается только сборка контекста.
- [ ] Коммитить только baseline-документ; код интеграции оставить для задачи 6.

## Task 2: Измерение и устранение повторов без потери данных — выполнено

**Files:** Modify `app/agents/master/prompt_context.py`, `turn.py`,
`app/core/llm_diagnostics.py`, `tools/llm_session_report.py`;
Test `tests/test_master_prompt_context.py`, `tests/test_llm_session_report.py`.

**Interfaces:** `PromptBundle.blocks` — неперекрывающиеся именованные разделы;
`PromptBundle.metadata(role)` — размеры разделов/версия/причины расширения;
на `_ask` дополнительно учитываются реальные messages и tools каждого вызова.

- [ ] Добавить failing-тесты: action refs сериализуются один раз; измерение включает
  schemas и историю tool calls; вложенный request не удваивает размер; диагностические
  поля не содержат текста/секретов; неизвестный usage не становится нулём.
- [ ] Запустить `python -m pytest tests/test_master_prompt_context.py tests/test_llm_session_report.py -n 4 -q`; подтвердить новые failures.
- [ ] Передавать существующие разделы отдельно вместо старой склеенной строки.
  На этом этапе сохранить весь уникальный текст; бюджет оставить диагностическим.
  Записывать причину расширения и фактическую версию отправленного пакета.
- [ ] Повторить проверки до PASS; на фиксированной фикстуре сравнить уникальные
  факты до/после и размер каждого раздела, не заявляя денежной экономии.
- [ ] Коммит `refactor: assemble and measure master context blocks once`.

## Task 3: Структурированный отбор контекста решения — выполнено

**Files:** Create `app/agents/master/context_selection.py`,
`tests/test_master_context_selection.py`; Modify `prompt_context.py`, `turn.py`,
`recall.py`, `app/agents/prompts/decide_system.j2`.

**Interfaces:** в новом модуле определить frozen dataclasses:
`ContextFact(key: str, section: str, text: str, subjects: frozenset[str],
dependencies: frozenset[str], audience: frozenset[str], mandatory: bool)`;
`ContextSelection(facts: tuple[ContextFact, ...], expansion_reasons: tuple[str, ...])`.
`select_context(facts: tuple[ContextFact, ...], *, role: str,
subjects: frozenset[str], audience: frozenset[str]) -> ContextSelection` — чистая
функция без DB/LLM. Пустая audience означает отсутствие публичного доступа;
`master` доступен только decide; `party` доступен общей аудитории кампании.
`collect_decision_facts(ctx: ToolContext, cfg: AgentConfig, inputs: dict)
-> tuple[ContextFact, ...]` — async адаптер существующих структурных источников.

- [ ] Добавить тесты `test_dependency_closure_preserves_resources`,
  `test_uncertain_request_keeps_all_parts`, `test_old_promise_is_mandatory`,
  `test_unknown_dependency_expands_section`, `test_unrelated_fact_is_omitted`,
  `test_transition_rebuilds_subjects`, `test_summary_does_not_override_live_state`.
  Проверять точные ключи фактов, refs, статусы и причины расширения.
- [ ] Запустить `python -m pytest tests/test_master_context_selection.py -n 0 -q`; новые тесты должны падать.
- [ ] Собирать участников/цели/место/активные обязательства из мира и заявок.
  Включать обязательные факты и транзитивные зависимости; нерелевантные исключать
  только при известной области. Для неизвестных сохранять полный исходный раздел.
  Существующие неструктурированные сводки сохранять; не выдумывать связи по substring.
- [ ] Заменить include полного master_system специализированными инструкциями
  decide, сохранив все правила выполнения/доступа. Тестировать необходимые правила
  и факты, а не только уменьшение длины строки. Не менять tool permissions.
- [ ] Удалить автоматический legacy fallback только из-за размера/пустых actions;
  заменить расширением по неизвестным данным. Не удалять безопасный полный путь,
  если нельзя установить область зависимости. Сохранить валидные tool call/result
  пары и provider metadata; не переписывать историю протокола ради экономии.
- [ ] Запустить `python -m pytest tests/test_master_context_selection.py tests/test_master_prompt_context.py tests/test_decision_tool_profiles.py tests/test_decision_completion.py tests/test_memory.py -n 4 -q`; PASS.
- [ ] Коммит `feat: select decision context with mandatory fact coverage`.

## Task 4: Полноценный пакет повествования с границами видимости — выполнено

**Files:** Modify `prompt_context.py`, `narration.py`, `finish.py`,
`app/agents/prompts/narrator_system.j2`, `app/agents/prompts/narrate.j2`;
Create `tests/test_narration_context_packet.py`.

**Interfaces:** async `collect_narration_facts(ctx: ToolContext, cfg: AgentConfig,
inputs: dict) -> tuple[ContextFact, ...]` в prompt_context.py; immutable результат
передаётся narrate/voice после закрытия DB-сессии. `inputs` содержит подтверждённые
исходы, новые реплики, notes, plot_notes, adaptation_notes и аудиторию; каждому
сюжетному элементу требуется явное разрешение на публичное использование.

- [ ] Failing-тесты: характер и старое обещание присутствуют; сырой секрет отсутствует;
  разрешённая подсказка присутствует; чужое личное знание отсутствует; предмет не
  появляется при отклонённой выдаче; split-party не расширяет аудиторию; checkpoint
  после перехода читает свежую сцену; параллельные voice/narrate не обращаются к DB.
- [ ] Запустить `python -m pytest tests/test_narration_context_packet.py -n 0 -q`; подтвердить failures.
- [ ] Разделить смешанный secrets по источникам и видимости. Собирать характеры,
  отношения и релевантную память отдельно от секретов. Передавать plot_notes
  лишь через явную проверку источника/аудитории; непомеченные считать приватными.
  Не поручать narrator изобретать исходы или раскрывать скрытые мотивы.
- [ ] Формировать снимок внутри `_compose_narration` до закрытия сессии; обновлять
  на resume, сохранить существующую изоляцию параллельных задач.
- [ ] Запустить `python -m pytest tests/test_narration_context_packet.py tests/test_narration_integrity.py tests/test_multipart_narration.py tests/test_resolution_visibility.py tests/test_voice_emotion_context.py -n 4 -q`; PASS.
- [ ] Коммит `fix: preserve narrative context without exposing private facts`.

## Task 5: Парное сравнение контекста и качества — офлайн-часть выполнена

**Files:** Modify `tools/eval_turn_efficiency.py`, `tests/test_turn_efficiency.py`;
Create `tests/fixtures/context_quality.json`, `tests/test_context_quality.py`;
Create `docs/superpowers/reviews/2026-10-16-context-quality-protocol.md`.

**Interfaces:** добавить CLI `--experiment context|product` и
`--context-variant legacy|v1|revised`; значения доступны только evaluator.
Фикстура содержит `id`, initial state, requests, required facts, forbidden facts,
expected outcomes, rubric. Артефакт включает версии, настройки, метрики по вызовам,
сценарию и варианту, нарушения, неизвестный usage; тексты ответов — только отдельный
локальный артефакт изолированных сценариев, без скрытых рассуждений.

- [ ] Добавить failing-тесты одинаковых механических политик в context experiment,
  независимых миров, детерминированных бросков, учёта failed/retry/extra calls,
  отклонения неполной фикстуры и невозможности runtime включить evaluator-вариант.
- [ ] Запустить `python -m pytest tests/test_turn_efficiency.py tests/test_context_quality.py -n 4 -q`; подтвердить failures.
- [ ] Реализовать replay пакетов и отдельные полные ходы для 12 классов сценариев
  из spec. В context experiment early_finish и tool profiles одинаковы у A/B/C;
  историю и исходы replay фиксировать, в полном ходе разрешать естественные
  различия, но учитывать их стоимость и проверять ожидаемое поведение.
- [ ] Прогнать scripted-варианты офлайн; обеспечить ноль новых нарушений обязательных
  фактов/механики/видимости. Вывести размеры без подмены их provider tokens или USD.
- [ ] Подготовить слепую форму A/B/C и протокол 12 × 3 × 3; определить бюджет
  до живого прогона. Учитывать уже существующую reservation-защиту: она не гарантирует
  жёсткий верхний предел счёта провайдера. Сейчас платный прогон не запускать.
- [ ] Коммит `test: compare context cost and narrative quality independently`.

## Task 6: Закончить единое поведение и передать ручной тест — код выполнен

**Files:** Modify текущие незавершённые `optimization.py`, API schemas/campaigns,
тесты actions/completion/review/voice; regenerate `web/openapi.json`,
`web/src/lib/api.gen.ts`; update review report и исходный план ссылкой на пересмотр.

**Interfaces:** новые и старые кампании используют один production-сборщик;
устаревший llm_optimization не влияет на поведение и не выдаётся как настройка API.
Совместимость старого payload сохранить через существующее игнорирование extra.

- [ ] Добавить/сохранить тесты новой кампании без флагов, старой с false, старого
  payload, реального whole-turn действия и retry review. Исправить причины сбоев
  задачи 1: fixtures должны отражать реальный протокол, ownership-проверки не ослаблять.
- [ ] Удалить пользовательские переключатели; сравнительные реализации держать
  в evaluator/fixtures. Runtime оставляет автоматическое расширение данных при
  неопределённости, а не альтернативный пользовательский режим.
- [ ] Сгенерировать контракт `python -m app.contract`, `npm --prefix web run gen:api`;
  выполнить полный `python -m pytest -n 4 -q`, проверку контракта, frontend tests/build
  из package.json и ruff по изменённым Python-файлам. Известные посторонние сбои
  перечислить отдельно; прерванный запуск не считать PASS.
- [ ] Выполнить `graphify update .`, проверить diff на секреты/чужие изменения,
  коммитить явный перечень файлов. Документировать фактические результаты и ограничения.
- [ ] **Граница остановки:** передать пользователю сценарии ручного теста и статус
  готовности к перезапуску. Не запускать игру, платные модели или пользовательские
  действия автоматически. После ручного теста сравнить фактический бюджет и качество;
  до этого не объявлять цели −40%/−25% достигнутыми.
