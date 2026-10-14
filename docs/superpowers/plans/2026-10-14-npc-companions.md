# NPC Companions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** NPC следует за одним героем, действует в его боевой слот и отображается спутником во всех публичных представлениях отряда.

**Architecture:** Единственный источник связи — `Entity.state.companion`. Общий модуль управляет поиском, переносом, разрывом и публичной проекцией; инструменты используют существующие события и откат. Экономика спутника отдельная, но привязана к слоту героя; рассылка использует существующие `character.updated` и `scene.updated`.

**Tech Stack:** Python, SQLAlchemy async, Pydantic, pytest; React, TypeScript, Zustand, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-14-npc-companions-design.md`, согласована пользователем 2026-10-14.

## Global Constraints

- Форма связи: `{"of": "ch_…", "since_event": "ev_…", "reason": "…"}`; без миграции БД.
- Нет собственной инициативы и места в очереди; одна атака за действие, своё перемещение.
- Потеря сознания героя сохраняет связь и совместный слот; окончательное выбытие разрывает связь.
- Публичная форма: `companions: [{id, name, hp, hp_max, down, dead}]`; без отношения и секретов каркаса.
- `zone=near` после перехода; клетка, сторона, укрытие и высота сбрасываются.
- Все мутации обратимы вместе с ходом; никакого отдельного канала состояния спутников.
- Сохранить существующие незакоммиченные изменения. Не менять `.env` и не выводить секреты подключения.
- Привязку Корвина считать выполненной только после проверки в реальной игровой БД.

## Review Focus

1. Повторная синхронизация того же слота не обновляет спасбросок от смерти и не освобождает действие спутника — задача 4.
2. NPC из другой локации не телепортируется за владельцем; разделение не раскрывает скрытые сущности — задачи 2 и 5.
3. Предатель с инициативой выше текущего героя не сбивает текущего участника и его расходы — задача 4.
4. Переподключение и повтор одинакового `character.updated` не создают уведомления о вступлении — задача 6.
5. Повторная адресная привязка текущей игры не создаёт новую связь или второе событие — задача 7.

## Рабочее место и порядок

Порядок задач: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Это одна связная фича; задачи не являются отдельными релизами.

Перед реализацией проверить `git status`, текущую ветку и инструкции каталога. На этапе подготовки текущая ветка — `feat/location-maps-delivery3`, рабочее дерево содержит важные изменения. Изоляция должна сохранять эту фактическую базу, а не начинаться с одного HEAD: предпочтительна копия текущего дерева в игнорируемый каталог внутри разрешённого workspace с последующим адресным переносом результата; не выполнять сбросы и не включать чужие изменения в коммиты. Использовать навык using-git-worktrees для выбора доступного способа изоляции. Если реализация ведётся непосредственно в существующей ветке по указанию пользователя, зафиксировать это решение в журнале.

Создать журнал `.superpowers/sdd/2026-10-14-npc-companions/progress.md`, первая строка — путь этого плана; записывать завершённые задачи, результаты проверок и решения. Коммиты/публикацию не смешивать с чужими изменениями; итог оставить доступным для просмотра в основном workspace.

### Task 1: Связь, инструменты и автоматический разрыв

**Files:** Create `app/core/companions.py`, `app/tools/master/companions.py`, `tests/test_companions.py`; modify `app/tools/master/__init__.py`, `app/tools/runtime.py`, `app/agents/master/outcomes.py`, `app/core/master_panel.py`.

**Interfaces:**
- `companions_of(world, hero_id: str, *, place: str | None = None) -> list[Entity]`: действующие связи, исключает погибших, бежавших и враждебных.
- `public_companions(entities, hero_id: str) -> list[dict]`: только шесть публичных полей.
- `break_companion(ctx, entity, reason: str, *, turn_hostile: bool = False) -> dict`: событие разрыва, inverse, уведомление существующей рассылки; внутренний общий путь.
- `reconcile_companions(ctx, result: dict | None = None) -> None`: идемпотентно снимает недействительные связи и помечает владельцев изменившихся NPC для рассылки хитов.
- Аргументы `join_party(entity_id, hero_id, basis_event_id, reason)` и `leave_party(entity_id, reason, turn_hostile=false, plot_id=null, betrayal_note=null)`.

- [ ] Написать тесты `test_join_requires_current_hero_evidence`, `test_join_rejects_failed_or_superseded_check`, `test_companion_cannot_be_claimed_twice`, `test_hostile_cannot_join`, `test_neutral_join_becomes_friendly`, `test_leave_betrayal_requires_own_plot_or_note`, `test_automatic_break_is_recorded_once`, `test_companion_changes_are_reversible`. Использовать `_play`, `_ok`, `party`, `QueueDice`; основания создавать реальным `roll_check`/`pass_item`. Проверять `ok=false` и неизменённый state для отказов; `companion.of == hero.id`, `since_event == basis.id` для успеха.
- [ ] Запустить `.venv/Scripts/python.exe -m pytest tests/test_companions.py -q`; убедиться, что провал связан с отсутствием новых инструментов.
- [ ] Реализовать схемы и инструменты: обязательные непустые причины, проверка actor/target/turn основания, последней социальной проверки, дружелюбность нейтрального, запрет перехвата. Сделки подтверждаются имеющимися событиями `pass_item`, а не произвольным текстом. Зарегистрировать инструменты и хук `AFTER_CALL` по примеру `app/tools/progress.py`. Вызывать сверку также перед финальной фиксацией хода: выбытие героя вне инструментов тоже должно снять связь. Включить новые события в факты повествования и доступность живому мастеру.
- [ ] Повторить тесты до PASS; проверить, что один разрыв даёт ровно одно событие и что чужой `plot_id` не принимается.

### Task 2: Перенос и разделение отряда

**Files:** Modify `app/core/companions.py`, `app/tools/master/places.py`; test `tests/test_companions.py`, `tests/test_layout_transit.py`, `tests/test_layout_develop.py`, `tests/test_party_split.py`.

**Interfaces:** `bring_companions(ctx, heroes: list[Character], loc: Entity, inverse: list) -> list[Entity]`; использует исходные места героев до их изменения.

- [ ] Написать `test_companion_follows_each_transition` для `move`, `create_location(make_current)`, `develop(here)`, `traverse_passage`, `test_only_departing_heros_companions_follow`, `test_remote_companion_is_not_teleported`, `test_companion_position_and_move_rollback`. В итоге проверять нужный `location_id`, `zone == "near"`, отсутствие `cell/bearing/cover/elevation`; после отката — точное прежнее состояние.
- [ ] Запустить эти тесты и зафиксировать ожидаемые провалы переноса.
- [ ] Реализовать helper и вызвать до изменения мест героев в `move_heroes` и `relocate_scene`. `transit.finish` уже использует `move_heroes`; отдельно helper там не вызывать. Сохранить inverse и инвалидировать actor; проверить, что `_reset_positions` и `_arrive` не восстанавливают старую геометрию NPC.
- [ ] Запустить новые тесты и существующие тесты переходов/разделения до PASS.

### Task 3: Собственное действие и перемещение спутника

**Files:** Modify `app/core/economy.py`, `app/core/companions.py`, `app/tools/master/checks.py`, `app/tools/master/places.py`; test `tests/test_companion_combat.py`, существующие тесты экономики и перемещения.

**Interfaces:** `economy.active(world, actor_id)` допускает спутника текущего героя только в том же месте боя; `ledger`, `charge_attack`, `charge_movement`, `moved_ft`, `view` используют ID NPC, но метку слота героя.

- [ ] Написать `test_companion_attack_spends_own_action`, `test_second_companion_attack_is_rejected`, `test_companion_cannot_act_on_other_hero_turn`, `test_companion_movement_is_independent_and_cumulative`, `test_down_companion_cannot_act`, `test_sync_does_not_reset_companion_spending`. После атаки действие героя свободно, действие спутника потрачено; повтор и чужой слот дают отказ без мутации.
- [ ] Запустить тесты; убедиться в провале бесплатной второй атаки на текущей реализации.
- [ ] Обобщить проверки экономики и получение имени/статов через actor вместо безусловного доступа к `world.characters`. Для NPC оставить ровно одну атаку за действие. Проверки слот/сознание выполнять до броска и мутации. В `reposition` учитывать расход движения спутников так же, как героев; свободное внебоевое движение и автоматические ходы обычных врагов сохраняются.
- [ ] Запустить новый набор и существующие наборы экономики/движения до PASS.

### Task 4: Совместный боевой слот, цели врагов и предательство

**Files:** Modify `app/core/combat.py`, `app/tools/master/checks.py`, `app/tools/master/places.py`, `app/agents/master/turn.py`, `app/core/companions.py`, `app/tools/master/companions.py`, `app/agents/prompts/master_system.j2`; test `tests/test_companion_combat.py`, `tests/test_master.py`, существующие тесты боя.

**Interfaces:** `combat.public_order` добавляет вложенный `companions` к записи героя; `run_until_hero` возвращает контекст совместного слота без дополнительного вызова модели; текущие `combat.insert/drop` управляют предателем и сохраняют активный слот.

- [ ] Написать `test_companion_has_no_initiative_entry`, `test_hero_turn_mentions_companion`, `test_no_companion_calls_leave_it_idle`, `test_unconscious_hero_keeps_companion_slot`, `test_death_save_runs_once_per_slot`, `test_living_companion_keeps_front_open`, `test_enemy_targets_weakest_companion`, `test_grid_enemy_can_target_companion`, `test_betrayal_rolls_initiative_and_preserves_current_turn`, `test_former_companion_uses_enemy_behavior`. Проверять отсутствие ID спутника в `scene.turn_order`, наличие в публичной вложенной форме; после предательства — ID в очереди и последующая реальная атака врага.
- [ ] Запустить тесты и подтвердить провалы отдельных инициатив/пропущенного слота/выбора целей.
- [ ] Исключить связанные существа в `roll_initiative` и входе в бой. Расширить выбор противников на стоящих героев и спутников того же места. В `close_fronts` учитывать действующих спутников, не меняя `_hostiles_left`. В `run_until_hero` выполнять спасбросок героя один раз, инициализировать слот для доступных спутников даже при герое без сознания, добавлять пометку и оставлять действия мастеру. Проверить существующие opening attack/spell/plan, раннее закрытие действий и завершение хода: действие героя не должно лишать мастера возможности действовать спутником в том же решении.
- [ ] При предательстве снять связь, затем бросить инициативу и вставить врага только в существующий бой его локации. Не исполнять его вражеский ход из `leave_party`. Записать обратные снимки очереди/state и состояние связи. Обычный уход прекращает совместные действия. Промпт описывает инструменты, требования основания и совместный слот, предательство только через `leave_party`.
- [ ] Запустить тесты до PASS; ScriptedLLM-тест подтверждает один вызов принятия решения для действий героя и спутника.

### Task 5: Публичный протокол, сцена и карта

**Files:** Modify `app/core/views.py`, `app/core/characters.py`, `app/api/characters.py`, `app/gateway/ws.py`, `app/tools/runtime.py`, `app/gateway/protocol.py`, `app/core/world.py`, `app/core/scene_view.py`, `app/core/map.py`, `web/src/lib/types.ts`; test `tests/test_companion_protocol.py`, `tests/test_scene_model.py`, `tests/test_ws.py`, `tests/test_map.py`.

**Interfaces:** `CompanionPublic(Strict)` с `id/name/hp/hp_max/down/dead`; `HeroPublic.companions` — список, по умолчанию пустой. `public_view(ch, *, entities=()) -> dict`, `full_view(ch, cat, inventory, effects, *, entities=()) -> dict` сохраняют совместимость старых вызовов и позволяют серверным путям передать сущности кампании. Все пути отправки героя передают актуальные entities; проверять также submit/review/claim/bonds.

- [ ] Написать `test_snapshot_rest_and_updates_include_companions`, `test_companion_hp_update_refreshes_owner`, `test_join_leave_death_update_public_list`, `test_companion_projection_never_leaks_plot_secret`, `test_split_scene_filters_remote_companions`, `test_public_order_nests_companion_without_initiative`. Добавить секретный маркер в каркас NPC и проверить его отсутствие во всём JSON публичных представлений.
- [ ] Запустить тесты и подтвердить отсутствие companions в текущих ответах.
- [ ] Добавить строгую форму, сборку списка из entities и передачу entities во всех REST/WS/полных листах. Отправлять обновление героя при изменении NPC; после разрыва хранить прежний ID владельца для его обновления. Добавить безопасную метку связи в публичные данные сцены/карты и вложенную очередь; расширить строгие контрактные модели и клиентские типы одновременно.
- [ ] В `World.scene_table()` показать «Спутники: имя — идёт с героем (с хода …, причина)», используя только саму связь. Не присоединять секрет/мотив каркаса к этой строке.
- [ ] Запустить тесты до PASS; проверить строгий WS-контракт и существующие тесты скрытых сущностей.

### Task 6: Панель, очередь, карта, мобильный лист и уведомления

**Files:** Create `web/src/game/CompanionRows.tsx`, `web/src/game/CompanionRows.test.tsx`, `web/src/game/Panels.test.tsx`; modify `web/src/game/Panels.tsx`, `web/src/game/HeroWindow.tsx`, `web/src/game/CombatStrip.tsx`, `web/src/game/LocationMap.tsx`, `web/src/game/SketchSurface.tsx` если значки карты проходят через него, `web/src/stores/game.ts`; test store в существующем или новом `web/src/stores/game.test.ts`.

**Interfaces:** `CompanionRows({companions, heroName, acting})`; uses `useInspector.open(id, name, anchor)`; уведомления сравнивают ID спутников в прежнем и новом `HeroPublic`.

- [ ] Написать `renders_companions_below_hero_hp`, `opens_companion_inspector`, `renders_nothing_for_empty_companions`, `renders_multiple_companions_and_down_state`, `shows_companions_in_mobile_hero_sheet`, `nests_companions_in_combat_order`, `marks_companion_on_map`, `notifies_only_on_actual_membership_change`. Проверять компактные значения HP, имя/пометку, действие с героем, кликабельность и отсутствие пустой разметки. Под snapshot/repeated update — ноль уведомлений, join/leave — по одному.
- [ ] Запустить `npm --prefix web test -- <целевые файлы>` и убедиться в ожидаемых провалах отсутствующей строки.
- [ ] Реализовать переиспользуемые строки и вставить под хитами в панель/лист. Вложить спутников в визуальную запись очереди героя. Метку карты показывать рядом с владельцем без изменения серверной клетки и правил дистанции. Использовать существующий механизм toast из store; убрать строки при уходе/смерти, без показа секретной причины предательства.
- [ ] Выполнить целевые Vitest-тесты, `npm --prefix web run typecheck` и `npm --prefix web run build`; все должны завершиться успешно.

### Task 7: Адресная привязка Корвина в текущей игре

**Files:** Create `tools/link_existing_companion.py`, `tests/test_existing_companion_link.py`.

**Interfaces:** CLI `--campaign-id --entity-id --hero-id --basis-event-id --reason`, по умолчанию dry-run; `--apply` выполняет одну транзакцию с событием/inverse. Использует настроенную БД без вывода URL или секретов.

- [ ] Написать `test_historical_link_requires_exact_campaign_and_event`, `test_historical_link_preserves_since_event`, `test_historical_link_is_idempotent`, `test_dry_run_does_not_mutate`. Чужая кампания/герой/событие отклоняется; повтор не создаёт второй журнал; runtime `join_party` продолжает требовать текущий ход.
- [ ] Запустить тесты, подтвердить ожидаемый провал отсутствующего CLI.
- [ ] Реализовать адресный backfill отдельно от публичного инструмента. Прочитать идентификаторы нужной кампании и текст исходного хода через используемую конфигурацию; выбрать только подтверждённое основание «подхватил и повёл». Историческое событие не подменять вновь созданным. Если старый ход имеет только сообщение, выбрать относящееся к нему реальное событие и сохранить точную ссылку на сообщение в backfill-журнале; при отсутствии доказательства не применять.
- [ ] Выполнить dry-run с найденными ID, затем применить разрешённую пользователем привязку и прочитать её обратно. Если соединение недоступно, оставить CLI проверенным и явно отметить невыполненную игровую операцию; остальные задачи продолжить.

### Task 8: Итоговая проверка и передача результата

**Files:** Tests above; update this plan and its progress ledger.

- [ ] Запустить все новые backend-наборы одной командой pytest; затем затронутые существующие наборы боя, экономики, карты, переходов, сцены и мастера. Использовать отдельный тестовый tmp-каталог в workspace, не игровую БД.
- [ ] Запустить целевые frontend-тесты, typecheck, build. Расширять проверки только при новых изменениях или выявленных проблемах.
- [ ] Проверить дифф на соответствие спецификации, особенно секреты, сохранение старых изменений, повторные события и обход экономики. Независимый итоговый обзор — по выбранному пользователем способу выполнения; до него прочитать requesting-code-review и verification-before-completion.
- [ ] Исправить подтверждённые ошибки с регрессионным тестом, повторить затронутые проверки. Зафиксировать результат каждой задачи в журнале и отметить выполненные пункты.
- [ ] Передать изменения в основной workspace адресно, повторно проверить итоговый набор после переноса. В финальном ответе указать реализованное поведение, результаты проверок и отдельно фактический статус связи Корвина. Не публиковать и не сливать ветку без соответствующей команды пользователя.

## Выбор выполнения

Рекомендация: выполнение в этой сессии (Native). Серверные задачи тесно связаны через экономику, события и публичные формы; одна последовательная реализация упрощает сохранение существующих изменений. Альтернатива: subagent-driven с отдельными исполнителями и обзорами каждой задачи, ценой дополнительных контекстов и координации.

Статус: план подготовлен и проверен на покрытие согласованной спецификации; ожидает просмотра и выбора способа выполнения.
