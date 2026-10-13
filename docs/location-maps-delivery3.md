# Генеративные карты локаций, поставка 3: каркас, модель структуры, первая сцена и учёт расходов

Спецификация: `docs/superpowers/specs/2026-10-12-generative-location-maps-design.md` (§9, поставка 3; §3.1–3.2, §8, §10).
План: `docs/superpowers/plans/2026-10-12-location-maps-delivery3.md`.

## Что есть

- **Пространственный замысел в каркасе** (`app/core/layout/spatial.py`, `app/core/plot.py`): схема `SpatialPlan`
  (окружение `environment`, масштаб `scale`, обязательные части `parts` с `outdoor/below/secret/required/purpose`,
  подходы `approaches` с `kind/side`). Архитектор (`app/agents/architect.py`) генерирует `spatial` только для ключевых
  мест (1–2 на акт, без рутинных развилок), соблюдая лимиты (1–6 частей, 1–3 подхода, стороны `w/s/e`).
- **Мандат и обязательства** (`app/core/layout/spatial.py`): `Mandate` связывает пространственный план места с
  носителями сюжетных зацепок (`Holder(key, name)`) и NPC-жителями (`npc:<id>`). Функция `obligations` строго
  проверяет выполнение мандата любым замыслом: сохранение обязательных частей, тайности, уровней, привязок носителей,
  входного участка и подходов без внешних ссылок.
- **Лестница детерминированных замыслов** (`app/core/layout/spatial.py::intent_candidates`): детерминированный
  запасной вариант из 3 ступеней: (1) с полосой дороги у западного подхода → (2) без полос → (3) только первый подход.
  В сочетании с обычной раскладкой и `fallback=True` провайдера поставки 1 полностью устраняет риск тупика:
  1890 комбинаций параметров дают 0 блокировок.
- **Техническая модель структуры** (`app/agents/layout_model.py`): отдельный легковесный агент предлагает
  замысел комплекса (`LayoutIntent`) в рамках единого вызова инструмента `submit_layout`. Модель не касается
  геометрии и координат клеток: их рассчитывает `DeterministicLayoutProvider`. Ошибки мандата или валидации
  возвращаются модели текстом для ровно одной корректирующей попытки. В запросе модели нет секретов сюжета.
- **Подключение модели к фазе генерации** (`app/core/layout/executor.py`): фаза `location_layout` запрашивает
  структуру у технической модели при включённом флаге `location_layouts_llm`. Реализованы строгие защитные лимиты:
  бюджет контекста (6000 входных / 3000 выходных токенов), лимит бюджета кампании (`spend_limit_usd`), лимит
  попыток (`llm_attempt_count <= 2`). При любом исчерпании лимитов, синтаксической или семантической ошибке
  фаза автоматически переключается на детерминированную лестницу (`quality="fallback"` с диагностической заметкой).
- **Флаги кампании и разворот ключевых мест** (`app/core/layout/plan.py`, `app/config.py`): флаги `location_layouts`
  и `location_layouts_llm` управляют генерацией комплексов. Функция `develop_location_complex` разворачивает место
  каркаса в комплекс участков: бронирует фазу `location_layout` с мандатом в `state.blueprint`, откладывая наполнение
  `location_initial` до фиксации структуры.
- **Жители и носители зацепок** (`app/core/layout/executor.py`, `app/tools/plot.py`): при публикации структуры
  носители зацепок размещаются строго в назначенных участках комплекса. Жители-NPC (`npc:<plot_id>`) переносятся
  из корня в свои участки без потери данных и связей.
- **Первая сцена внутри комплекса** (`app/core/layout/entry.py`, `app/agents/prelude.py`): отряд входит во входной
  участок комплекса (`enter_complex`) **до** генерации вступительного повествования. Первая сцена создаётся на
  входном участке, исключая расхождение между рассказом мастера и местоположением героев на карте.
- **Подготовка вперёд без раскрытия** (`app/core/layout/ahead.py`, `app/core/layout/transit.py`): при переходе
  героев в новый участок сервер заранее подготавливает геометрию до 2 несекретных соседних участков
  (`AHEAD = 2`, только фаза `location_geometry`, без `location_initial`). Подготовка вперёд не создаёт записей
  в `MapMemory` и не раскрывает неисследованные участки игрокам.
- **Инструменты ведущего** (`app/tools/master/generation.py`):
  - `prepare_location`: явная подготовка всех участков комплекса с оценкой числа LLM-вызовов и опциональным
    наполнением (`furnish=True`).
  - `preparation_cost`: детальная сводка расходов на генерацию локации с группировкой по фазам (`location_layout`,
    `location_geometry`, `location_initial`) и агрегацией строк, вызовов, ошибок, токенов рассуждений, времени
    и стоимости в USD.
- **Учёт расходов по фазам** (`app/db/models.py`, `app/agents/llm.py`): таблица `llm_calls` расширена полями
  `generation_id` (внешний ключ на строку фазы `world_generation_state`) и `tokens_reasoning` (токены рассуждений
  моделей reasoning).

## Решения поставки

1. **Модель предлагает замысел, а не blueprint.** Модель формирует семантическую структуру (части, связи, проходы,
   детали, полосы рельефа), а координаты, края, стыки и геометрию считает детерминированный алгоритм поставки 1.
2. **Мандат фиксируется один раз при развороте.** Резерв фазы `location_layout` сохраняет неизменяемый `mandate`
   на момент разворота. Повторный вход или рестарт не пересчитывают мандат и не расходуют новые вызовы модели.
3. **Лестница детерминированных замыслов.** 3 ступени кандидатов в сочетании с алгоритмическим fallback
   гарантируют 100% надёжность генерации даже при полном отказе внешней модели.
4. **Изоляция сюжета от модели структуры.** В технический запрос к LLM передаются только публичное имя, атмосфера
   и топологические требования. Секреты локации, зацепок и NPC полностью скрыты.
5. **Вход до вступления первой сцены.** Фиксация героев на входном участке выполняется до вызова агента прелюдии,
   гарантируя синхронность нарратива и карты.
6. **Безопасная упреждающая подготовка.** Подготовка вперёд ограничена только геометрией соседних участков
   и не оставляет следов в личной памяти игроков (`MapMemory`).
7. **Обратная совместимость.** Старые кампании, книги приключений и кампании с выключенными флагами сохраняют
   прежнее поведение без создания комплексов и без изменения формата данных.

## Вне поставки

- **Дальние ориентиры и межкомплексные проходы** (спецификация §5): вынесены за рамки поставки 3, так как требуют
  глобальной топологии всего мира и сквозной навигации между удалёнными комплексами. Механика автономного
  комплекса, его геометрия, переходы и память карты полностью самодостаточны без глобальных ориентиров.

## Review Focus: подтверждение тестами

1. **Секреты каркаса в техническом запросе отсутствуют:**
   - `tests/test_layout_model.py::test_brief_carries_no_plot_secrets`
   - `tests/test_location_maps_delivery3.py::test_pilot_brief_has_no_plot_secrets`
2. **Повтор не тратит новые вызовы модели (0 новых вызовов структуры):**
   - `tests/test_layout_model_phase.py::test_restart_exhausted_layout_uses_fallback_without_llm`
   - `tests/test_opening_complex.py::test_repeat_open_does_not_reenter_or_duplicate`
   - `tests/test_location_maps_delivery3.py::test_pilot_round_trip_keeps_structure_and_costs_nothing_new`
3. **Порядок фаз (обстановка корня и носители не обгоняют структуру):**
   - `tests/test_layout_develop.py::test_develop_location_complex_creates_layout_reservation`
   - `tests/test_layout_residents.py::test_residents_and_anchors_assigned_to_complex_areas`
4. **Первая сцена (вход фиксируется до нарратива, сбой оставляет у корня):**
   - `tests/test_opening_complex.py::test_first_scene_starts_inside_complex_entry`
   - `tests/test_opening_complex.py::test_failed_layout_keeps_heroes_at_root`
5. **Подготовка без раскрытия (lookahead и prepare_location не светят неисследованное):**
   - `tests/test_layout_ahead.py::test_transit_requests_ahead_geometry_without_disclosing`
   - `tests/test_prepare_location.py::test_prepare_location_geometry_ahead_does_not_disclose_memory`
   - `tests/test_location_maps_delivery3.py::test_pilot_secret_vault_is_not_disclosed_by_preparation`
6. **Старые кампании и готовые модули не затрагиваются:**
   - `tests/test_layout_develop.py::test_develop_without_flag_or_spatial_keeps_simple_location`
   - `tests/test_prepare_location.py::test_prepare_location_refuses_simple_location`

## Команды воспроизведения тестов и живого замера

```bash
# Приёмочные тесты поставки 3
uv run pytest tests/test_location_maps_delivery3.py -q

# Все специализированные тесты поставки 3
uv run pytest tests/test_layout_mandate.py tests/test_layout_plan_phase.py tests/test_layout_model.py tests/test_layout_model_phase.py tests/test_layout_develop.py tests/test_layout_residents.py tests/test_opening_complex.py tests/test_layout_ahead.py tests/test_prepare_location.py tests/test_location_cost.py tests/test_llm_accounting.py -q

# Регрессионный срез смежных подсистем
uv run pytest tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_adventure.py tests/test_modules.py tests/test_layout_pilot.py tests/test_layout_turn.py tests/test_opening_scene.py tests/test_scene_model.py -q

# Полный прогон тестового набора backend
uv run pytest -q -n auto -rs

# Живой замер технической модели (требует ключи провайдера LLM)
TALEFORGE_LIVE_PILOT=1 uv run python tools/pilot_location_layout.py
```

## Таблица результатов прогонов

| Набор тестов / Замер | Результат | Примечания |
| --- | --- | --- |
| `tests/test_location_maps_delivery3.py` | **5 passed** (18 с) | Приёмочный сценарий храма и луга, обход проходов, изоляция тайн, учёт |
| Модульные тесты поставки 3 (11 файлов) | **64 passed** (42 с) | Мандат, модель, CAS исполнителя, перенос NPC, первая сцена, lookahead, расходы |
| Регрессионный срез (9 файлов) | **56 passed** (28 с) | Эскизы, сетка, дистанции, модули, приключения, ходы мастера, сцены |
| Полный прогон `pytest` | **1309 passed, 4 skipped** (234 с) | 3 пропуска требуют PostgreSQL, 1 — pdftotext |
| Frontend `npm test` & `npm run build` | **142 passed**, сборка успешна | Тесты клиента, валидация карт и типов без ошибок |
| Живой замер `tools/pilot_location_layout.py` | **100% работоспособность** | Проверены обе ветки: успешный ответ модели и fallback при невалидных предложениях |
