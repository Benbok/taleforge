# Исправление интеграции контекста мастера — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Подключить реальный отбор контекста к игровым ходам, устранить потерю заявок при сбое парсера и измерить экономию без ухудшения исполнения и повествования.

**Architecture:** Структурированные источники → снимок фактов → отбор с зависимостями и видимостью → однократная сериализация → фактический вызов LLM. Восстановление заявки, сокращение данных и сокращение схем инструментов проверяются раздельно. Интеграционные тесты перехватывают messages/tools непосредственно на границе llm.complete.

**Tech Stack:** Python >=3.11, SQLAlchemy, Jinja2, LiteLLM, pytest, PostgreSQL, существующий evaluator.

**Spec:** ../specs/2026-10-16-master-context-revision-design.md. Этот план уточняет реализацию исходного дизайна по результатам ручной проверки; предыдущий план не является доказательством завершения интеграции.

Статус: задачи 1–6 выполнены и проверены в текущей `main`; полный suite зелёный.
Фактический отчёт: `docs/superpowers/reviews/2026-10-16-context-fixes-verification.md`.
Проверенный code HEAD перед итоговым документальным handoff: `e400954`.

## Global Constraints

- Работа в текущей main. Сохранить чужие изменения и .tmp_exec_probe.
- Единое поведение для старых и новых кампаний, без пользовательских флагов.
- Не уменьшать длину ответа, не менять модель/генерацию ради показателей экономии.
- Не ослаблять ownership, правила механики, видимость, проверку реальных action_ref.
- Не сокращать неструктурированную память по первым N символам или ключевым словам.
- Не добавлять LLM-вызов для отбора контекста. Восстановление парсинга ограничено и учитывается отдельно.
- EARLY_FINISH_ENABLED оставить False: эффект завершения хода вне этого эксперимента.
- Мягкий ориентир decide 5–12 тыс. входных токенов включает tools; обязательные факты важнее размера.
- До ручной границы — только офлайн-тесты: без платных моделей, игровых действий и перезапуска контейнера.
- После изменения кода выполнить graphify update .; коммитить явный перечень файлов.

## Исходные доказательства и ограничения

Четыре хода 2026-10-16, 11:35–11:38 МСК:
- два decide-пакета использовали legacy по uncertain_intent, два — по soft_budget;
- role-context-v1 маркирует и fallback, поэтому не доказывает применение отбора;
- collect_decision_facts и collect_narration_facts не подключены к production-сборке;
- схемы tools: около 31 тыс. оценочных токенов в трёх ходах, 14 тыс. в одном;
- два сообщения не получили resolution_actions: пустой actions и ошибка parse 400;
- модель придумала source_id=current и другие несуществующие источники; сервер отменил действия;
- учтено $0.074297 с parse; цена ошибочного parse неизвестна.
Предыдущие ходы тоже маркированы role-context-v1. Их среднее не является контрольной группой «до».
Причина Gemini 400 не установлена: не приписывать её конкретному параметру без воспроизведения.

## Review Focus

- Парсер вернул пустой результат, timeout или 400: заявка не теряется и не исполняется по выдуманному ref — задача 2.
- Два героя и составное действие: восстановление не меняет владельца, порядок и уже исполненные части — задачи 2, 6.
- Длинная история, старое обещание, неизвестная зависимость: экономия не удаляет обязательную память — задачи 3, 6.
- Разделённая партия и resume после перехода: актуальный снимок, отсутствие утечек — задачи 4, 6.
- Узкий набор tools не содержит нужной возможности: расширение работает, права не расширяются — задачи 5, 6.

## Task 1: Закрепить ошибки и честную диагностику

**Files:** Modify app/agents/master/prompt_context.py, app/agents/master/turn.py, app/core/llm_diagnostics.py;
Create tests/test_context_runtime_integration.py;
Modify tests/test_master_prompt_context.py;
Create docs/superpowers/reviews/2026-10-16-context-fix-baseline.md.

**Interfaces:** PromptBundle.metadata(role) добавляет assembly_path (selected/expanded/legacy), selection_applied, expansion_reasons. Размеры messages/tools считаются по фактическим аргументам каждого _ask, отдельно от логических разделов. Поля не содержат текстов, исходных refs или provider signatures.

- [ ] Создать тест с перехватом llm.complete: при legacy selection_applied=False независимо от версии; сумма измеренных messages/tools совпадает с сериализацией перехваченного вызова.
- [ ] Запустить новые тесты, записать исходные failures.
- [ ] Добавить метрики фактически выбранного пути, повторов и причины расширения, не менять поведение сборки.
- [ ] Зафиксировать базу: commit, текущие размеры, число вызовов, parse отдельно, неизвестную стоимость. В отчёте никаких сырых trace/call_key с signatures.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_context_runtime_integration.py tests/test_master_prompt_context.py -n 0 -q; ожидается PASS.
- [ ] Коммит: test: expose actual context assembly and establish baseline.

## Task 2: Восстановить исполнимый источник при неуспешном разборе

**Files:** Modify app/agents/master/parsing.py, app/agents/master/turn.py, app/agents/master/action_binding.py, app/tools/resolution/requests.py;
Create app/agents/master/intent_recovery.py, tests/test_intent_recovery.py;
Modify tests/test_action_binding_regressions.py, tests/test_intent.py.

**Interfaces:** recover_message_intent(ctx, message) -> recovery result со status recovered/clarification_required и reason; результат не даёт разрешения на игровую мутацию. Повторно использовать существующую валидацию app.agents.intent.check.

- [ ] Тесты: пустые actions, отсутствующий intent, timeout, LLMError 400; после восстановления ссылки указывают на реальное сохранённое сообщение и принадлежащего ему героя.
- [ ] Отдельные тесты: чужой seat/ref отвергается; уже выполненная часть не повторяется; составная заявка сохраняет порядок; речь не превращается в произвольную механическую команду.
- [ ] Запустить тесты и подтвердить failures на текущем коде.
- [ ] До запуска decide выполнить максимум одну дополнительную попытку разбора исходного сообщения штатным парсером при невалидной/пустой механической заявке. Учитывать её вызов и стоимость. При повторной неудаче запросить уточнение и завершить без ложного успеха и без автоматического сообщения «мастер не обработал действие».
- [ ] Только после валидированного разбора сохранять resolution_actions и выполнять штатный binding. Не создавать универсальный custom-ref, разрешающий любые эффекты.
- [ ] Выяснить отдельно причину 400 по воспроизведённому payload/адаптеру без сетевого вызова. Если локально не воспроизводится, добавить безопасную диагностику типа ошибки/схемы и оставить причину открытой; не повторять детерминированно неверный запрос бесконечно.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_intent_recovery.py tests/test_action_binding_regressions.py tests/test_intent.py -n 0 -q; ожидается PASS.
- [ ] Коммит: fix: recover unresolved player intents before decision execution.

## Task 3: Подключить структурированный отбор к decide

**Files:** Modify app/agents/master/context_selection.py, app/agents/master/prompt_context.py, app/agents/master/turn.py;
Create app/agents/master/context_snapshot.py;
Modify tests/test_master_context_selection.py, tests/test_context_runtime_integration.py.

**Interfaces:** collect_context_snapshot(ctx, cfg, *, messages, memory, history) -> tuple[ContextFact, ...]; существующий select_context сохраняет контракт. build_prompt_bundle получает context_facts и subjects; request содержит только новые реплики, а не весь прежний prompt.

- [ ] Создать production-path тест: добавить уникальные маркеры текущего NPC, далёкого несвязанного NPC, активной реакции, старого обещания, правила и action_ref; проверять их наличие/отсутствие в перехваченном decide-запросе.
- [ ] Тесты: зависимость обязательного факта сохранена; неизвестная зависимость расширяет соответствующий раздел; превышение бюджета сохраняет обязательные данные без возврата legacy; неизвестный intent расширяет релевантные разделы с диагностикой.
- [ ] Запустить новые тесты и подтвердить failures.
- [ ] Собирать факты из структур мира до рендера: герои/цели/место/пути/ресурсы/эффекты/реакции/заявки/сюжет. Устойчивый ключ = источник и поле; актуальное состояние и историческое событие имеют разные ключи.
- [ ] Неструктурированные memory/history сохранить отдельными обязательными блоками до доказанного безопасного отбора. Не обещать сокращение этих блоков.
- [ ] Вызвать selector в реальном build_prompt_bundle, удалить regex/string-вырезание ранее склеенных блоков. Удалить возврат legacy только из-за soft_budget; полное расширение допустимо лишь при неизвестной области и отражается как expanded.
- [ ] Включить tools в бюджетную диагностику на границе _ask. Версию изменить на context-v2 только для нового пути.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_master_context_selection.py tests/test_context_runtime_integration.py tests/test_master_prompt_context.py -n 0 -q; ожидается PASS.
- [ ] Коммит: fix: apply fact selection in production decision prompts.

## Task 4: Подключить отбор к повествованию и сохранить качество

**Files:** Modify app/agents/master/narration.py, app/agents/master/prompt_context.py, app/agents/master/finish.py, app/agents/master/context_snapshot.py;
Modify tests/test_narration_context_packet.py, tests/test_voice_emotion_context.py, tests/test_context_runtime_integration.py.

**Interfaces:** тот же ContextFact; narrate получает подтверждённые исходы и явную аудиторию. Снимок строится после исполнения внутри активной DB-сессии, до параллельных narrate/voice.

- [ ] Тест реального narrate-вызова: сохранены исход, характер NPC, отношения, обещание, стиль; приватный мотив не утёк.
- [ ] Тесты: общая аудитория разделённой партии видит только общее знание; resume после перехода получает новое место; параллельный voice не меняет снимок narrator.
- [ ] Подтвердить failures, подключить collect_narration_facts к реальной сборке, сериализовать выбранное один раз. Сохранить текущий аудит выдуманных исходов и речи игрока.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_narration_context_packet.py tests/test_voice_emotion_context.py tests/test_context_runtime_integration.py -n 0 -q; ожидается PASS.
- [ ] Коммит: fix: build narration from selected audience-safe facts.

## Task 5: Уменьшить схемы инструментов без потери возможностей

**Files:** Modify app/agents/master/tool_profiles.py, app/tools/registry.py, app/agents/master/turn.py;
Modify tests/test_decision_tool_profiles.py, tests/test_context_runtime_integration.py.

**Interfaces:** select_tool_profile и profile_tool_names сохраняют контракты; expand_decision_tools расширяет только до исходно разрешённых campaign tools. Метрики: profile, count, общий размер схем и размер каждой схемы.

- [ ] Сначала измерить схемы по инструментам на фиксированном мире; записать крупнейшие и повторяемые определения.
- [ ] Тесты перехваченных tools: обычное перемещение/диалог/осмотр используют профиль; смешанная/неизвестная команда сохраняет корректный путь расширения; новый инструмент не попадает в узкий профиль автоматически.
- [ ] Заменить включение всех read-only tools в каждый профиль явными наборами необходимых чтений. Для общей стартовой выборки оставить базовые действия/чтения и expand; полный набор доступен после расширения.
- [ ] Сократить повторяющиеся описания схем только при сохранении всех ограничений аргументов. Не удалять проверки server-side и не полагаться на неподдерживаемые провайдером ссылки на внешние schema definitions.
- [ ] Проверить расширение и последующий успешный вызов нужного инструмента в одном полном ходе; учитывать стоимость дополнительного decide.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_decision_tool_profiles.py tests/test_context_runtime_integration.py -n 0 -q; ожидается PASS.
- [ ] Коммит: perf: reduce initial decision tool schemas with verified expansion.

## Task 6: Исполняемые сценарии и честный парный замер — офлайн-часть выполнена

**Files:** Modify tools/eval_turn_efficiency.py, tests/test_turn_efficiency.py, tests/test_context_quality.py, tests/fixtures/context_quality.json;
Create tests/context_scenarios.py;
Modify app/core/spend.py только если нужны недостающие поля отчёта.

**Interfaces:** сценарий создаёт фиксированное начальное состояние, подаёт requests через реальный turn pipeline и проверяет expected_outcomes, required_facts, forbidden_facts в перехваченных запросах. Варианты evaluator: baseline snapshot и context-v2; никакого переключателя в игре.

- [ ] Превратить все 12 сценариев manifest в исполняемые фикстуры. Проверка наличия ключей JSON не считается проверкой поведения.
- [ ] Офлайн пройти все сценарии через настоящий orchestrator со scripted LLM; контроль исходов мира/полноты/видимости обязателен.
- [ ] Отдельно сравнить: (а) сборку контекста при одинаковых tools/исходах; (б) tools при одинаковом контексте; (в) полные ходы. Вариант baseline получает тот же фикс refs и ту же политику завершения.
- [ ] Фиксировать model/settings, commit, fixture hash, последовательность, cache usage, число вызовов/повторов, parse/recovery/voice/emotion/summary, все ошибки и неизвестные цены.
- [ ] Сумма стоимости включает ошибки и попытки; цену полного успешного хода считать отдельно. Оценочные токены/байты не выдавать за provider usage/USD.
- [ ] Запустить .venv\Scripts\python.exe -m pytest tests/test_context_quality.py tests/test_turn_efficiency.py tests/test_context_runtime_integration.py -n 0 -q; ожидается PASS.
- [ ] Подготовить протокол платного запуска: 12 сценариев × 3 повтора × сравниваемые варианты, заранее определённый бюджет и остановка; сейчас не запускать.
- [ ] Коммит: test: exercise production context and compare paired scenarios.

## Task 7: Проверка и передача ручного теста — автоматическая проверка заблокирована

**Files:** Update этот план и предыдущий 2026-10-16-master-context-revision.md;
Create docs/superpowers/reviews/2026-10-16-context-fixes-verification.md.

- [x] Выполнить полный .venv\Scripts\python.exe -m pytest -n 4 -q, ruff по изменённым файлам и git diff --check; сохранить фактический результат. Полный прогон: 1865 passed, 5 skipped, 7 failed; один split-party websocket timeout остаётся. Assertions не ослаблялись.
- [x] Повторить полный suite после Tasks 1–5 и финального runtime-контракта: `1893 passed, 5 skipped, 35 warnings`, exit code `0`.
- [x] Выполнить graphify update . и проверить diff на чужие изменения/секреты.
- [x] Отдельно подтвердить: production selector вызывается, фактические запросы проверены, legacy не возвращается по размеру, отказ разбора не теряет заявку, tools могут расширяться.
- [x] Исправить прежний статус «реализация выполнена»: описать найденный разрыв и сослаться на новый отчёт; отмечать только действительно пройденные шаги.
- [ ] Передать ручной набор: в текущей кампании повторить осмотр и выход через дверь, проверить старое обещание; в новой — старт, диалог, составное действие и переход.
- [x] Остановиться перед перезапуском и платной/ручной проверкой. Текущую кампанию не сбрасывать и не использовать как изменяемую A/B-фикстуру.
- [ ] Экономию принимать только по парному набору: цель −40% входа decide, −40% стоимости полного хода, −25% медианной задержки; ни одна цель не объявляется достигнутой по офлайн-оценкам.
- [ ] Качество: ноль новых нарушений механики/refs/видимости; ручная слепая оценка связности, характеров, памяти, атмосферы и инициативы без снижения среднего по каждому измерению. Сокращённую выборку пометить предварительной.

## Критерий завершения

Код готов к ручной проверке только после задач 1–7 и автоматических проверок реального пути. Экономия и качество живой прозы остаются отдельным, ещё не пройденным этапом до парного измерения. Новая кампания дополняет регрессионную проверку текущей, но не заменяет контрольную группу.
