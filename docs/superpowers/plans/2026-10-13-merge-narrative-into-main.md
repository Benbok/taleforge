# Слияние `feat/narrative-adaptation` с `main`

> Для исполнителя: шаги выполнять по порядку, каждый завершать коммитом и
> проверкой. `main` не двигать до зелёного шага 7. Рабочую базу Docker не
> мигрировать до шага 9 и только после резервной копии.

## Исходное положение (2026-10-13)

| | |
| --- | --- |
| Общая база | `24e2676` docs: plan narrative adaptation in verifiable releases |
| `main` | `3080ca4`, +43 коммита: вторая поставка карт локаций. Локальный, `origin/main` отстаёт на 45 коммитов |
| `feat/narrative-adaptation` | `8560c2b` (или новее), +73 коммита: адаптация сюжета F1–F12, исправления плейтеста |
| Единственная постоянная база | Docker `taleforge-db-1` (PostgreSQL, pgvector/pg16), ревизия **`0023` ветки**; в ней живые кампании |
| Другие серверы с `main` | нет (подтверждено пользователем) |

Worktree с `main`: `D:/Workspace/Projects/taleforge-worktrees/location-maps-merge`.
Не трогать чужие worktree в `.superpowers/worktrees/`.

## Миграции — ключевое решение

Номера ревизий совпадают, содержимое разное:

| Ревизия | `main` (карты) | ветка (сюжет) |
| --- | --- | --- |
| `0021` | `location_layout_phases`: `DELETE FROM world_generation_states WHERE phase IN ('location_layout','location_geometry')` | `narrative_foundation`: таблицы `narrative_states/facts/threads` |
| `0022` | `map_memories`: таблица `map_memories` + индексы | `narrative_work`: таблица `narrative_work` + индексы |
| `0023` | — | `user_menu_audio`: колонки `users.menu_music_enabled/volume` |

Таблицы не пересекаются. **Номера ветки сохраняются** (на `0023` стоит рабочая
база с играми). Миграции карт перенумеровать:

- `0021_location_layout_phases.py` → `0024_location_layout_phases.py`,
  `revision = "0024"`, `down_revision = "0023"`;
- `0022_map_memories.py` → `0025_map_memories.py`,
  `revision = "0025"`, `down_revision = "0024"`.

Итоговая цепочка: `0020 → 0021 → 0022 → 0023` (сюжет) `→ 0024 → 0025` (карты).
Рабочая база обновится обычным `alembic upgrade head` без ручного `stamp`.
Проверить, что в коде/тестах `main` нет ссылок на ревизии `"0021"`/`"0022"`
карт (`grep -rn '"002[12]"' app tests alembic`).

## Шаг 1. Зелёная ветка до слияния

На `feat/narrative-adaptation` падают 12 сценарных тестов (известно,
см. сообщение коммита `0dcf048`):

- `tests/test_intent.py::test_parser_garbage_passes_through`
- `tests/test_ai_players.py::test_ai_player_answers_once_after_master`
- `tests/test_ai_players.py::test_vote_hands_hero_to_ai_and_back`
- `tests/test_narrative.py::test_stalled_party_gets_new_opportunity`
- `tests/test_narrative_gate_d.py::test_alliance_future_job_next_scene_and_reconnect`
- `tests/test_offline.py::test_vote_hands_hero_to_other_player_and_back`
- `tests/test_offline.py::test_live_master_leaves_ai_takes_over_and_gives_back`
- `tests/test_offline.py::test_waiting_for_replies_skips_absent_player`
- `tests/test_persona.py::test_chronicle_notes_edit_revert_and_reach_the_agent`
- `tests/test_party_split.py::test_split_party_has_own_chat_and_meets_again`
- `tests/test_tts.py::test_master_turn_skips_voice_when_tts_disabled_in_campaign`
- `tests/test_tts.py::test_text_channel_without_line_skips_voice_line_request`

Причина: сценарий ScriptedLLM отвечает мастеру `DONE` без инструмента,
закрывающего действие игрока. Сервер автоматически отменяет действие, а
рассказчик теперь публикует фактическую отмену (`audit.cancel_fallback`)
вместо сценарной прозы. Это намеренное поведение (п.1/5/21 отчёта
`docs/superpowers/reviews/2026-10-13-playtest-findings.md`).

Исправлять **сценарии**, не защиту: героям, чьё действие сценарий считает
выполненным, добавить осмысленный закрывающий вызов (`auto_success` с
`character_id`, `roll_check` и т. п.) перед `DONE`. Где тест проверяет саму
автоотмену — проверять отмену. Для Gate D и TTS сначала проверить порядок
ответов ScriptedLLM (запросы режиссёра идут в `llm.director_requests`, не в
общую очередь). Не ослаблять `public_factual_fallback` и не возвращать
прежний текст ради старого ожидания.

Готовность: полный `python -m pytest -n 4 -q` на SQLite — 0 failed.
Коммит: `test: close scripted actions in scenario tests`.

## Шаг 2. Ветка слияния

```powershell
git switch -c merge/narrative-into-main main
git merge --no-ff feat/narrative-adaptation
```

## Шаг 3. Конфликты

Ожидаемые (`git merge-tree --write-tree main feat/narrative-adaptation`):

| Файл | Суть |
| --- | --- |
| `app/core/world.py` | ветка: `narrative_view`, `narrative_entry/facts` в `World` и `load_world`; `main`: перемещение сцены/места групп карт. Сохранить обе стороны |
| `app/core/world_tx.py` | транзакции мира: обе ветки правили защиту ревизии. Сохранить семантику ветки (`world_write` для no_change не вызывается — executor) и изменения карт |
| `app/agents/master/checkpoint.py` | поля checkpoint: `adaptation_effects` (ветка) + поля карт |
| `app/core/world_generation/storage.py` | F5: точные `FactRef`/`SnapshotRef(kind=event)` (ветка) + фазы раскладки карт (`main`) |
| `app/tools/master/knowledge.py` | `learn_fact`: проверка `used_fact_refs` до записи (ветка, `5275add`) + изменения `main` |
| `.gitignore` | объединить |
| `docs/superpowers/plans/2026-10-12-location-maps-delivery1.md` | add/add: взять версию `main`, применить `ruff format` (ruff 0.16 форматирует блоки кода в Markdown) |

Автослитые файлы, изменённые обеими сторонами, — просмотреть дифф
вручную: `app/agents/master/finish.py`, `turn.py`, `app/core/plot_anchors.py`,
`app/core/world_generation/contracts.py`, `app/db/models.py`,
`app/gateway/protocol.py`, `app/gateway/ws.py`, `app/tools/master/places.py`,
`app/tools/plot.py`, `app/tools/registry.py`, `web/src/game/MapWindow.tsx`.
Особое внимание: `ws.py` — у ветки обработка `WorldConflict` в `map.step`
(`cc912dd`), у `main` новые обработчики карты; `registry.py` — internal grant
и `narration_viewer_ids` (ветка) рядом с изменениями карт.

`web/openapi.json` и `web/src/lib/api.gen.ts` не сливать вручную: после
разрешения — `python -m app.contract` и `npm run gen:api`.

Коммит слияния после зелёных шагов 4–6 (можно отдельными фикс-коммитами
поверх merge-коммита).

## Шаг 4. Миграции

Перенумерация по разделу выше. Проверки на **отдельной** базе
(временный контейнер, не `taleforge-db-1`):

```powershell
docker run -d --name tf-merge-pg -e POSTGRES_USER=tf -e POSTGRES_PASSWORD=tf -e POSTGRES_DB=merge_test -p 55433:5432 postgres:16-alpine
$env:DATABASE_URL = "postgresql+asyncpg://tf:tf@localhost:55433/merge_test"
alembic upgrade head; alembic check; alembic downgrade base; alembic upgrade head
alembic heads   # ровно одна голова: 0025
```

Затем **копия рабочей базы**:

```powershell
docker exec taleforge-db-1 pg_dump -U taleforge -Fc taleforge > merge-copy.dump
docker exec -i tf-merge-pg createdb -U tf live_copy
docker exec -i tf-merge-pg pg_restore -U tf -d live_copy --no-owner < merge-copy.dump
$env:DATABASE_URL = "postgresql+asyncpg://tf:tf@localhost:55433/live_copy"
alembic current   # 0023
alembic upgrade head   # 0023 -> 0024 -> 0025 без ошибок
alembic check
```

Дамп содержит игровые данные: хранить вне репозитория, удалить после проверки.

## Шаг 5. Тесты сервера

- `ruff check .`, `ruff format --check .` (включая Markdown);
- полный `python -m pytest -n 4 -q --timeout 300` на SQLite — 0 failed;
- полный прогон на PostgreSQL: `TEST_DATABASE_URL=postgresql+asyncpg://tf:tf@localhost:55433/merge_pytest`
  (у каждого xdist-воркера своя база; фикстура `_postgres_test_loops` даёт NullPool);
- обязательно зелёные: `test_narrative_startup.py`, `test_narrative_gate_d.py`,
  тесты карт `main` (`test_map*.py`, `test_steps.py`, тесты map memories/transit),
  `test_narrative_canon_readers.py` (читатели канона против изменений `load_world`).

## Шаг 6. Контракт и клиент

```powershell
python -m app.contract; python -m app.contract --check
cd web; npm run gen:api; npx tsc --noEmit -p .; npx vitest run; npm run build
```

Проверить, что diff `openapi.json`/`api.gen.ts` объясним объединением двух
веток (поля карт + поля сюжета, `narrative_mode` default `adaptive`).

## Шаг 7. Живая проверка на копии базы

Поднять приложение на базе `live_copy` (не на рабочей): отдельный
`docker compose` с `DATABASE_URL` на `tf-merge-pg` или локальный `uvicorn`
с этим URL и `GEMINI_*` из `.env`.

- открыть существующую кампанию из копии: карта, сцена, история на месте;
- новая адаптивная кампания: вступление, ход, переход между помещениями
  с картой (поставка 2 карт), закрытие узла → задание режиссёра → квитанция;
- в логах нет `Traceback`, `WorldConflict` в WebSocket не рвёт соединение.

## Шаг 8. Перевод `main`

```powershell
git switch main
git merge --ff-only merge/narrative-into-main
```

Пуш в `origin` — только по решению пользователя (`origin/main` сейчас
отстаёт на 45 коммитов).

## Шаг 9. Выкатка на рабочую базу

Только с согласия пользователя, в перерыве между играми:

1. `docker exec taleforge-db-1 pg_dump -U taleforge -Fc taleforge > backup-before-merge.dump`
   (вне репозитория);
2. рабочее дерево на `main`; `docker compose up -d --build app`
   (образ копирует `alembic/` при сборке — пересборка обязательна);
3. в логе старта: `alembic upgrade` 0023 → 0025, `Application startup complete`;
4. `docker exec taleforge-db-1 psql -U taleforge -d taleforge -tAc "select version_num from alembic_version"` → `0025`;
5. обновить страницу клиента; короткий ход в живой кампании.

Откат: `pg_restore` из `backup-before-merge.dump` и образ с прежнего коммита.

## Риски

- `load_world` и транзакции мира изменены обеими ветками: ошибка слияния
  проявится как `WorldConflict` или потеря `narrative_view` — ловят
  `test_narrative_canon_readers.py` и тесты карт.
- Фоновый режиссёр живой в `create_app`; тестовая фикстура `client`
  отключает его (`tests/conftest.py`). Если тесты карт `main` создают
  приложение иначе, их ScriptedLLM может получить запросы режиссёра —
  ответы режиссёра идут в `director_requests`, но проверить.
- `narrative_mode` по умолчанию `adaptive` для процедурных кампаний:
  тесты `main`, ожидающие strict-поведение мастера, могут потребовать
  явного `narrative_mode="strict"` (как `test_lead.py`, `b3b9397`).
