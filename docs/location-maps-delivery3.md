# Генеративные карты локаций, поставка 3: каркас, модель структуры, первая сцена и учёт расходов

Спецификация: `docs/superpowers/specs/2026-10-12-generative-location-maps-design.md` (§9, поставка 3; §3.1–3.2, §8, §10).
План: `docs/superpowers/plans/2026-10-12-location-maps-delivery3.md`.

## Что есть

- **Пространственный замысел в каркасе** (`app/core/layout/spatial.py`, `app/core/plot.py`): схема `SpatialPlan`
  (окружение `environment`, масштаб `scale`, обязательные части `parts` с `outdoor/below/secret/required/purpose`,
  подходы `approaches` с `kind/side`). Архитектор (`app/agents/architect.py`) генерирует `spatial` для каждого места
  каркаса: простое место (поляна, комната) — `small` и 1–2 части, место для исследования по частям — до 6 частей
  (лимиты: 1–6 частей, 1–3 подхода, стороны `w/s/e`). Если `spatial` в наброске нет (модель пропустила, старый
  каркас), `plan.with_spatial` строит простой замысел `spatial.default_spatial`: одна часть с именем места,
  окружение и подход по тегам шаблона (`wild`/`rural` — открытая местность и тропа, `underground` — расщелина,
  иначе — помещение и дверь). Карту за столом рисуют и для поляны, поэтому комплексом становится каждое место.
- **Мандат и обязательства** (`app/core/layout/spatial.py`): `Mandate` связывает пространственный план места с
  носителями сюжетных зацепок (`Holder(key, name)`) и NPC-жителями (`npc:<id>`). Функция `obligations` строго
  проверяет выполнение мандата любым замыслом: сохранение обязательных частей, тайности, уровней, привязок носителей,
  входного участка и подходов без внешних ссылок.
- **Лестница детерминированных замыслов** (`app/core/layout/spatial.py::intent_candidates`): детерминированный
  запасной вариант из 3 ступеней: (1) с полосой дороги у западного подхода → (2) без полос → (3) только первый подход.
  В сочетании с обычной раскладкой и `fallback=True` провайдера поставки 1 проверена на
  1890 комбинациях параметров: 0 блокировок. Это результат проверенного набора, а не гарантия для любых входов.
- **Техническая модель структуры** (`app/agents/layout_model.py`): отдельный легковесный агент предлагает
  замысел комплекса (`LayoutIntent`) в рамках единого вызова инструмента `submit_layout`. Модель не касается
  геометрии и координат клеток: их рассчитывает `DeterministicLayoutProvider`. Ошибки мандата или валидации
  возвращаются модели текстом для ровно одной корректирующей попытки. В запросе модели нет секретов сюжета.
- **Подключение модели к фазе генерации** (`app/core/layout/executor.py`): фаза `location_layout` запрашивает
  структуру у технической модели при включённом флаге `location_layouts_llm`. Реализованы строгие защитные лимиты:
  бюджет контекста (оценка до 6000 входных / ограничение 3000 выходных токенов), лимит бюджета кампании (`spend_limit_usd`), лимит
  попыток (`llm_attempt_count <= 2`). При любом исчерпании лимитов, синтаксической или семантической ошибке
  фаза автоматически переключается на детерминированную лестницу (`quality="fallback"` с диагностической заметкой).
  Оценка охватывает всю историю и схему инструмента перед каждой попыткой. Переполнение коррекции даёт
  `fallback:context_budget` до резервирования второго вызова; лишняя запись `LlmCall` не создаётся.
  Входные токены оцениваются по длине сериализованного запроса, а не подсчитываются токенизатором провайдера.
- **Флаги кампании и разворот ключевых мест** (`app/core/layout/plan.py`, `app/config.py`): флаги `location_layouts`
  и `location_layouts_llm` управляют генерацией комплексов. Функция `develop_location_complex` разворачивает место
  каркаса в комплекс участков: бронирует фазу `location_layout` с мандатом в `WorldGenerationState.reservation`, откладывая наполнение
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
  `generation_id` (идентификатор строки фазы, индексированный без ограничения внешнего ключа) и `tokens_reasoning` (токены рассуждений
  моделей reasoning).

## Решения поставки

1. **Модель предлагает замысел, а не blueprint.** Модель формирует семантическую структуру (части, связи, проходы,
   детали, полосы рельефа), а координаты, края, стыки и геометрию считает детерминированный алгоритм поставки 1.
2. **Мандат фиксируется один раз при развороте.** Резерв фазы `location_layout` сохраняет неизменяемый `mandate`
   на момент разворота. Повторный вход или рестарт не пересчитывают мандат и не расходуют новые вызовы модели.
3. **Лестница детерминированных замыслов.** 3 ступени кандидатов в сочетании с алгоритмическим fallback
   обеспечивают запасной путь при отказе внешней модели; проверенные 1890 комбинаций мандата не блокируются.
4. **Изоляция сюжета от модели структуры.** В технический запрос к LLM передаются только публичное имя, атмосфера
   и топологические требования. Секреты локации, зацепок и NPC полностью скрыты.
5. **Вход до вступления первой сцены.** Фиксация героев на входном участке выполняется до вызова агента прелюдии,
   гарантируя синхронность нарратива и карты.
6. **Безопасная упреждающая подготовка.** Подготовка вперёд ограничена только геометрией соседних участков
   и не оставляет следов в личной памяти игроков (`MapMemory`).
7. **Обратная совместимость.** Книги приключений и кампании с выключенными флагами сохраняют прежнее поведение
   без создания комплексов и без изменения формата данных. В кампаниях с включённым `location_layouts` места
   каркаса без `spatial` при развороте получают простой замысел; уже развёрнутые места не перестраиваются.
8. **Обязательный вызов инструмента.** Общий клиент сохраняет `tool_choice="required"` для всех провайдеров.
   Установленный адаптер LiteLLM преобразует его в Gemini `functionCallingConfig.mode="ANY"`;
   замена на `auto`, разрешающая ответ обычным текстом, удалена. Проверка адаптера не делает сетевого запроса.

## Вне поставки

- **Дальние ориентиры и межкомплексные проходы** (спецификация §5): вынесены за рамки поставки 3, так как требуют
  глобальной топологии всего мира и сквозной навигации между удалёнными комплексами. Механика автономного
  комплекса, его геометрия, переходы и память карты полностью самодостаточны без глобальных ориентиров.

## Review Focus: подтверждение тестами

1. **Секреты каркаса в техническом запросе отсутствуют:**
   - `tests/test_layout_model.py::test_brief_carries_no_plot_secrets`
   - `tests/test_location_maps_delivery3.py::test_pilot_brief_has_no_plot_secrets`
2. **Повтор не тратит новые вызовы модели (0 новых вызовов структуры):**
   - `tests/test_layout_model_phase.py::test_limit_survives_restart_retry_and_reentry`
   - `tests/test_opening_complex.py::test_second_opening_does_not_enter_again`
   - `tests/test_location_maps_delivery3.py::test_pilot_round_trip_keeps_structure_and_costs_nothing_new`
3. **Порядок фаз (обстановка корня и носители не обгоняют структуру):**
   - `tests/test_layout_develop.py::test_root_preparation_waits_for_structure`
   - `tests/test_layout_residents.py::test_resident_developed_before_structure_moves_in_on_publish`
   - `tests/test_layout_residents.py::test_carrier_appears_in_its_area_not_at_root`
4. **Первая сцена (вход фиксируется до нарратива, сбой оставляет у корня):**
   - `tests/test_opening_complex.py::test_intro_text_is_written_after_entry`
   - `tests/test_opening_complex.py::test_blocked_structure_keeps_heroes_outside`
5. **Подготовка без раскрытия (lookahead и prepare_location не светят неисследованное):**
   - `tests/test_layout_ahead.py::test_prepared_neighbour_stays_unknown_to_players`
   - `tests/test_prepare_location.py::test_two_calls_prepare_structure_then_all_geometry`
   - `tests/test_location_maps_delivery3.py::test_pilot_secret_vault_is_not_disclosed_by_preparation`
6. **Старые кампании и готовые модули не затрагиваются:**
   - `tests/test_layout_develop.py::test_no_layout_without_flag_or_for_modules`
   - `tests/test_layout_develop.py::test_place_without_spatial_gets_single_part_plan`
   - `tests/test_prepare_location.py::test_refuses_visited_and_prepares_places_without_space`
7. **Лимит коррекции и контракт Gemini:**
   - `tests/test_layout_model_phase.py::test_correction_over_budget_uses_fallback_without_spending_second_call`
   - `tests/test_llm_tool_choice.py::test_required_tool_choice_is_not_downgraded`

## Команды воспроизведения тестов и живого замера

```bash
# Приёмочные тесты поставки 3
uv run pytest tests/test_location_maps_delivery3.py -q

# Все специализированные тесты поставки 3
uv run pytest tests/test_layout_mandate.py tests/test_layout_plan_phase.py tests/test_layout_model.py tests/test_layout_model_phase.py tests/test_layout_develop.py tests/test_layout_residents.py tests/test_opening_complex.py tests/test_layout_ahead.py tests/test_prepare_location.py tests/test_location_cost.py tests/test_llm_accounting.py tests/test_llm_tool_choice.py -q

# Регрессионный срез смежных подсистем
uv run pytest tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_adventure.py tests/test_modules.py tests/test_layout_pilot.py tests/test_layout_turn.py tests/test_opening_scene.py tests/test_scene_model.py -q

# Полный прогон тестового набора backend
uv run pytest -q -n auto -rs

# Живой замер технической модели (требует ключи провайдера LLM)
TALEFORGE_LIVE_PILOT=1 uv run python tools/pilot_location_layout.py
```

## Таблица результатов прогонов

Проверка исправлений ревью от 2026-10-13. Результаты полного backend-прогона ниже относятся
к рабочему дереву перед фиксацией исправлений ревью.

| Набор тестов / Замер | Результат | Примечания |
| --- | --- | --- |
| `tests/test_location_maps_delivery3.py` | **5 passed** | Приёмочный сценарий храма и луга, обход проходов, изоляция тайн, учёт |
| Модульные тесты поставки 3 (12 файлов, включая адаптер Gemini) | **64 passed** | Вместе с 5 приёмочными тестами: 69 passed за 47.32 с; мандат, модель, CAS, жители, первая сцена, lookahead, расходы, бюджет коррекции, режим ANY |
| Регрессионный срез (9 файлов) | **66 passed, 1 skipped** (предыдущая независимая проверка) | Повторная проверка — в составе полного backend-прогона |
| Полный прогон `pytest` | **1319 passed, 4 skipped** (570.19 с, 4 воркера) | 3 пропуска требуют PostgreSQL, 1 — pdftotext; 31 предупреждение зависимостей |
| Frontend `npm test` & `npm run build` | **217 passed** (46 файлов), сборка успешна | Повторная проверка 2026-10-13 |
| Линтер, форматирование, контракт | **PASS** | Проверены все 46 Python-файлов поставки; `app.contract --check` и `git diff --check` проходят |
| Живой замер `tools/pilot_location_layout.py` | В текущей проверке не запускался | Предыдущий исполнитель сообщил о запуске, но замер с датой, моделью и расходами в отчёте отсутствует; успешный путь и fallback проверены сценарными тестами |

Полный прогон выполнен командой:

```powershell
$env:LITELLM_LOCAL_MODEL_COST_MAP='True'
.venv\Scripts\python.exe -m pytest -o addopts='' -n 4 -p no:cacheprovider --basetemp .tmp-delivery3-fixes-full -q -rs
```

Каталог `--basetemp` должен быть отдельным временным каталогом: pytest очищает его перед запуском.
Параллельные изменения озвучки входили в рабочее дерево полного прогона и не относятся к исправлениям карт.

## Проверка слияния в main (2026-10-13)

Поставка вместе с исправлениями ревью (`feat/location-maps-delivery3@6572d24`) объединена с
`main@7e07ca7`. Конфликт в `app/core/plot.py` разрешён с сохранением проверок и инструкций
для обоих полей каркаса: `opening` и `spatial`.

- Полный backend-набор объединённого дерева: **1334 passed, 4 skipped**, 566.57 с, 4 воркера.
  Три пропуска требуют PostgreSQL, один — `pdftotext`.
- Frontend: **217 passed** (46 файлов), production build успешен.
- Линтер и форматирование: все 46 Python-файлов поставки проходят проверки.
- `app.contract --check` и `git diff --cached --check` проходят.

Слияние выполнено локально; публикация в `origin/main` не выполнялась.
