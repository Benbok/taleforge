# Multipart Player Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Несколько действий в сообщении получают отдельные проверенные результаты без ложной отмены, повторных бросков и расхода ресурсов.

**Architecture:** Существующий ActionRef служит идентификатором части. Общий адаптер проверяет привязку до выполнения инструмента, журнал частей хранит завершение отдельно от промежуточных попыток. Поиск, зависимости и повествование используют тот же источник; координатор сохраняет транзакцию и публикацию.

**Tech Stack:** Python, Pydantic, SQLAlchemy async, PostgreSQL/SQLite, pytest; существующие LLM-инструменты.

**Spec:** `docs/superpowers/specs/2026-10-14-multipart-actions-design.md`, одобрена запросом пользователя «готовь план».

## Global Constraints

- Использовать существующие ActionRef, Message.data.resolution_actions, resolution_completed и журнал попыток MasterTurn. Не вводить отдельный сервис или таблицу.
- Независимые действия продолжаются после неудачи другой части. Зависимые действия блокируются с конкретной причиной.
- Боевой бюджет, доступность целей и правила инструментов остаются обязательными.
- Основной бросок с игровым провалом завершает проверяемое действие без переброса.
- Технические ошибки не превращаются в успех. Отказы и пропуски не становятся доказательствами успеха.
- Исторические предупреждения автоматически не переписывать.
- Произвольные условные программы, автоматическое выполнение будущих ходов и перенос остатков заявки в следующий ход не входят в объём.
- Текущий parser ограничивает actions восемью: в этом объёме лимит не увеличивается.
- Сохранить чужие изменения, не менять `.env`. При подготовке обнаружены изменения `app/agents/voiceover.py` и `tests/test_tts.py`: не включать их в коммиты этой работы.

## Review Focus

1. Несколько сообщений одного героя в одном пакете: ссылка выбирает исходное сообщение, а не произвольную первую заявку — задача 2.
2. Повтор после успешного эффекта, но до публикации: восстановление не бросает и не расходует ресурс повторно — задачи 3, 7.
3. Вспомогательный roll_check мастера без заявки: не закрывает действие игрока — задачи 2, 4.
4. Девять действий в тексте: parser не обрезает хвост до восьми молча — задача 5.
5. Скрытый провал или причина отказа: публичная пометка не раскрывает DC, числа и секреты — задача 6.

## Порядок и рабочее место

Задачи 1 → 2 → 3 → 4 → 5 → 6 → 7 образуют один выпуск. Промежуточные коммиты не разворачивать в работающую игру до завершения всей цепочки.

Перед реализацией проверить инструкции, ветку и git status; выбрать изоляцию по using-git-worktrees, сохранив фактическую базу с текущими изменениями. Не выполнять reset/stash чужой работы. В журнале `.superpowers/sdd/2026-10-14-multipart-actions/progress.md` записывать команды, результаты и согласованные отклонения. План предполагает последовательное исполнение: интерфейсы задач тесно связаны.

Во всех задачах сначала создать тест, затем запустить и убедиться в падении по проверяемому поведению, после реализации повторить ту же команду до PASS. Запуск из корня: `.venv\Scripts\python.exe -m pytest ...`. Использовать существующие fixtures `game`, `play`, `game_client`, управляемые LLM и dice; не обращаться к реальным моделям или рабочей БД.

## Карта файлов

- `app/core/resolution/contracts.py`: типы привязки, итогов и зависимостей.
- `app/tools/resolution/requests.py`: контекст одной части, сохранение результатов, закрытие героя.
- Новый `app/agents/master/action_binding.py`: проверяемое сопоставление инструмента и заявки.
- Новый `app/agents/master/action_progress.py`: роли инструментов, поиск результата, финализация остатка.
- `app/agents/master/resolution.py`, `turn.py`: общий путь серверного и модельного исполнения.
- `app/tools/registry.py`: извлечение метаданных, replay и совместимость closes_actions.
- `app/agents/intent.py` и новый `app/agents/master/action_order.py`: зависимости и готовность шагов.
- `app/agents/master/searches.py`, `narration.py`, `outcomes.py`: подтверждения поиска и конкретные предупреждения.
- `app/tools/narrative/evidence.py`: доказательства по выбранной части.

### Task 1: Контекст и сохранённое состояние отдельной части

**Files:** Modify `app/core/resolution/contracts.py`, `app/tools/resolution/requests.py`; test `tests/test_resolution_requests.py`, `tests/test_resolution_contracts.py`, `tests/test_resolution_policy.py`.

**Interfaces:**
- `ActionDependency(part: int, requires: Literal['applied', 'success'])`.
- `ActionProgress(status: Literal['pending', 'completed', 'denied', 'blocked', 'unhandled'], reason_code: str | None = None, result: ResolutionResult | None = None, blocked_by: list[int] = [])`; использовать Field(default_factory=list).
- `load_action_context(ctx, ref) -> ActionContext`: глагол и цели только `bound[ref.part]`.
- `set_action_progress(ctx: ToolContext, ref: ActionRef, progress: ActionProgress) -> None`: проверенный источник текущего хода; JSON `resolution_progress[str(part)]`. Только completed с applied/repeated пополняет совместимый `resolution_completed`.
- `refresh_actor_closed(ctx: ToolContext, actor_id: str) -> None`: терминальны все обязательные части героя; не изменяет legacy без частей.

- [x] Написать `test_multipart_context_is_local`: search рядом с cast имеет `verbs == ('search',)`, цели только search; соседний cast не запрещает обычное внебоевое разрешение search.
- [x] Написать `test_progress_preserves_other_parts_and_legacy_data`: два результата сохраняются раздельно, чужая ссылка отклоняется, изменение intent не меняет уже привязанные части. `test_terminal_denial_is_not_success_evidence`: denied закрывает учёт, но не создаёт resolution_completed.
- [x] Запустить перечисленные три файла тестов; подтвердить FAIL новых проверок.
- [x] Реализовать интерфейсы, сохранив формат ActionRef/schema_version=1; старые записи без resolution_progress читать через существующие completed, остальные считать pending. record_attempt сохраняет попытку, но не объявляет промежуточную проверку завершённой автоматически.
- [x] Повторить тесты до PASS; адресно закоммитить файлы задачи: `fix: isolate multipart action context and progress`.

### Task 2: Привязка до изменения мира

**Files:** Create `app/agents/master/action_binding.py`, `tests/test_action_binding.py`; modify `app/agents/master/turn.py`, `resolution.py`, `app/tools/registry.py`.

**Interfaces:**
- `ToolActionBinding(ref: ActionRef, role: Literal['prepare', 'check', 'consequence', 'finish'])` в contracts.
- `bind_tool_action(ctx: ToolContext, name: str, args: dict, explicit: ActionRef | None = None) -> ToolActionBinding | None`.
- Зарезервированный аргумент обычных LLM-инструментов `action_ref`; извлечь из raw args до валидации handler, автоматически добавить в опубликованную JSON schema только подходящих инструментов. Внутренние вызовы execute не требуют этого поля.
- `capture_attempt(ctx, binding: ToolActionBinding, raw: dict) -> str`: вместо выбора по actor_id; ключ возвращается для точной части. `permit_repair(ctx, ref: ActionRef) -> bool`.

- [x] Написать тесты `test_explicit_cast_selects_second_part`, `test_two_messages_same_actor_require_source`, `test_ambiguous_check_changes_nothing`, `test_wrong_target_or_foreign_ref_changes_nothing`, `test_auxiliary_world_call_does_not_claim_player_part`, `test_tool_schema_accepts_metadata_without_handler_field`. Проверять отсутствие новых событий/расхода при отказе привязки.
- [x] Запустить `tests/test_action_binding.py` и увидеть FAIL.
- [x] Реализовать таблицу совместимости по фактическому REGISTRY и IntentAction: actor, verb, spell_id, цели, skill; неизвестное соответствие не угадывать. До execute валидировать текущий ход и обязательные ссылки. Ошибка неоднозначности возвращает модели кандидатов. Отдельно разрешить явно вспомогательные вызовы; они не получают завершение или fallback заявки.
- [x] Серверный маршрут выбирает ActionRef исходного действия; не использовать только tuple(hero, spell). Модель получает refs в списке заявок. adjudicate_action использует уже существующий proposal.ref, без второго идентификатора.
- [x] Запустить `tests/test_action_binding.py tests/test_resolution_safe_failure.py tests/test_resolution_end_to_end.py tests/test_master.py`; PASS. Коммит: `feat: bind tool calls to verified action parts`.

### Task 3: Повторы и расход ресурсов по ActionRef

**Files:** Modify `app/tools/resolution/requests.py`, `app/tools/registry.py`, `app/agents/master/turn.py`; test `tests/test_resolution_replay.py`, new `tests/test_multipart_replay.py`.

**Interfaces:** `action_tool_key(ref: ActionRef, name: str, role: str) -> str`. Для основной проверки роль `primary_check`; ключ не включает изменяемые моделью DC/stat/call_id. Для cast ключ включает ActionRef и имя инструмента, а не только героя/spell_id.

- [ ] Написать `test_same_part_new_call_id_rolls_once`, `test_two_search_parts_have_distinct_rolls`, `test_two_cast_parts_spend_separately_but_replay_spends_once`, `test_concurrent_same_part_has_one_effect`. Проверять счётчик dice, slots и количество событий.
- [ ] Запустить `tests/test_multipart_replay.py`; FAIL.
- [ ] Перевести bound_tool_key и routed_casts на проверенную привязку задачи 2. Блокировать источник до чтения cache; обновлять мир существующим refresh_world. Не объединять refs кандидатов. Последствия одного действия с разными предметами сохраняют собственные operation/call keys; нельзя склеивать все place_item одной части.
- [ ] Проверить replay не только эффекта, но и восстановления прогресса по возвращённой квитанции. Вспомогательные вызовы без заявки сохраняют прежние keys.
- [ ] Запустить оба файла replay и `tests/test_resolution_busy.py tests/test_resolution_executor.py`; PASS. Коммит: `fix: scope action replay and resource spending to parts`.

### Task 4: Завершение многошагового действия и поиск

**Files:** Create `app/agents/master/action_progress.py`, `tests/test_multipart_progress.py`; modify `searches.py`, `resolution.py`, `turn.py`, `app/tools/registry.py`, `app/tools/narrative/evidence.py`.

Дополнительно изменить `app/tools/master/items.py` (handler use_item) и `app/tools/master/places.py` (handler edit_sketch): структурированная причина отсутствия механики и проверенная привязка unlock к части/цели.

**Interfaces:**
- `apply_tool_progress(ctx: ToolContext, binding: ToolActionBinding, raw: dict) -> None`.
- `unresolved_searches(ctx: ToolContext) -> list[ActionRef]` для разобранных заявок; legacy проверки обслужить отдельным путём без ложного ActionRef.
- `finalize_action_parts(ctx: ToolContext) -> list[tuple[ActionRef, ActionProgress]]`: обработать только незавершённые части.

- [ ] Написать тесты `test_cast_and_search_discovery_complete_both`, `test_successful_search_waits_for_world_confirmation`, `test_failed_search_completes_without_reroll`, `test_discovery_cannot_complete_second_search`, `test_auto_success_cannot_overwrite_failed_check`, `test_argument_error_allows_one_repair_per_part`.
- [ ] Добавить `test_staff_lever_alternative_path_completes_same_action`: одна цель, use_item посоха без механики отклонён, roll_check Силы 13 против 10 и edit_sketch unlock применены; ActionProgress.completed и события относятся к той же ActionRef/проходу, отказ остаётся в attempts. `test_lever_check_without_unlock_is_not_completed`: бросок без подтверждённого изменения не объявляет проход открытым. `test_neighbor_unlock_does_not_complete_failed_item_action`: другая часть/цель не заимствует успех.
- [ ] Запустить `tests/test_multipart_progress.py`; FAIL.
- [ ] Зафиксировать роли фактически используемых инструментов: cast/attack/move окончательные при законном результате; search roll — промежуточный при успехе, окончательный при игровом провале; связанные learn_fact/reveal_knowledge/place_item подтверждают поиск по check event и части. auto_success требует однозначную привязку и не подменяет существующий бросок.
- [ ] closes_actions не закрывает героя с required_actions напрямую. Ошибки аргументов пишут попытку; законный окончательный отказ получает denied. Незавершённый успешный поиск получает unhandled с причиной отсутствия подтверждения. Сохранить rollback и запреты fallback; capture_attempt не создаёт у составной заявки unbound успешных попыток.
- [ ] В use_item выделить структурированный `failure.code='item_use_unsupported'` для существующего предмета без механики; не менять категорию отказа ради выдачи fallback. `missing_content`, отсутствие владения/количества и запреты правил не получают этот код. Попытка инструмента с этим кодом не терминальна для цели «использовать как рычаг»; обычные разрешённые roll_check и unlock могут завершить эту цель. Добавить роль consequence для edit_sketch unlock с проверкой прохода и связи с проверкой; не считать любой edit_sketch завершением заявки.
- [ ] Проверить evidence использует event_ids только завершённой части. Запустить новый файл и `tests/test_adjudication.py tests/test_narrative_master.py tests/test_resolution_safe_failure.py`; PASS. Коммит: `fix: finalize multipart actions from verified outcomes`.

### Task 5: Порядок и явные зависимости

**Files:** Modify `app/agents/intent.py`, `app/tools/resolution/requests.py`, `app/agents/master/turn.py`; create `app/agents/master/action_order.py`, `tests/test_action_order.py`; test `tests/test_intent.py`.

**Interfaces:** IntentAction получает `summary: str = ''` (max_length=160), `depends_on: list[ActionDependency] = []` через default_factory. `ready_action_refs(ctx: ToolContext) -> list[ActionRef]`; `blocked_dependencies(ctx: ToolContext, ref: ActionRef) -> list[int]`. bind_message_actions сохраняет summary/dependencies вместе с действием.

- [ ] Написать тесты `test_lighting_dependency_reorders_search`, `test_plain_and_does_not_imply_success_dependency`, `test_independent_action_after_denial_is_ready`, `test_dependent_action_after_denial_is_blocked`, `test_cycle_and_missing_part_rejected`, `test_nine_actions_are_not_silently_truncated`. Старый intent без полей остаётся валиден.
- [ ] Запустить `tests/test_action_order.py tests/test_intent.py`; FAIL новых тестов.
- [ ] Парсер описывает порядок действий и явные dependencies; валидатор проверяет диапазон ссылок/цикл после полного разбора. Невалидные или >8 действий дают problem=unclear и вопрос о разделении заявки, без частичного исполнения; не обрезать массив. Условное «если» вне поддержанной зависимости требует уточнения, а не обещания будущего выполнения.
- [ ] Автомаршрут исполняет только готовую часть и не перескакивает через предыдущий влияющий на мир шаг. Перед модельными шагами адаптер повторно проверяет dependencies и текущую цель/место. applied означает выполненный эффект, success — выполненный эффект с успешным игровым исходом. Независимые продолжаются; заблокированным сохранять причины.
- [ ] Запустить тесты задачи плюс `tests/test_master.py tests/test_resolution_policy.py`; PASS. Коммит: `feat: order explicit dependencies in multipart requests`.

### Task 6: Конкретный остаток заявки в повествовании

**Files:** Modify `app/agents/master/narration.py`, `outcomes.py`, `turn.py`; test `tests/test_narration_playtest.py`, create `tests/test_multipart_narration.py`.

**Interfaces:** `public_action_notice(ctx: ToolContext, ref: ActionRef, progress: ActionProgress) -> str | None` в action_progress; возвращает пометку для denied/blocked/unhandled, completed не даёт предупреждения.

`failed_item_action(ctx: ToolContext, attempts: list[dict] | None) -> bool` в outcomes: использовать структурированные отказы, семантику предмета и привязанные результаты. Обновить все callers и тесты прежней сигнатуры. Точные сведения брать из серверного каталога/событий, не из текста прозаического ответа.

- [ ] Написать `test_completed_multipart_has_no_partial_cancel`, `test_only_search_left_names_search`, `test_blocked_contents_names_unopened_container`, `test_hidden_failure_notice_does_not_expose_dc_or_secrets`, `test_one_denial_preserves_other_committed_facts`.
- [ ] Добавить `test_staff_lever_preserves_story_after_unsupported_use`: воспроизвести инструменты хода `t_0409b05abb07b13b` и контролируемый рассказ об открытом проходе; assert рассказ сохранён, `audit.get('item_fallback')` ложно, служебной сводки и partial_cancel нет. Изолировать детектор имён корректным текстом без «Сл 10»: его исправление — отдельная задача.
- [ ] Добавить `test_missing_consumable_still_blocks_invented_consumption`, `test_failed_transfer_still_blocks_invented_transfer_after_neighbor_success`, `test_unlock_does_not_prove_consumption`, `test_unsupported_use_without_completion_does_not_claim_success`. Проверять все give_item/pass_item/pick_up_item/drop_item и use_item с механикой, сохраняя защиту от выдуманных операций.
- [ ] Запустить `tests/test_multipart_narration.py tests/test_narration_playtest.py`; FAIL новых тестов.
- [ ] Передать повествованию результаты по частям. Заменить общую пометку partial_cancel конкретными уведомлениями; summary использовать только как название действия, не доказательство или причину. При пустой summary брать безопасное название verb. Причины выводить по публичной карте reason_code, без raw errors; соблюдать существующий secrets_visible. Обновить auto_cancel на ссылки частей; оставить legacy поведение сообщений без них.
- [ ] failed_item_action не включает item_fallback для `item_use_unsupported` существующего предмета без механики; окончательный успех цели подтверждается через прогресс задачи 4. При отсутствии такого успеха показывать конкретный незавершённый итог цели. Сохранить консервативную проверку неподтверждённых передач и применения расходников; не отключать её по факту любого успешного действия героя и не сравнивать текст ошибок.
- [ ] Повторить тесты плюс `tests/test_narration_integrity.py tests/test_resolution_visibility.py`; PASS. Коммит: `fix: report exact unresolved player actions`.

### Task 7: Сквозная регрессия, восстановление и документация

**Files:** Create `tests/test_multipart_actions.py`; modify `tests/resolution_helpers.py`, `docs/master-resolution.md`.

**Interfaces:** `prepare_actions(ctx, hero_id: str, actions: list[dict]) -> tuple[Message, list[ActionRef]]` в resolution_helpers; существующий prepare_action остаётся совместимым.

- [ ] Написать сквозные тесты на существующем game_client: реальная двухчастная заявка search+cast, подтверждение предметом; assert обе части completed, нет auto_cancel/partial_cancel, события заклинания/броска/находки по одному. Подмена текста рассказа без событий не считается выполнением.
- [ ] Добавить `test_turn_rollback_reverts_effects_and_progress`, `test_recovery_after_effect_before_publication_does_not_repeat`, `test_combat_multipart_cannot_gain_extra_action`, `test_scene_change_does_not_retarget_old_request`, `test_old_single_action_and_unparsed_custom_still_work`. Проверять сохранённую БД через новую сессию.
- [ ] Запустить новый файл до реализации недостающей интеграции; подтвердить FAIL либо документировать, что сценарий уже покрыт работающими задачами 1–6, без искусственного изменения кода.
- [ ] Завершить интеграцию и обновить docs/master-resolution: refs, роли, статусы, dependencies, replay, отказ при неоднозначности, совместимость и лимит 8. Согласовать найденные конфликтующие ожидания старых тестов с утверждённой спецификацией, не удалять защитные проверки.
- [ ] Запустить `tests/test_multipart_actions.py tests/test_action_binding.py tests/test_action_order.py tests/test_multipart_progress.py tests/test_multipart_replay.py tests/test_multipart_narration.py` и существующие `tests/test_resolution_*.py tests/test_adjudication.py tests/test_intent.py tests/test_master.py tests/test_narration_playtest.py tests/test_narration_integrity.py tests/test_narrative_master.py`. Передать pytest развернутый список файлов через PowerShell Get-ChildItem, не рассчитывать на shell glob expansion.
- [ ] Выполнить существующие PostgreSQL конкурентные тесты с тестовым DATABASE_URL по fixtures проекта; SQLite не доказывает корректность PostgreSQL row locks. При недоступном тестовом PostgreSQL явно записать ограничение, не использовать рабочую игровую базу.
- [ ] Запустить `.venv\Scripts\python.exe -m ruff check` на изменённых Python-файлах и полный pytest по принятым настройкам проекта. Записать результаты, проверить адресный diff на посторонние изменения. Коммит: `test: cover multipart player action lifecycle`.

## Самопроверка плана

Покрытие спецификации: идентичность/контекст — 1–2; replay/транзакции — 3 и 7; поиск/итоги и альтернативные попытки одной цели — 4; зависимости/порядок — 5; публичные причины/секретность и регрессия посоха без потери защиты инвентаря — 6; совместимость/боевые регрессии — 7. Все пять Review Focus привязаны к тестам. Интерфейсы используют один ActionRef; терминальный отказ не записывается как успешное evidence. Ложное имя «Сл 10» вне объёма. Продуктовый код и тесты при подготовке плана не изменены.

## Передача в исполнение

Рекомендовано последовательное исполнение в этой сессии через executing-plans: привязка, replay и завершение используют общие интерфейсы. До реализации пользователь проверяет план и выбирает последовательное исполнение либо исполнение с отдельными агентами и проверками задач. Развёртывание в работающую игру в этот план не входит.
