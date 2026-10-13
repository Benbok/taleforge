# Карты локаций TaleForge — поставка 3: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Генерируемая кампания сама превращает ключевые места каркаса в комплексы участков: архитектор задаёт пространственный замысел, техническая модель (или детерминированный fallback) предлагает структуру, первая сцена начинается внутри подготовленного участка, соседи готовятся вперёд без раскрытия, а расходы каждой локации видны по фазам.

**Architecture:** Архитектор пишет в набросок места `spatial` (части, подходы, тайные/нижние/обязательные части). При развороте места `develop` резервирует фазу `location_layout` с неизменным **мандатом** — замысел плюс сюжетные привязки (носители зацепок, жители-NPC). Исполнитель фазы получает от модели `LayoutIntent` (не blueprint!) и прогоняет его через детерминированный provider и `validate` поставки 1; ошибки возвращаются модели одной корректирующей попыткой, дальше — лестница детерминированных замыслов из того же мандата. Геометрию по-прежнему строит код. Вызовы модели пишутся в `LlmCall` с `generation_id`, по которому собирается стоимость места.

**Tech Stack:** Python 3.12, SQLAlchemy async, Alembic, Pydantic 2, LiteLLM (через `app/agents/llm.py`); React 19 + TypeScript (только переключатели настроек). Новых зависимостей нет.

**Spec:** `docs/superpowers/specs/2026-10-12-generative-location-maps-design.md` — §9 п. 3 (объём), §3.1–3.2 (каркас и структура), §8 целиком (порядок, лимиты, стоимость, сбои), §10 (приёмка), применимые пункты §4–7.

**Основа:** `main` **после слияния поставки 2** (`main@3080ca4`: поставка 2 влита merge-коммитом, 842 passed / 2 skipped на её финальном дереве). Итоги: `docs/location-maps-delivery1.md`, `docs/location-maps-delivery2.md`. Контракты поставки 2 сверены с финальным кодом ветки на `4d84c43`. Не реализовывать повторно blueprint, геометрию, переходы, память карты и проекцию.

## Global Constraints

- Клетка — 5 футов; сторона участка не больше 30 клеток; в комплексе максимум 12 участков и 8 проходов на участок (`app/core/layout/contracts.py`). Превышение — следующий комплекс, не расширение текущего.
- Структура текстовой моделью: **один основной вызов и одна корректирующая попытка на сохранённый blueprint** (`LLM_LIMIT = 2` в строке фазы, `llm_attempt_count`). Перезагрузка, повторный вход, рестарт и `retry_preparation` новый лимит не открывают.
- Бюджет вызова структуры: до **6000** входных токенов и до **3000** выходных вместе с рассуждениями (`max_tokens=3000`). Не уложились во вход — упрощаем необязательный контекст, затем fallback. Обязательные сюжетные факты не удаляются ради сокращения запроса.
- Модель выдаёт только `LayoutIntent`-подобный JSON. Ни SVG, ни ORM-состояния, ни id сущностей, ни координат, ни механики. Реальные id назначает сервер при публикации.
- Модель проверяется тем же `DeterministicLayoutProvider.propose` + `validate`, что и ручной замысел; обязательства каркаса — отдельной `spatial.obligations`. Несогласованный результат не публикуется.
- Геометрия участка строится кодом без LLM. Подготовка вперёд — только `location_geometry`, не больше **двух** участков после текущего, без LLM-наполнения и без раскрытия игроку.
- Готовность генерации не открывает карту: `MapMemory` пишут только реальные вход/наблюдение (поставка 2). `map.get`, фоновые фазы, подготовка вперёд и явная подготовка мастером ничего не раскрывают.
- Сохранить механизм `WorldGenerationState`: lease, CAS, world revision, `MAX_CONFLICTS`, восстановление через `run_due`, запрет дубликатов (`uq_world_generation_scope`). Сетевые вызовы — вне транзакции БД. Ручной эскиз мастера (`manual_preserved`) не перезаписывается.
- Секрет места, тайны NPC, тексты зацепок и антагонисты в запрос технической модели **не уходят**: тайность задаётся флагами частей.
- Готовые приключения (`adventure.module_place`, `BookMap`) не превращаются в комплексы. Каркас без `spatial`, выключенный флаг кампании и уже посещённые места ведут себя как до поставки.
- Модель структуры — техническая (`parser_model_for()` через существующий `_model_of`), без хардкода; включается флагом кампании `location_layouts_llm`. Лимит расходов кампании (`spend_limit_usd`) соблюдается: превышен — без модели.
- Тесты не делают сетевых вызовов LLM: `ScriptedLLM` или записанные ответы. Живой замер — отдельный скрипт за явным флагом окружения.
- Тексты интерфейса, комментарии, docstring и коммиты — по-русски; Python — ruff, длина строки 120.
- Исполнение — в новом worktree `feat/location-maps-delivery3` от актуального main **после слияния поставки 2**. Не трогать основную рабочую копию (`feat/narrative-adaptation`, там чужие незакоммиченные правки) и worktree поставки 2.

**Вне поставки:**
- **Дальние ориентиры** (§5). Их место — слой обзора местности в SVG поставки 2 и отдельная модель направления/расстояния без клетки. В поставке 3 ни генерации, ни отрисовки нет: существующие `add_landmark` и `reveal_knowledge` остаются единственным путём, точной клетки ориентир не получает. Причина: без слоя обзора данные было бы негде показать, а придуманный формат пришлось бы ломать.
- Проходы **между разными комплексами** из `spatial.links`: `links` — только подсказка модели и мастеру; подходы всех комплексов ведут в их корень (неоднозначность ссылок поставки 1 не трогаем).
- Пересборка уже опубликованного blueprint, ротация участков, бесшовная ходьба, видимость по клеткам/свету/высоте.
- Наполнение (`location_initial`) моделью «вперёд»; новая UI-панель расходов (сводка — инструментом ведущего и в отчёте расходов по назначению).

## Review Focus

1. **Секреты каркаса в техническом запросе.** Секрет места, тайны и страхи NPC, тексты зацепок не попадают ни в system, ни в user, ни в схему вызова структуры; тайные части видны модели только флагом `secret`. Tests: Task 5 (`test_brief_carries_no_plot_secrets`), Task 13.
2. **Повтор не тратит новые вызовы.** Повторный вход в готовое место, перезагрузка, рестарт с исчерпанным `llm_attempt_count`, `retry_preparation` после `blocked` и повторное вступление дают 0 новых запросов структуры. Tests: Task 6, Task 9, Task 13.
3. **Порядок фаз.** Обстановка корня и носители зацепок не обгоняют структуру: `location_initial` корня ждёт `location_layout`; реликвия появляется в своём участке, не у корня; NPC-жители переезжают в участок при публикации. Tests: Task 7, Task 8.
4. **Первая сцена.** Вступление пишется только после фиксации входа; сбой структуры оставляет героев у корня без выдуманной комнаты; двойной вызов вступления не входит второй раз и не плодит подготовок. Tests: Task 9.
5. **Подготовка без раскрытия.** Подготовка вперёд и `prepare_location` не создают `MapMemory`, не добавляют участки в пакет карты игрока, не резервируют `location_initial`, не вызывают модель. Tests: Task 10, Task 11.
6. **Старые кампании и книга.** Каркас без `spatial`, выключенный флаг, готовое приключение, уже посещённое место — ни резерва структуры, ни изменения поведения. Tests: Task 1, Task 7, Task 11.

---

## Решения и совместимость

1. **Модель предлагает замысел, а не blueprint.** Схема ответа — подмножество `LayoutIntent` (части, связи `connects_to/side`, проходы, детали, полосы рельефа, подходы без `outside_id`). Раскладку, endpoints, края и рельеф считает `DeterministicLayoutProvider` поставки 1 с тем же seed. Так модель не может выдать геометрически невозможный план, а её ошибки — это ошибки `validate`/`obligations`, которые возвращаются ей текстом для единственной коррекции.
2. **Мандат фиксируется один раз при развороте.** Резерв `location_layout` с `source: "plan"` хранит `mandate` (замысел + привязки на момент разворота). Повтор/рестарт не пересчитывает его. Зацепки, привязанные позже, обрабатывает существующий `_with_anchors` (до публикации — во входной участок) и `materialize_late` (после).
3. **Лестница детерминированных замыслов** (`spatial.intent_candidates`): (а) с полосой дороги у западного подхода → (б) без полос → (в) только первый подход; каждый — обычной раскладкой, затем `fallback=True`. Прототип на настоящем provider: 1188 + 702 комбинаций `spatial` (все окружения, масштабы, 1–6 частей, 1–3 подхода, тайные/нижние/обязательные части, двор за помещением) — **0 блокировок**, 18 случаев уходят на ступень (б)/(в). Этот перебор становится тестом Task 2.
4. **Вход в комплекс.** В игре развёрнутое место — корень, «снаружи»: герои стоят у корня и выбирают подход (`traverse_passage`/`map.traverse`) — так работает альтернативный подход пилота. Первая сцена — исключение: после готовности структуры отряд проходит первым открытым подходом во входной участок (`layout.entry.enter_complex`) **до** вступления.
5. **Флаги кампании:** `location_layouts` — структура из каркаса при развороте места; `location_layouts_llm` — структуру предлагает модель. По умолчанию выключены, включаются в настройках или `NEW_CAMPAIGN_FLAGS`. Включение посреди кампании ничего не пересобирает: резерв создаётся только при развороте нового места (`develop`) или явной командой ведущего, которая отказывает посещённому месту.
6. **Учёт:** `llm_calls.generation_id` (id строки фазы) и `llm_calls.tokens_reasoning` (из `usage.completion_tokens_details.reasoning_tokens`; у большинства провайдеров уже внутри `tokens_out`, хранится для прозрачности). Цена — `litellm.completion_cost`, как сейчас. Длительность фазы — `completed_at − requested_at`. Сводка — `preparation.location_cost` и инструмент ведущего `preparation_cost`.
7. **Секрет места не уходит в модель.** Brief строится только из публичного имени, настроения (необязательный контекст) и `spatial`; тайность — флаг части. Публичные имена частей задаёт архитектор (`name` — «для героев, без тайн»).
8. **Лимит расходов:** если `spend_limit_usd` достигнут, модель не вызывается, заметка `fallback:spend_limit`.
9. **Качество фазы:** `normal` — принят замысел модели либо (модель выключена) первый детерминированный кандидат без `fallback=True`; иначе `fallback` и заметки `fallback:<причина>` (`llm_limit`, `invalid_proposal`, `llm_failed`, `context_budget`, `spend_limit`, `layout`).
10. **Жители-NPC** хранятся в существующем `Blueprint.anchors` ключом `npc:<plot_id>` (схема blueprint не меняется; `plot_anchors.reserved_for` такие ключи не совпадут ни с одним `anchor_id`).

## Контракты, которые связывают задачи

**Каркас и мандат (Tasks 1–2), `app/core/layout/spatial.py`:**

- `SpatialPart(ref, name, purpose="", outdoor=False, below=False, secret=False, required=False)`; `SpatialApproach(name, kind: Literal["road","path","door","gate","gap"]="path")`; `SpatialPlan(schema_version=1, environment: Literal["indoor","outdoor","mixed"], scale: Literal["small","medium","large"]="medium", parts: 1..6, approaches: 1..3, links: ≤4)`. Первая часть — вход.
- `Holder(key: str, name: str)`; `key` — `anchor_id` носителя зацепки или `npc:<plot_id>` жителя.
- `Mandate(schema_version=1, place: str, mood: str = "", spatial: SpatialPlan, anchors: list[Holder] = [], residents: list[Holder] = [])`; вместе не больше 8 привязок.
- `intent_candidates(m: Mandate) -> list[LayoutIntent]` — лестница из Решения 3, первый — основной.
- `obligations(intent: LayoutIntent, m: Mandate) -> list[str]` — пустой список: каркас соблюдён.

**Резерв и исполнитель (Tasks 3, 6, 7):**

- `store.reserve_plan_layout(session, campaign, root: Entity, mandate: Mandate) -> WorldGenerationState` — резерв `{"phase","seed","root_id","plot_id","source":"plan","mandate"}`; повтор возвращает ту же строку.
- `store.home_of(entities: dict[str, Entity], place_id: str | None, key: str) -> str | None` — участок жителя/носителя или сам `place_id`, если blueprint нет.
- `executor.run(maker, dice_factory, claim, phase, provider, llm=None)`; `_draft(...) -> tuple[Blueprint, str, list[str], storage.Claim]` (claim обновлён после `reserve_llm_call`).
- `layout_plan.reserve_from_plan(ctx, root: Entity, sketch: dict, inverse: list) -> WorldGenerationState | None` (`app/core/layout/plan.py`), `layout_plan.mandate_for(session, campaign_id, plan: dict, sketch: dict, root: Entity) -> Mandate`, `layout_plan.eligible(world, root) -> bool`.

**Модель структуры (Task 5), `app/agents/layout_model.py`:**

- `PURPOSE = "location_layout"`, `TOOL = "submit_layout"`, `MAX_IN = 6000`, `MAX_OUT = 3000`, `TIMEOUT = 60.0`.
- `spec(m: Mandate) -> dict`; `brief(m: Mandate) -> str | None` (None — обязательное не помещается в бюджет); `to_intent(m: Mandate, args: Any) -> LayoutIntent` (бросает `Blocked("invalid_proposal", ...)`);
- `async ask(llm, m, *, model, api_base, msgs: list, check: Callable[[LayoutIntent], None]) -> tuple[LayoutIntent | None, Attempt, str | None]`; `check` бросает `LayoutError`.
- `world_generator.Attempt` получает `tokens_reasoning: int = 0` и переиспользуется.

**Учёт (Tasks 4, 12):**

- `LLMReply.reasoning_tokens: int = 0`; `LlmCall.generation_id: str | None`, `LlmCall.tokens_reasoning: int = 0`; миграция `0023_llm_call_generation`.
- `preparation.location_cost(session, campaign_id: str, root_id: str) -> dict` — `{"root_id", "phases": {phase: Bucket}, "total": Bucket}`, `Bucket = {rows, ready, pending, blocked, calls, errors, tokens_in, tokens_out, tokens_reasoning, cost, duration_ms}`.

**Первая сцена и вперёд (Tasks 9–10):**

- `entry.entry_approach(root: Entity, bp: Blueprint) -> str | None`; `async entry.enter_complex(maker, preparer, dice_factory, campaign_id: str, root_id: str, bus=None) -> dict` — `{"moved": bool, "reason"?: str, "area_id"?: str}`.
- `async ahead.request_ahead(ctx, area: Entity) -> list[str]` — id активированных строк геометрии (≤ `AHEAD = 2`).

**Инструменты ведущего (Tasks 11–12), `app/tools/master/generation.py`, оба в `HOST_TOOLS`:** `prepare_location(location_id, furnish=False)`, `preparation_cost(location_id)` (`mutating=False`).

## Зависимости от поставки 2

| Контракт поставки 2 (её план) | Где в коде (ветка `4d84c43`) | Кто в поставке 3 зависит |
| --- | --- | --- |
| Миграция `0022_map_memories` (Task 2) | `alembic/versions/0022_map_memories.py`, `revision="0022"` | Task 4: `down_revision = "0022"` |
| `relocate_scene` стала `async` (Task 3) | `app/tools/master/places.py` | Task 7 (`develop` вызывает `await relocate_scene`), Task 9 |
| `observe_area(ctx, place_id, hero_ids, inverse, *, explicit=False)` в `move_heroes`/`relocate_scene` (Tasks 2–3) | `app/core/map_memory.py` | Task 9: вход первой сцены пишет память только вошедшим |
| `MapMemory(character_id, entity_id)`, `snapshot` (Task 2) | `app/db/models.py` | Tasks 9, 10, 11, 13 — проверки «не раскрыто» |
| `find_passage/check(..., known_passages=None)` (Task 4) | `app/core/layout/transit.py` | Task 9: `enter_complex` идёт путём мастера (`known_passages=None`) |
| `map_projection.location_plan` и `location_map` в `map.state` (Task 5) | `app/core/map_projection.py` | Tasks 10, 13: подготовленный сосед не в пакете игрока |
| Тесты памяти и проекции (общих хелперов `memory_party`/`read_memory` поставка 2 не завела) | `tests/test_map_memory.py`, `tests/test_location_map_privacy.py`, `tests/test_location_map_contract.py`; память читать `rows(settings, MapMemory, ...)` | Tasks 9, 10, 13 |
| `transit.traverse(..., expected_source_id=...)`, `map.traverse` с `source_id` | `app/core/layout/transit.py`, `app/gateway/ws.py::_traverse` | Task 10: правка только в `finally` `_traverse`; сигнатуру `traverse` не менять |

**Можно исполнять до слияния поставки 2** (чистые модули без её точек касания): **Tasks 1, 2, 3, 5**. Остальные — после слияния. Если исполнение начинается раньше, эти четыре задачи делаются в worktree от main и затем ребейзятся; их файлы с поставкой 2 не пересекаются (`app/core/plot.py`, `app/agents/architect.py`, `app/core/layout/{spatial,store,executor}.py`, `app/agents/layout_model.py`).

## Карта файлов

| Файл | Ответственность |
| --- | --- |
| `app/core/layout/spatial.py` (новый) | `SpatialPlan`, `Mandate`, лестница замыслов, обязательства каркаса |
| `app/core/plot.py`, `app/agents/architect.py` | Схема `spatial` в каркасе, проверка, подсказка архитектору, оценка выхода |
| `app/core/layout/store.py` | Резерв структуры из мандата, участок жителя |
| `app/core/layout/executor.py` | Мандат → замысел (модель/лестница) → blueprint; жители при публикации |
| `app/agents/layout_model.py` (новый) | Техническая модель структуры: схема, brief с бюджетом, разбор, коррекция |
| `app/agents/llm.py`, `app/agents/world_generator.py`, `app/core/world_generation/service.py` | Токены рассуждений, `generation_id`, `llm` в исполнитель, зависимости фаз |
| `app/db/models.py`, `alembic/versions/0023_llm_call_generation.py` (новый), `app/core/spend.py` | Колонки учёта и отчёт |
| `app/core/layout/plan.py` (новый), `app/tools/plot.py` | Разворот места каркаса в комплекс, дом NPC |
| `app/config.py`, `app/api/schemas.py`, `app/api/campaigns.py`, `web/src/lib/campaign.ts`, `web/src/cabinet/SettingsTab.tsx`, `web/openapi.json`, `web/src/lib/api.gen.ts` | Флаги `location_layouts`, `location_layouts_llm` |
| `app/core/layout/entry.py` (новый), `app/agents/prelude.py` | Первая сцена внутри комплекса |
| `app/core/layout/ahead.py` (новый), `app/core/layout/transit.py`, `app/gateway/ws.py` | Подготовка вперёд |
| `app/tools/master/generation.py`, `app/core/preparation.py` | `prepare_location`, `preparation_cost`, `location_cost` |
| `tests/layout_plan_pilot.py` (новый) | Каркас храма, мандат, ответ модели для тестов |
| `tests/test_layout_spatial.py`, `test_layout_plan_phase.py`, `test_layout_model.py`, `test_llm_accounting.py`, `test_layout_model_phase.py`, `test_layout_develop.py`, `test_layout_residents.py`, `test_opening_complex.py`, `test_layout_ahead.py`, `test_prepare_location.py`, `test_location_cost.py`, `test_location_maps_delivery3.py` (новые) | Тесты задач |
| `tools/pilot_location_layout.py` (новый), `docs/location-maps-delivery3.md` (новый), `docs/README.md` | Живой замер и итог поставки |

## Перед исполнением

1. Прочитать спеку, этот план, итоги поставок 1 и 2. Проверить, что поставка 2 влита в main: `git log --oneline main | head`, наличие `docs/location-maps-delivery2.md`.
2. **Сверка с поставкой 2 (обязательно):** сравнить таблицу «Зависимости от поставки 2» с фактическим кодом main: сигнатуры `observe_area`, `relocate_scene`, `find_passage/check`, `_traverse`, имя и ревизию последней миграции (`uv run alembic heads`). Если head не `0022`, взять следующий номер и `down_revision` по факту. Расхождения записать в журнал решений исполнения и поправить затронутые задачи **до** их исполнения.
3. Worktree: `git worktree add ../taleforge-worktrees/location-maps-delivery3 -b feat/location-maps-delivery3 main`; в нём `uv sync --extra dev`; в `web/` — `npm install`, если зависимостей нет.
4. Baseline: `uv run pytest -q -n auto -rs`, в `web/` `npm test` и `npm run build`. Записать число passed/skipped и причины skips (известные: нет `pdftotext`, два — PostgreSQL). Это baseline, а не потолок. Старые ошибки ruff в `test_tts`, `test_voicing`, `test_crits_advantage`, `test_game_screen`, `app/core/chat.py`, `app/core/linker.py` не исправлять.
5. Общие тестовые заготовки: `tests.game` (`import_base`, `party`, `quiet`, `run`), `tests.test_map` (`_ok`, `_play`, `_map`), `tests.test_world_generation` (`_prepare`, `_row`, `_with_maker`, `_fast_retry`), `tests.test_master` (`rows`, `game_client`, `admin_g`, `llm`), `tests.test_lead` (`set_plan`), `tests.test_plan` (`good_plan`, `FakeCatalog`), `tests.test_layout_passages._built`, `tests.test_layout_transit._go`.

---

### Task 1: Пространственный замысел в каркасе

**Files:**
- Create: `app/core/layout/spatial.py` (модели замысла), `tests/test_layout_spatial.py`
- Modify: `app/core/plot.py` (`tool_spec`, `check`, `SYSTEM`), `app/agents/architect.py` (`estimate_cost`), `app/core/layout/__init__.py` (строка в docstring)

**Interfaces:**
- Consumes: `app.core.layout.intent.REF`.
- Produces: `SpatialPart`, `SpatialApproach`, `SpatialPlan` (см. «Контракты»); `plot.check` нормализует `loc["spatial"]` в `SpatialPlan.model_dump(mode="json")`; `plot.spatial_schema() -> dict`.

- [ ] **Step 1: Написать failing tests** в `tests/test_layout_spatial.py`:

```python
"""Пространственный замысел места в каркасе (спецификация 2026-10-12, §3.1)."""

import copy

import pytest

from app.core import plot
from tests.test_plan import FakeCatalog, good_plan

TEMPLE = {
    "environment": "mixed",
    "scale": "medium",
    "parts": [
        {"ref": "road", "name": "Дорога у храма", "purpose": "дорога, ручей и мост", "outdoor": True},
        {"ref": "narthex", "name": "Притвор"},
        {"ref": "nave", "name": "Главный зал", "purpose": "колонны и алтарь"},
        {"ref": "chapel", "name": "Часовня", "required": True},
        {"ref": "crypt", "name": "Крипта", "below": True},
        {"ref": "vault", "name": "Тайник", "secret": True},
    ],
    "approaches": [{"name": "Дорога в деревню", "kind": "road"}],
    "links": ["loc_tavern"],
}


def _check(p):
    return plot.check(p, length="short", catalog=FakeCatalog(), excluded=[])


def test_plan_without_spatial_still_checks():
    p, errors = _check(good_plan())
    assert errors == [] and all("spatial" not in x for x in p["locations"])


def test_spatial_is_normalized():
    raw = good_plan()
    raw["locations"][2]["spatial"] = copy.deepcopy(TEMPLE)
    p, errors = _check(raw)
    assert errors == []
    sp = p["locations"][2]["spatial"]
    assert sp["schema_version"] == 1 and sp["parts"][1]["outdoor"] is False and sp["approaches"][0]["kind"] == "road"


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda s: s["parts"][0].update(secret=True), "вход"),
        (lambda s: s.update(environment="indoor"), "indoor"),
        (lambda s: s["parts"].append(dict(s["parts"][1])), "повторяется"),
        (lambda s: s["parts"].extend([{"ref": f"x{i}", "name": "X"} for i in range(3)]), "parts"),
        (lambda s: s["parts"][3].update(secret=True), "тайная часть"),
        (lambda s: s["parts"][4].update(outdoor=True), "уровнем ниже"),
        (lambda s: s.update(links=["loc_nowhere"]), "нет места loc_nowhere"),
    ],
)
def test_spatial_errors_return_to_architect(mutate, text):
    raw = good_plan()
    sp = copy.deepcopy(TEMPLE)
    mutate(sp)
    raw["locations"][2]["spatial"] = sp
    _p, errors = _check(raw)
    assert any(e.startswith("локация loc_light: пространство") and text in e for e in errors), errors


def test_tool_spec_spatial_is_optional_and_revision_keeps_it():
    loc = plot.tool_spec()["function"]["parameters"]["properties"]["locations"]["items"]
    assert "spatial" in loc["properties"] and "spatial" not in loc["required"]
    rev_loc = plot.revision_spec()["function"]["parameters"]["properties"]["locations"]["items"]
    assert "spatial" in rev_loc["properties"]
    p, _ = _check(good_plan())
    new = {"id": "loc_temple", "name": "Храм", "template_id": "location.ruins", "role": "-", "mood": "-",
           "secret": "-", "spatial": copy.deepcopy(TEMPLE) | {"links": []}}  # fmt: skip
    merged, errors = plot.merge_revision(p, {"summary": "храм", "acts": copy.deepcopy(p["acts"]), "locations": [new]})
    merged, errors = plot.check(merged, length="short", catalog=FakeCatalog(), excluded=[], keep_state=True)
    assert errors == [] and merged["locations"][-1]["spatial"]["parts"][0]["ref"] == "road"


def test_architect_is_told_about_spatial():
    assert "spatial" in plot.SYSTEM
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_spatial.py -q` — FAIL: нет `spatial` в схеме, `check` не проверяет поле.

- [ ] **Step 3: Реализовать модели замысла.** Создать `app/core/layout/spatial.py` (во Task 2 сюда же добавятся мандат и лестница):

```python
"""Пространственный замысел места из каркаса (спецификация 2026-10-12, §3.1) и мандат структуры (§3.2, §8).

``SpatialPlan`` пишет архитектор: окружение, масштаб, обязательные части и подходы — без клеток и предметов.
Первая часть — вход. ``Mandate`` — неизменная часть резерва ``location_layout``: замысел и сюжетные привязки места.
Из мандата структуру предлагает модель (app/agents/layout_model.py) или лестница детерминированных замыслов;
``obligations`` проверяет, что предложенный замысел каркас не нарушил.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.core.layout.intent import REF


class SpatialPart(BaseModel):
    ref: str = Field(pattern=REF, description="id части внутри места: nave, crypt")
    name: str = Field(min_length=1, max_length=80, description="название для героев, без тайн")
    purpose: str = Field("", max_length=300, description="что здесь, одной фразой")
    outdoor: bool = Field(False, description="открытая местность: поле, двор, берег")
    below: bool = Field(False, description="уровнем ниже входа: подвал, крипта")
    secret: bool = Field(False, description="за тайным проходом")
    required: bool = Field(False, description="сюжетная цель: к ней обязан вести открытый путь")

    @model_validator(mode="after")
    def _shape(self) -> SpatialPart:
        if self.secret and self.required:
            raise ValueError(f"{self.ref}: тайная часть не может быть обязательной целью")
        if self.below and self.outdoor:
            raise ValueError(f"{self.ref}: часть уровнем ниже — помещение, а не открытая местность")
        return self


class SpatialApproach(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="как герои подходят: «Дорога из деревни»")
    kind: Literal["road", "path", "door", "gate", "gap"] = "path"


class SpatialPlan(BaseModel):
    schema_version: Literal[1] = 1
    environment: Literal["indoor", "outdoor", "mixed"]
    scale: Literal["small", "medium", "large"] = "medium"
    parts: list[SpatialPart] = Field(min_length=1, max_length=6)
    approaches: list[SpatialApproach] = Field(min_length=1, max_length=3)
    links: list[str] = Field(default_factory=list, max_length=4, description="id других мест каркаса рядом")

    @model_validator(mode="after")
    def _parts(self) -> SpatialPlan:
        refs = [p.ref for p in self.parts]
        if len(set(refs)) != len(refs):
            raise ValueError("ref части повторяется")
        entry = self.parts[0]
        if entry.secret or entry.below:
            raise ValueError("первая часть — вход: не тайная и не уровнем ниже")
        outdoor = {p.outdoor for p in self.parts}
        if self.environment == "indoor" and True in outdoor:
            raise ValueError("indoor: открытых частей нет")
        if self.environment == "outdoor" and not entry.outdoor:
            raise ValueError("outdoor: вход — открытая местность")
        if self.environment == "mixed" and outdoor != {True, False}:
            raise ValueError("mixed: нужны и открытые части, и помещения")
        return self
```

- [ ] **Step 4: Подключить к каркасу.** В `app/core/plot.py`:
  - рядом с `_str/_id` добавить `spatial_schema()`; в `tool_spec()` добавить в `locations.items.properties` ключ `"spatial": spatial_schema()` (не в `required`). `revision_spec` берёт `props["locations"]`, поэтому получит поле сам.

```python
def spatial_schema() -> dict:
    """Пространство места (спецификация 2026-10-12, §3.1): только для мест, которые исследуют по частям."""
    part = {
        "type": "object",
        "properties": {
            "ref": _id("id части."),
            "name": _str("Название для героев, без тайн.", 80),
            "purpose": _str("Что здесь, одной фразой.", 300),
            "outdoor": {"type": "boolean", "description": "открытая местность"},
            "below": {"type": "boolean", "description": "уровнем ниже входа: подвал, крипта"},
            "secret": {"type": "boolean", "description": "за тайным проходом"},
            "required": {"type": "boolean", "description": "сюжетная цель: к ней ведёт открытый путь"},
        },
        "required": ["ref", "name"],
    }
    approach = {
        "type": "object",
        "properties": {
            "name": _str("Как герои подходят.", 60),
            "kind": {"type": "string", "enum": ["road", "path", "door", "gate", "gap"]},
        },
        "required": ["name"],
    }
    return {
        "type": "object",
        "description": "Только для места, которое отряд будет исследовать по частям (храм, руины, усадьба, поле у "
        "моста): из чего оно состоит. Без клеток и предметов — план построит сервер.",
        "properties": {
            "environment": {"type": "string", "enum": ["indoor", "outdoor", "mixed"]},
            "scale": {"type": "string", "enum": ["small", "medium", "large"]},
            "parts": {"type": "array", "minItems": 1, "maxItems": 6, "description": "Первая — вход.", "items": part},
            "approaches": {"type": "array", "minItems": 1, "maxItems": 3, "items": approach},
            "links": {"type": "array", "maxItems": 4, "items": {"type": "string"}, "description": "id мест рядом"},
        },
        "required": ["environment", "parts", "approaches"],
    }
```

  - в `check()` внутри цикла `for loc in plan["locations"]:` после проверки `lore_ref`:

```python
            if loc.get("spatial") is not None:
                from pydantic import ValidationError

                from app.core.layout.spatial import SpatialPlan

                try:
                    loc["spatial"] = SpatialPlan.model_validate(loc["spatial"]).model_dump(mode="json")
                except ValidationError as e:
                    why = "; ".join(f"{'.'.join(map(str, x['loc'])) or '-'}: {x['msg']}" for x in e.errors()[:3])
                    errors.append(f"локация {oid}: пространство — {why}")
```

  - после вычисления `loc_ids`:

```python
    for loc in plan["locations"]:
        links = ((loc.get("spatial") or {}).get("links") or []) if isinstance(loc, dict) else []
        for link in links:
            if link not in loc_ids:
                errors.append(f"локация {loc.get('id')}: пространство — нет места {link}")
```

  - в `SYSTEM` добавить правило: `"- Для 1–3 мест, которые отряд будет исследовать по частям (храм, руины, усадьба, поле у моста), заполни spatial: первая часть — вход, тайные части — secret, сюжетная цель — required, подвал и крипта — below. Без клеток и предметов; названия частей видны игрокам."`
  - в `app/agents/architect.py`: `SPATIAL_OUT = 600  # пространство 1–3 мест в ответе архитектора` и `tokens_out = OUT_TOKENS.get(length, 6000) + SPATIAL_OUT` в `estimate_cost`.

- [ ] **Step 5: Проверить GREEN.** `uv run pytest tests/test_layout_spatial.py tests/test_plan.py tests/test_lead.py -q` — PASS; старые каркасы без `spatial` проходят без изменений.

- [ ] **Step 6: Commit.**

```bash
git add app/core/layout/spatial.py app/core/layout/__init__.py app/core/plot.py app/agents/architect.py tests/test_layout_spatial.py
git commit -m "Каркас кампании описывает пространство ключевых мест"
```

---

### Task 2: Мандат и лестница детерминированных замыслов

**Files:**
- Modify: `app/core/layout/spatial.py`
- Create: `tests/layout_plan_pilot.py`, `tests/test_layout_mandate.py`

**Interfaces:**
- Consumes: `SpatialPlan` (Task 1); `LayoutIntent`, `DeterministicLayoutProvider` (поставка 1).
- Produces: `Holder`, `Mandate`, `intent_candidates(m) -> list[LayoutIntent]`, `obligations(intent, m) -> list[str]`; тестовые `TEMPLE_SPATIAL`, `temple_mandate()`, `temple_plan()`, `model_layout(keys)`.

- [ ] **Step 1: Создать общие заготовки** `tests/layout_plan_pilot.py`:

```python
"""Пилот поставки 3: каркас храма с пространством, мандат и ответ технической модели для тестов."""

from __future__ import annotations

import copy

from app.core import plot
from app.core.layout.spatial import Holder, Mandate, SpatialPlan
from tests.layout_pilot import pilot_intent
from tests.test_plan import FakeCatalog, good_plan

TEMPLE_SPATIAL = {
    "environment": "mixed",
    "scale": "medium",
    "parts": [
        {"ref": "road", "name": "Дорога у храма", "purpose": "дорога, ручей и мост", "outdoor": True},
        {"ref": "narthex", "name": "Притвор"},
        {"ref": "nave", "name": "Главный зал", "purpose": "колонны и алтарь"},
        {"ref": "chapel", "name": "Часовня", "required": True},
        {"ref": "crypt", "name": "Крипта", "below": True},
        {"ref": "vault", "name": "Тайник", "secret": True},
    ],
    "approaches": [{"name": "Дорога в деревню", "kind": "road"}],
}


def temple_mandate(anchors=(("clue_relic", "Журнал смотрителя"),), residents=(("npc:npc_warden", "Бертольд"),)):
    return Mandate(
        place="Старый храм",
        mood="Ветер в разбитых окнах",
        spatial=SpatialPlan.model_validate(TEMPLE_SPATIAL),
        anchors=[Holder(key=k, name=n) for k, n in anchors],
        residents=[Holder(key=k, name=n) for k, n in residents],
    )


def temple_plan() -> dict:
    """Каркас good_plan: Солёная бухта стала храмом с пространством; смотритель живёт там, журнал — носитель."""
    p = good_plan()
    port = p["locations"][0]
    port.update(name="Старый храм", template_id="location.ruins", mood="Ветер в разбитых окнах",
                spatial=copy.deepcopy(TEMPLE_SPATIAL))  # fmt: skip
    p["reveals"][0]["clues"][1]["carrier"] = {"name": "Журнал смотрителя", "description": "Страницы вырваны."}
    checked, errors = plot.check(p, length="short", catalog=FakeCatalog(), excluded=[])
    assert errors == [], errors
    return checked


def model_layout(keys: list[str]) -> dict:
    """Ответ модели: замысел пилота поставки 1 без outside_id; носители — в часовне, жители — у дороги."""
    raw = pilot_intent().model_dump(mode="json")
    raw.pop("schema_version", None)
    for ap in raw["approaches"]:
        ap.pop("outside_id", None)
    parts = []
    for part in raw["parts"]:
        part = {k: v for k, v in part.items() if v is not None}
        part["anchors"] = []
        if part["part_ref"] == "chapel":
            part["anchors"] = [k for k in keys if not k.startswith("npc:")]
            part["required"] = True
        if part["part_ref"] == "road":
            part["anchors"] = [k for k in keys if k.startswith("npc:")]
        parts.append(part)
    raw["parts"] = parts
    raw["bands"] = [{k: v for k, v in b.items() if v is not None} for b in raw["bands"]]
    raw["approaches"] = [{k: v for k, v in a.items() if v is not None} for a in raw["approaches"]]
    return raw
```

- [ ] **Step 2: Написать failing tests** `tests/test_layout_mandate.py` (перебор — из прототипа планирования; ~2 с):

```python
"""Мандат и лестница детерминированных замыслов (спецификация 2026-10-12, §3.2, §8)."""

import itertools

import pytest
from pydantic import ValidationError

from app.core.layout.contracts import LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Holder, Mandate, SpatialPlan, intent_candidates, obligations
from tests.layout_plan_pilot import model_layout, temple_mandate

HOLDERS = dict(anchors=[Holder(key="a1", name="Письмо"), Holder(key="a2", name="Перстень")],
               residents=[Holder(key="npc:x", name="Смотритель"), Holder(key="npc:y", name="Сторож")])  # fmt: skip


def _variants(n: int, env: str):
    base = [{"ref": f"p{i}", "name": f"Часть {i}"} for i in range(n)]
    if env == "outdoor":
        base = [p | {"outdoor": True} for p in base]
    if env == "mixed":
        base[0]["outdoor"] = True
    yield base
    if n >= 3:
        yield base[:-1] + [base[-1] | {"secret": True, "outdoor": False}]
        yield base[:-1] + [base[-1] | {"below": True, "outdoor": False}]
        yield base[:-2] + [base[-2] | {"secret": True, "outdoor": False}, base[-1] | {"below": True, "outdoor": False}]
        yield base[:1] + [base[1] | {"required": True}] + base[2:-1] + [base[-1] | {"secret": True, "outdoor": False}]
    if env == "mixed" and n >= 2:  # вход — помещение, двор дальше
        yield [{"ref": f"p{i}", "name": f"Часть {i}", "outdoor": i == n - 1} for i in range(n)]


def _cases():
    for env, scale, n, nap, kind in itertools.product(("indoor", "outdoor", "mixed"), ("small", "medium", "large"),
                                                     range(1, 7), (1, 2, 3), ("road", "door")):  # fmt: skip
        for parts in _variants(n, env):
            if env == "mixed" and {p.get("outdoor", False) for p in parts} != {True, False}:
                continue
            yield {"environment": env, "scale": scale, "parts": parts,
                   "approaches": [{"name": f"Подход {k}", "kind": kind} for k in range(nap)]}  # fmt: skip


def test_every_spatial_plan_lays_out_and_keeps_obligations():
    provider = DeterministicLayoutProvider()
    total = 0
    for raw in _cases():
        m = Mandate(place="Место", spatial=SpatialPlan.model_validate(raw), **HOLDERS)
        built = None
        for intent in intent_candidates(m):
            assert obligations(intent, m) == [], (raw, obligations(intent, m))
            for fallback in (False, True):
                try:
                    built = provider.propose(intent, seed=12345, root_id="root", fallback=fallback)
                    break
                except LayoutError:
                    continue
            if built is not None:
                break
        assert built is not None, raw
        total += 1
    assert total > 1000


def test_candidates_put_holders_where_the_plan_expects():
    m = temple_mandate()
    first = intent_candidates(m)[0]
    by = {p.part_ref: p for p in first.parts}
    assert first.entry == "road" and by["chapel"].anchors == ["clue_relic"] and by["road"].anchors == ["npc:npc_warden"]
    assert by["vault"].secret and by["crypt"].level == -1 and by["chapel"].required
    assert all(a.outside_id is None for a in first.approaches)
    assert [b.kind for b in first.bands] == ["road"] and not intent_candidates(m)[1].bands


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda r: r.update(parts=[p for p in r["parts"] if p["part_ref"] != "crypt"]), "нет обязательной части crypt"),
        (lambda r: next(p for p in r["parts"] if p["part_ref"] == "vault").update(secret=False), "vault: тайность"),
        (lambda r: next(p for p in r["parts"] if p["part_ref"] == "chapel").update(anchors=[]), "clue_relic"),
        (lambda r: r.update(entry="narthex"), "вход — часть road"),
        (lambda r: r["approaches"][0].update(outside_id="en_x"), "подход"),
    ],
)
def test_obligations_name_what_the_model_broke(mutate, text):
    m = temple_mandate()
    raw = model_layout(["clue_relic", "npc:npc_warden"])
    mutate(raw)
    errors = obligations(LayoutIntent.model_validate(raw), m)
    assert any(text in e for e in errors), errors


def test_model_layout_fixture_keeps_obligations():
    m = temple_mandate()
    assert obligations(LayoutIntent.model_validate(model_layout(["clue_relic", "npc:npc_warden"])), m) == []


def test_mandate_limits_holders():
    many = [Holder(key=f"a{i}", name="x") for i in range(9)]
    with pytest.raises(ValidationError):
        Mandate(place="Место", spatial=temple_mandate().spatial, anchors=many)
```

  Код модуля из Step 4 и эти тесты при написании плана прогнаны на снимке `main@8d05a22`: 9 passed, перебор ~2 с.

- [ ] **Step 3: Проверить RED.** `uv run pytest tests/test_layout_mandate.py -q` — FAIL: нет `Mandate`/`intent_candidates`/`obligations`.

- [ ] **Step 4: Реализовать** в `app/core/layout/spatial.py` (импорты дополнить `Counter`, `LayoutIntent`, `MAX_AREAS`):

```python
ROAD_KINDS = ("road", "path")
APPROACH_SIDES = ("w", "s", "e")
OUTDOOR_ROWS = {"small": 8, "medium": 10, "large": 12}  # как app/core/layout/provider.py SIZES["outdoor"]
MAX_HOLDERS = 8  # PartIntent.anchors: не больше восьми привязок на часть


class Holder(BaseModel):
    """То, что каркас обязал держать в одной части места: носитель зацепки или житель-NPC (``npc:<id>``)."""

    key: str = Field(pattern=r"^(npc:)?[a-z][a-z0-9_]{0,63}$")
    name: str = Field(min_length=1, max_length=80)


class Mandate(BaseModel):
    schema_version: Literal[1] = 1
    place: str = Field(min_length=1, max_length=128, description="публичное имя места")
    mood: str = Field("", max_length=300, description="настроение: необязательный контекст модели")
    spatial: SpatialPlan
    anchors: list[Holder] = Field(default_factory=list)
    residents: list[Holder] = Field(default_factory=list)

    @model_validator(mode="after")
    def _holders(self) -> Mandate:
        keys = [h.key for h in [*self.anchors, *self.residents]]
        if len(keys) > MAX_HOLDERS:
            raise ValueError(f"привязок места больше {MAX_HOLDERS}")
        if len(set(keys)) != len(keys):
            raise ValueError("привязка повторяется")
        return self

    def holders(self) -> list[Holder]:
        return [*self.anchors, *self.residents]


def intent_candidates(m: Mandate) -> list[LayoutIntent]:
    """Лестница замыслов: с дорогой у западного подхода → без полос → только первый подход. Первый — основной."""
    return [_intent(m, bands=True, approaches=3), _intent(m, bands=False, approaches=3),
            _intent(m, bands=False, approaches=1)]  # fmt: skip


def _intent(m: Mandate, *, bands: bool, approaches: int) -> LayoutIntent:
    sp = m.spatial
    entry = sp.parts[0].ref
    aps = sp.approaches[:approaches]
    ap_sides = APPROACH_SIDES[: len(aps)]
    free = [s for s in ("n", "e", "s", "w") if s not in ap_sides]  # стороны входа для детей, не занятые подходами
    open_parts = [p for p in sp.parts if not p.secret]
    deep = next((p.ref for p in reversed(open_parts) if p.ref != entry and not p.below), None) or next(
        (p.ref for p in reversed(open_parts) if p.ref != entry), entry
    )
    out: list[dict] = []
    last: dict[int, str | None] = {0: None, -1: None}
    entry_kids = 0
    for i, p in enumerate(sp.parts):
        level = -1 if p.below else 0
        outdoor = p.outdoor and level == 0
        d = {"part_ref": p.ref, "role": "field" if outdoor else "room", "name": p.name, "public_name": p.name,
             "description": p.purpose, "environment": "outdoor" if outdoor else "indoor",
             "shape": "open" if outdoor else "rect", "size": "small" if p.secret else sp.scale, "level": level,
             "secret": p.secret, "required": p.required, "anchors": []}  # fmt: skip
        if i > 0:
            parent = (last[0] if level == 0 else (last[-1] or last[0])) or entry
            same = next(x for x in out if x["part_ref"] == parent)["level"] == level
            if parent == entry and same:
                if entry_kids < len(free):
                    d["side"] = free[entry_kids]
                    entry_kids += 1
                else:  # стороны входа заняты подходами: часть встаёт за предыдущей открытой частью уровня
                    parent = next((x["part_ref"] for x in reversed(out) if x["part_ref"] != entry
                                   and not x["secret"] and x["level"] == level), entry)  # fmt: skip
            d["connects_to"] = parent
            d["passage_name"] = "Тайный ход" if p.secret else ("Лестница" if not same else "Проход")
            if not same:
                d["passage_kind"] = "stairs"
        if p.ref == deep:
            d["anchors"] += [h.key for h in m.anchors]
        if p.ref == entry:
            d["anchors"] += [h.key for h in m.residents]
        out.append(d)
        if not p.secret:
            last[level] = p.ref
    outdoor_entry = out[0]["environment"] == "outdoor"
    approaches_out, bands_out = [], []
    for side, ap in zip(ap_sides, aps, strict=True):
        a = {"part_ref": entry, "side": side, "kind": "edge" if outdoor_entry else "door", "public_name": ap.name}
        if bands and outdoor_entry and side == "w" and ap.kind in ROAD_KINDS:
            rows = OUTDOOR_ROWS[out[0]["size"]]
            bands_out.append({"band_ref": "road", "kind": ap.kind, "axis": "we", "at": rows // 2 - 1, "width": 2})
            a |= {"band": "road", "width": 2}
        approaches_out.append(a)
    return LayoutIntent.model_validate({"entry": entry, "parts": out, "approaches": approaches_out, "bands": bands_out})


def obligations(intent: LayoutIntent, m: Mandate) -> list[str]:
    """Что предложенный замысел нарушил в каркасе. Пусто — можно раскладывать."""
    errors: list[str] = []
    parts = {p.part_ref: p for p in intent.parts}
    entry = m.spatial.parts[0]
    if intent.entry != entry.ref:
        errors.append(f"вход — часть {entry.ref} «{entry.name}»")
    for sp in m.spatial.parts:
        p = parts.get(sp.ref)
        if p is None:
            errors.append(f"нет обязательной части {sp.ref} «{sp.name}»")
            continue
        if p.secret != sp.secret:
            errors.append(f"{sp.ref}: тайность части задана каркасом — {'тайная' if sp.secret else 'открытая'}")
        if sp.below and p.level >= 0:
            errors.append(f"{sp.ref}: часть уровнем ниже входа (level < 0)")
        if sp.required and not p.required:
            errors.append(f"{sp.ref}: сюжетная цель — required=true")
    held = Counter(a for p in intent.parts for a in p.anchors)
    for h in m.holders():
        if held[h.key] != 1:
            errors.append(f"«{h.name}» ({h.key}) — ровно в одной части, в её anchors")
    known = {h.key for h in m.holders()}
    errors += [f"неизвестная привязка {k}" for k in sorted(set(held) - known)]
    if len(intent.parts) > MAX_AREAS:
        errors.append(f"частей больше {MAX_AREAS}")
    if not intent.approaches:
        errors.append("нужен хотя бы один подход снаружи")
    errors += [f"подход «{a.public_name}»: снаружи — само место, outside_id не задаётся"
               for a in intent.approaches if a.outside_id is not None]  # fmt: skip
    return errors
```

- [ ] **Step 5: Проверить GREEN.** `uv run pytest tests/test_layout_mandate.py tests/test_layout_spatial.py tests/test_layout_provider.py -q` — PASS; перебор не дольше нескольких секунд.

- [ ] **Step 6: Commit.**

```bash
git add app/core/layout/spatial.py tests/layout_plan_pilot.py tests/test_layout_mandate.py
git commit -m "Мандат места строит замысел комплекса без модели и проверяет обязательства каркаса"
```

---

### Task 3: Структура из мандата в исполнителе фазы

**Files:**
- Modify: `app/core/layout/store.py`, `app/core/layout/executor.py`, `app/core/world_generation/service.py:153-160` (передать `llm`)
- Create: `tests/test_layout_plan_phase.py`

**Interfaces:**
- Consumes: `Mandate`, `intent_candidates` (Task 2).
- Produces: `store.reserve_plan_layout`, `store.home_of`; `executor.run(..., llm=None)`; `_draft -> (bp, quality, notes, claim)`; `_publish_layout(ctx, row, bp, quality, notes)`.

- [ ] **Step 1: Написать failing tests** `tests/test_layout_plan_phase.py`:

```python
# ruff: noqa: F811
"""Структура комплекса из мандата каркаса (спецификация 2026-10-12, §3.2, §8): детерминированно, один раз."""

import pytest

from app.core.layout import spatial, store
from app.core.world_generation import storage
from app.db.models import Campaign, Entity, WorldGenerationState
from tests.game import run
from tests.layout_pilot import pilot_intent
from tests.layout_plan_pilot import temple_mandate
from tests.test_layout_preparation import _areas, _setup
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура


def _plan_root(settings, cid, mandate=None):
    async def go(ctx):
        root = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        campaign = await ctx.session.get(Campaign, cid)
        row = await store.reserve_plan_layout(
            ctx.session, campaign, ctx.world.entities[root], mandate or temple_mandate()
        )
        storage.activate(row)
        return root, row.id

    return _play(settings, cid, go)


def test_mandate_builds_complex_once(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.quality == "normal" and row.reservation["source"] == "plan" and row.llm_attempt_count == 0
    areas = _areas(settings, root)
    assert set(areas) == {"road", "narthex", "nave", "chapel", "crypt", "vault"}
    bp = store.blueprint_of(run(settings, lambda s: s.get(Entity, root)))
    assert bp.anchors["clue_relic"] == "chapel" and bp.anchors["npc:npc_warden"] == "road"
    before = dict(row.reservation)

    async def again(ctx):
        campaign = await ctx.session.get(Campaign, cid)
        return (await store.reserve_plan_layout(ctx.session, campaign, ctx.world.entities[root], temple_mandate())).id

    assert _play(settings, cid, again) == ref and _row(settings, ref).reservation == before


def test_broken_mandate_blocks_without_areas(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)

    async def corrupt(s):
        row = await s.get(WorldGenerationState, ref)
        row.reservation = {**row.reservation, "mandate": {"place": "x"}}
        await s.commit()

    run(settings, corrupt)
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "unsupported_source" and _areas(settings, root) == {}


def test_impossible_candidates_block(client, admin, settings, monkeypatch):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    impossible = pilot_intent().model_copy(deep=True)
    impossible.parts[-1].secret = True  # обязательная крипта за тайным ходом: как в поставке 1
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [impossible])
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "layout_unsatisfiable" and _areas(settings, root) == {}


def test_later_candidate_is_fallback(client, admin, settings, monkeypatch):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    real = spatial.intent_candidates
    impossible = pilot_intent().model_copy(deep=True)
    impossible.parts[-1].secret = True
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [impossible, *real(m)])
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.quality == "fallback" and "fallback:layout" in row.result_manifest["notes"]


def test_home_of_resolves_area_or_keeps_place(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    entities = run(settings, lambda s: _all(s, cid))
    assert store.home_of(entities, root, "npc:npc_warden") == root  # blueprint ещё нет
    _prepare(settings, cid, ref)
    entities = run(settings, lambda s: _all(s, cid))
    areas = _areas(settings, root)
    assert store.home_of(entities, root, "npc:npc_warden") == areas["road"].id
    assert store.home_of(entities, root, "npc:stranger") == areas["road"].id  # неизвестный — во вход
    assert store.home_of(entities, None, "npc:x") is None


async def _all(s, cid):
    from sqlalchemy import select

    return {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid))}


def test_host_intent_path_is_unchanged(client, admin, settings):
    from tests.test_layout_preparation import _complex

    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    assert _prepare(settings, cid, ref) == "ready" and _row(settings, ref).quality == "normal"
    assert len(_areas(settings, temple)) == 8


@pytest.fixture(autouse=True)
def _quiet_retry(_fast_retry):  # noqa: F811
    yield
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_plan_phase.py -q` — FAIL: нет `reserve_plan_layout`/`home_of`, исполнитель требует `intent`.

- [ ] **Step 3: Резерв и дом жителя** в `app/core/layout/store.py`:

```python
async def reserve_plan_layout(
    session: AsyncSession, campaign: Campaign, root: Entity, mandate: Mandate
) -> WorldGenerationState:
    """Резерв структуры из каркаса: мандат и seed фиксируются один раз; повтор возвращает ту же строку."""
    from app.core.world_generation import storage

    row = await storage.find(session, campaign.id, root.id, "location_layout")
    if row is not None:
        return row
    seed = layout_seed(campaign.id, root.id)
    reservation = {"phase": "location_layout", "seed": seed, "root_id": root.id,
                   "plot_id": _state(root).get("plot_id"), "source": "plan",
                   "mandate": mandate.model_dump(mode="json")}  # fmt: skip
    row = WorldGenerationState(campaign_id=campaign.id, target_entity_id=root.id, phase="location_layout",
                               status="unprepared", reservation=reservation, seed=seed,
                               generator_version=BUILDER_VERSION)  # fmt: skip
    session.add(row)
    await session.flush()
    return row


def home_of(entities: dict[str, Any], place_id: str | None, key: str) -> str | None:
    """Где в комплексе держать жителя или носителя ``key``: его участок, иначе входной; без blueprint — само место."""
    root = entities.get(place_id or "")
    bp = blueprint_of(root)
    if root is None or bp is None:
        return place_id
    return area_ids(root).get(bp.anchors.get(key) or bp.entry) or place_id
```

  (импорт `from app.core.layout.spatial import Mandate` — в `TYPE_CHECKING` или прямой: циклов нет.)

- [ ] **Step 4: Исполнитель.** В `app/core/layout/executor.py`:

```python
async def run(maker, dice_factory, claim: storage.Claim, phase: str, provider, llm=None) -> dict[str, Any]:
    if phase == "location_layout":
        bp, quality, notes, claim = await _draft(maker, claim, provider, llm)

        async def publish(ctx, row):
            return await _publish_layout(ctx, row, bp, quality, notes)

        return await storage.commit_with(maker, dice_factory, claim, publish, quality=quality)
    return await storage.commit_with(maker, dice_factory, claim, _publish_geometry)


async def _draft(maker, claim: storage.Claim, provider, llm=None) -> tuple[Blueprint, str, list[str], storage.Claim]:
    """Замысел резерва → blueprint. Ручной замысел ведущего — как в поставке 1; мандат каркаса — лестница
    детерминированных замыслов (модель добавляется в поставке 3, Task 6). Ни один не лёг — ``blocked``."""
    from app.core import plot_anchors
    from app.core.layout import spatial

    async with maker() as s:
        row = await s.get(WorldGenerationState, claim.ref)
        res = dict(row.reservation or {})
        waiting = [b.anchor_id for b in await plot_anchors.reserved_for(s, claim.campaign_id, row.target_entity_id)]
    kw = {"seed": int(res["seed"]), "root_id": res["root_id"], "plot_id": res.get("plot_id")}
    notes: list[str] = []
    try:
        if "mandate" in res:
            candidates = spatial.intent_candidates(spatial.Mandate.model_validate(res["mandate"]))
        else:
            candidates = [LayoutIntent.model_validate(res["intent"])]
    except (KeyError, ValidationError) as e:
        raise Blocked("unsupported_source", str(e)[:500]) from e
    errors: list[str] = []
    for i, intent in enumerate(candidates):
        for fallback in (False, True):
            try:
                bp = provider.propose(intent, fallback=fallback, **kw)
            except LayoutError as e:
                errors += e.errors[:3]
                log.info("структура %s: замысел %d%s не прошёл (%s)", claim.ref, i, " fallback" if fallback else "",
                         "; ".join(e.errors[:3]))  # fmt: skip
                continue
            quality = "normal" if i == 0 and not fallback and not notes else "fallback"
            if quality == "fallback":
                notes.append("fallback:layout")
            return _with_anchors(bp, waiting), quality, notes, claim
    raise Blocked("layout_unsatisfiable", "; ".join(errors[:6]))
```

  `_publish_layout(ctx, row, bp, quality, notes)`: заменить строку `notes = [] if quality == "normal" else ["fallback:layout"]` на использование параметра `notes`. В `service.Orchestrator._run`: `await executor.run(maker, self.dice_factory, claim, phase, self.layout_provider, llm=self.llm)`.

  Важно: `spatial.intent_candidates` вызывать через модуль (`spatial.intent_candidates`), а не импортом имени — тест подменяет его `monkeypatch`.

- [ ] **Step 5: Проверить GREEN.** `uv run pytest tests/test_layout_plan_phase.py tests/test_layout_preparation.py tests/test_layout_turn.py tests/test_layout_pilot.py -q` — PASS (прежние ожидания `fallback:layout` поставки 1 сохраняются).

- [ ] **Step 6: Commit.**

```bash
git add app/core/layout/store.py app/core/layout/executor.py app/core/world_generation/service.py tests/test_layout_plan_phase.py
git commit -m "Структура комплекса строится из мандата каркаса одним резервом"
```

---

### Task 4: Учёт вызовов модели по фазе подготовки

**Files:**
- Create: `alembic/versions/0023_llm_call_generation.py`, `tests/test_llm_accounting.py`
- Modify: `app/db/models.py:689-705` (`LlmCall`), `app/agents/llm.py` (`LLMReply`, `LiteLLMClient.complete`, `_collect_stream`), `app/agents/world_generator.py` (`Attempt`, `ask`), `app/core/world_generation/service.py:125-138` (`generation_id`, `tokens_reasoning`), `app/core/spend.py:19-25`

**Interfaces:**
- Consumes: последняя миграция поставки 2 (`revision = "0022"` — сверить в «Перед исполнением»).
- Produces: `LLMReply.reasoning_tokens`, `LlmCall.generation_id`, `LlmCall.tokens_reasoning`, `Attempt.tokens_reasoning`; отчёт расходов показывает `tokens_reasoning`.

- [ ] **Step 1: Написать failing tests** `tests/test_llm_accounting.py`:

```python
"""Учёт вызовов модели по фазам подготовки (спецификация 2026-10-12, §8): строка фазы и токены рассуждений."""

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config

from app.agents import llm as llm_mod
from app.agents.llm import LLMReply, ScriptedLLM
from app.core.world_generation.service import Orchestrator
from app.db.models import LlmCall
from app.gateway.coordination import InMemoryCoordination
from tests.test_master import rows
from tests.test_scene_model import _campaign, _named
from tests.test_world_generation import _fast_retry, _prepare, _room  # noqa: F401 — фикстура


def test_llm_call_migration_upgrade_and_downgrade(monkeypatch, tmp_path):
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    db_path = tmp_path / "calls.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")

    def columns() -> set[str]:
        with sqlite3.connect(db_path) as db:
            return {r[1] for r in db.execute("PRAGMA table_info(llm_calls)").fetchall()}

    command.upgrade(config, "0022")
    assert "generation_id" not in columns()
    command.upgrade(config, "0023")
    assert {"generation_id", "tokens_reasoning"} <= columns()
    command.downgrade(config, "0022")
    assert "generation_id" not in columns() and "tokens_reasoning" not in columns()


def test_scene_generation_call_is_tied_to_its_phase(client, admin, settings):
    cid = _campaign(client, admin, settings)
    _room_id, ref = _room(settings, cid)

    def reasoned(messages, tools):
        got = _named(messages, tools)
        return LLMReply(text="", tool_calls=[llm_mod.ToolCall("c1", got["tool_calls"][0][0], got["tool_calls"][0][1])],
                        model="m", tokens_in=100, tokens_out=40, reasoning_tokens=25, cost=0.01)  # fmt: skip

    assert _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([reasoned]))) == "ready"
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.tokens_reasoning == 25 and call.tokens_out == 40


def test_litellm_reply_reads_reasoning_tokens():
    usage = SimpleNamespace(prompt_tokens=10, completion_tokens=7,
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=3))  # fmt: skip
    assert llm_mod.reasoning_of(usage) == 3
    assert llm_mod.reasoning_of(SimpleNamespace(prompt_tokens=1, completion_tokens=1)) == 0
    assert llm_mod.reasoning_of(None) == 0
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_llm_accounting.py -q` — FAIL: нет миграции, `reasoning_tokens`, `reasoning_of`.

- [ ] **Step 3: Миграция** `alembic/versions/0023_llm_call_generation.py`:

```python
"""LLM call accounting by preparation phase (generative location maps spec, §8).

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.add_column(sa.Column("generation_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("tokens_reasoning", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_llm_calls_generation_id", ["generation_id"])


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.drop_index("ix_llm_calls_generation_id")
        batch.drop_column("tokens_reasoning")
        batch.drop_column("generation_id")
```

  `generation_id` без FK: строка фазы может уйти откатом хода (`inverse` delete), а учёт расходов остаётся.

- [ ] **Step 4: Модель и клиент.**
  - `LlmCall`: `generation_id: Mapped[str | None] = mapped_column(String(32), index=True)  # строка WorldGenerationState` и `tokens_reasoning: Mapped[int] = mapped_column(Integer, default=0, server_default="0")  # часть tokens_out у большинства провайдеров`.
  - `app/agents/llm.py`: `LLMReply.reasoning_tokens: int = 0`; функция

```python
def reasoning_of(usage: Any) -> int:
    """Токены рассуждений из usage LiteLLM; у провайдеров без них — 0. Обычно уже входят в completion_tokens."""
    details = getattr(usage, "completion_tokens_details", None)
    return int(getattr(details, "reasoning_tokens", 0) or 0)
```

    и `reasoning_tokens=reasoning_of(usage)` в обоих `LLMReply(...)` (`complete` и `_collect_stream`).
  - `world_generator.Attempt`: `tokens_reasoning: int = 0`; в `ask` после токенов: `attempt.tokens_reasoning = reply.reasoning_tokens`.
  - `service.Orchestrator._propose`: в `LlmCall(...)` добавить `tokens_reasoning=attempt.tokens_reasoning, generation_id=claim.ref`.
  - `app/core/spend.py::_add`: ключ `"tokens_reasoning"` в bucket и `b["tokens_reasoning"] += c.tokens_reasoning or 0`; в `summary` по умолчанию добавить `"tokens_reasoning": 0`.

- [ ] **Step 5: Проверить GREEN.** `uv run pytest tests/test_llm_accounting.py tests/test_scene_model.py tests/test_spend.py -q` (если `test_spend.py` нет — `uv run pytest -q -k spend`). PostgreSQL-рендер миграции — `uv run alembic upgrade 0023 --sql` без ошибок.

- [ ] **Step 6: Commit.**

```bash
git add alembic/versions/0023_llm_call_generation.py app/db/models.py app/agents/llm.py app/agents/world_generator.py app/core/world_generation/service.py app/core/spend.py tests/test_llm_accounting.py
git commit -m "Вызовы модели подготовки привязаны к фазе и считают токены рассуждений"
```

---

### Task 5: Техническая модель структуры

**Files:**
- Create: `app/agents/layout_model.py`, `tests/test_layout_model.py`

**Interfaces:**
- Consumes: `Mandate`, `obligations` (Task 2); `PartIntent`, `DetailIntent`, `ApproachIntent`, `BandIntent`, `LayoutIntent` (поставка 1); `world_generator.Attempt` (Task 4); `Blocked`.
- Produces: см. «Контракты» (`spec`, `brief`, `to_intent`, `ask`, константы).

- [ ] **Step 1: Написать failing tests** `tests/test_layout_model.py` (без БД):

```python
"""Техническая модель структуры комплекса (спецификация 2026-10-12, §3.2, §8): схема, бюджет, разбор, коррекция."""

import asyncio
import json

import pytest

from app.agents import layout_model
from app.agents.llm import LLMError, LLMReply, ScriptedLLM, ToolCall
from app.core.layout.contracts import LayoutError
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.world_generation.contracts import Blocked
from tests.layout_plan_pilot import model_layout, temple_mandate, temple_plan

KEYS = ["clue_relic", "npc:npc_warden"]


def _check(intent):
    DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")


def _ask(llm, msgs=None):
    return asyncio.run(layout_model.ask(llm, temple_mandate(), model="m", api_base=None, msgs=msgs if msgs is not None
                                        else [], check=_check))  # fmt: skip


def test_schema_is_strict_and_lists_holders():
    fn = layout_model.spec(temple_mandate())["function"]
    assert fn["name"] == layout_model.TOOL
    params = fn["parameters"]
    part = params["properties"]["parts"]["items"]
    assert params["additionalProperties"] is False and part["additionalProperties"] is False
    assert part["properties"]["anchors"]["items"]["enum"] == KEYS
    assert "outside_id" not in params["properties"]["approaches"]["items"]["properties"]
    assert set(part["properties"]["shape"]["enum"]) == {"rect", "circle", "l_shape", "corridor", "open", "cave"}


def test_brief_carries_no_plot_secrets():
    plan = temple_plan()
    port = plan["locations"][0]
    warden = next(n for n in plan["npcs"] if n["id"] == "npc_warden")
    text = layout_model.SYSTEM + layout_model.brief(temple_mandate()) + json.dumps(layout_model.spec(temple_mandate()),
                                                                                  ensure_ascii=False)  # fmt: skip
    for secret in (port["secret"], warden["secret"], warden["fear"], "Журнал смотрителя подчищен", "Мать Ирса"):
        assert secret not in text
    assert "Тайник" in text and "secret" in text and "clue_relic" in text


def test_brief_trims_optional_context_but_not_obligations(monkeypatch):
    m = temple_mandate()
    full = layout_model.brief(m)
    budget = layout_model.estimate(layout_model.SYSTEM + full)
    budget += layout_model.estimate(json.dumps(layout_model.spec(m), ensure_ascii=False))
    monkeypatch.setattr(layout_model, "MAX_IN", budget - 5)
    trimmed = layout_model.brief(m)
    assert trimmed is not None and m.mood not in trimmed and "clue_relic" in trimmed and "Крипта" in trimmed
    monkeypatch.setattr(layout_model, "MAX_IN", 50)
    assert layout_model.brief(m) is None


def test_valid_answer_becomes_intent_with_tokens():
    reply = LLMReply(text="", tool_calls=[ToolCall("c1", layout_model.TOOL, model_layout(KEYS))], model="tech",
                     tokens_in=900, tokens_out=700, reasoning_tokens=300, cost=0.002, latency_ms=40)  # fmt: skip
    intent, attempt, retry = _ask(ScriptedLLM([reply]))
    assert intent is not None and retry is None and attempt.error is None
    assert intent.entry == "road" and all(a.outside_id is None for a in intent.approaches)
    assert (attempt.tokens_in, attempt.tokens_out, attempt.tokens_reasoning) == (900, 700, 300)


@pytest.mark.parametrize(
    "mutate, text",
    [
        (lambda r: r["parts"].pop(), "нет обязательной части crypt"),
        (lambda r: r.update(colour="red"), "только"),
        (lambda r: r["approaches"][0].update(outside_id="en_x"), "outside_id"),
        (
            lambda r: next(p for p in r["parts"] if p["part_ref"] == "vault").update(secret=False, required=True),
            "vault",
        ),
    ],
)
def test_invalid_answer_returns_correction(mutate, text):
    raw = model_layout(KEYS)
    mutate(raw)
    msgs: list = []
    intent, attempt, retry = _ask(ScriptedLLM([{"tool_calls": [(layout_model.TOOL, raw)]}]), msgs)
    assert intent is None and retry and text in retry and attempt.error
    assert "Сервер не принял план" in msgs[-1]["content"]


def test_layout_errors_from_provider_are_corrections():
    def bad(intent):
        raise LayoutError(["часть «nave» не помещается рядом с «narthex»"])

    raw = model_layout(KEYS)
    intent, attempt, retry = asyncio.run(layout_model.ask(
        ScriptedLLM([{"tool_calls": [(layout_model.TOOL, raw)]}]), temple_mandate(), model="m", api_base=None,
        msgs=[], check=bad))  # fmt: skip
    assert intent is None and "не помещается" in retry


def test_model_failure_is_not_corrected():
    class Down:
        async def complete(self, *a, **kw):
            raise LLMError("сеть")

    intent, attempt, retry = _ask(Down())
    assert intent is None and retry is None and "сеть" in attempt.error


def test_request_respects_output_budget():
    llm = ScriptedLLM([{"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}])
    seen = {}
    orig = llm.complete

    async def spy(messages, **kw):
        seen.update(kw)
        return await orig(messages, **kw)

    llm.complete = spy
    _ask(llm)
    assert seen["max_tokens"] == layout_model.MAX_OUT == 3000 and seen["tool_choice"] == "required"
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_model.py -q` — FAIL: модуля нет.

- [ ] **Step 3: Реализовать** `app/agents/layout_model.py`:

```python
"""Техническая модель структуры комплекса (спецификация 2026-10-12, §3.2, §8; поставка 3).

Модель предлагает замысел — части, связи, проходы, детали, полосы рельефа — по мандату места. Координаты, endpoints и
края считает детерминированный provider поставки 1: невозможную геометрию модель выдать не может, её ошибки — это
ошибки ``obligations``/``validate``, они возвращаются одной корректирующей попыткой. Секреты каркаса в запрос не
идут: тайность задают флаги частей. Лимит вызовов и учёт — в исполнителе фазы (app/core/layout/executor.py).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any, get_args

from pydantic import ValidationError

from app.agents.world_generator import Attempt
from app.core.layout.contracts import MAX_AREAS, MAX_SIDE, LayoutError
from app.core.layout.intent import BandIntent, DetailIntent, LayoutIntent, PartIntent
from app.core.layout.spatial import Mandate, obligations
from app.core.world_generation.contracts import Blocked

TOOL = "submit_layout"
PURPOSE = "location_layout"
TIMEOUT = 60.0  # секунд: меньше lease фазы, опоздавший ответ всё равно отклонит CAS
MAX_IN = 6000  # входных токенов на вызов (спецификация §8)
MAX_OUT = 3000  # выходных токенов вместе с рассуждениями
CHARS_PER_TOKEN = 3.2  # как оценка архитектора (app/agents/architect.py)

SYSTEM = (
    "Ты планировщик пространства текстовой ролевой игры. Сервер дал обязательные части места, подходы и привязки. "
    "Предложи устройство комплекса одним вызовом submit_layout.\n"
    "- Каждая обязательная часть — ровно с тем part_ref, тайная — secret=true, «уровнем ниже» — level=-1 и "
    "passage_kind=stairs, сюжетная цель — required=true. Первая обязательная часть — entry.\n"
    "- Можно добавить коридоры и комнаты (всего до 12 частей), но не убирать обязательные.\n"
    "- connects_to — часть выше по списку, side — с какой стороны родителя (n, e, s, w).\n"
    "- Каждую привязку из списка укажи ровно в одной части, в её anchors.\n"
    "- Подходы ведут снаружи к частям; outside_id не задаётся.\n"
    "- Дорога, тропа и ручей — полосы bands в клетках плана; клетка 5 футов, сторона части до 30 клеток.\n"
    "- Названия (name, public_name, passage_name) видят игроки: без тайн и спойлеров. Не придумывай механику, "
    "существ и сокровища: только устройство места."
)


def estimate(text: str) -> int:
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _enum(model, field: str) -> list[str]:
    return list(get_args(model.model_fields[field].annotation))


def spec(m: Mandate) -> dict[str, Any]:
    keys = [h.key for h in m.holders()]
    detail = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "detail_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "name": {"type": "string", "maxLength": 60},
            "kind": {"type": "string", "enum": _enum(DetailIntent, "kind")},
            "cells": {"type": "array", "maxItems": 4,
                      "items": {"type": "array", "minItems": 4, "maxItems": 4, "items": {"type": "integer"}}},
            "solid": {"type": "boolean"},
        },
        "required": ["detail_ref", "name", "cells"],
    }  # fmt: skip
    part = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "part_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "role": {"type": "string", "maxLength": 32},
            "name": {"type": "string", "maxLength": 128},
            "public_name": {"type": "string", "maxLength": 128},
            "description": {"type": "string", "maxLength": 1000},
            "environment": {"type": "string", "enum": _enum(PartIntent, "environment")},
            "shape": {"type": "string", "enum": _enum(PartIntent, "shape")},
            "size": {"type": "string", "enum": _enum(PartIntent, "size")},
            "cols": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "rows": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
            "level": {"type": "integer", "minimum": -3, "maximum": 3},
            "connects_to": {"type": "string"},
            "side": {"type": "string", "enum": ["n", "e", "s", "w"]},
            "passage_kind": {"type": "string", "enum": _enum(PartIntent, "passage_kind")},
            "passage_name": {"type": "string", "maxLength": 60},
            "passage_state": {"type": "string", "enum": _enum(PartIntent, "passage_state")},
            "secret": {"type": "boolean"},
            "required": {"type": "boolean"},
            "anchors": {"type": "array", "items": {"type": "string", "enum": keys}},
            "details": {"type": "array", "maxItems": 16, "items": detail},
        },
        "required": ["part_ref", "name", "public_name"],
    }  # fmt: skip
    approach = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "part_ref": {"type": "string"},
            "side": {"type": "string", "enum": ["n", "e", "s", "w"]},
            "kind": {"type": "string", "enum": ["edge", "door", "gate", "arch", "passage", "gap"]},
            "public_name": {"type": "string", "maxLength": 60},
            "band": {"type": "string"},
            "width": {"type": "integer", "minimum": 1, "maximum": MAX_SIDE},
        },
        "required": ["part_ref", "side", "public_name"],
    }  # fmt: skip
    band = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "band_ref": {"type": "string", "pattern": r"^[a-z][a-z0-9_]{0,31}$"},
            "kind": {"type": "string", "enum": _enum(BandIntent, "kind")},
            "axis": {"type": "string", "enum": _enum(BandIntent, "axis")},
            "at": {"type": "integer"}, "width": {"type": "integer", "minimum": 1, "maximum": 4},
            "start": {"type": "integer"}, "end": {"type": "integer"},
        },
        "required": ["band_ref", "kind", "axis", "at"],
    }  # fmt: skip
    schema = {
        "type": "object", "additionalProperties": False,
        "properties": {
            "entry": {"type": "string"},
            "parts": {"type": "array", "minItems": 1, "maxItems": MAX_AREAS, "items": part},
            "approaches": {"type": "array", "minItems": 1, "maxItems": 8, "items": approach},
            "bands": {"type": "array", "maxItems": 6, "items": band},
        },
        "required": ["entry", "parts", "approaches"],
    }  # fmt: skip
    return {"type": "function", "function": {"name": TOOL, "description": "Сдать устройство места.",
                                             "parameters": schema}}  # fmt: skip


def _lines(m: Mandate, *, mood: bool, purposes: bool) -> list[str]:
    sp = m.spatial
    lines = [f"Место: «{m.place}». Окружение: {sp.environment}; масштаб: {sp.scale}."]
    if mood and m.mood:
        lines.append(f"Настроение: {m.mood}")
    lines.append("Обязательные части (part_ref «название»):")
    for i, p in enumerate(sp.parts):
        flags = [x for x, on in (("вход", i == 0), ("открытая местность", p.outdoor), ("уровнем ниже", p.below),
                                 ("тайная — secret=true", p.secret), ("сюжетная цель — required=true", p.required))
                 if on]  # fmt: skip
        what = f" — {p.purpose}" if purposes and p.purpose else ""
        lines.append(f"- {p.ref} «{p.name}»{what}" + (f" [{'; '.join(flags)}]" if flags else ""))
    lines.append("Подходы снаружи: " + "; ".join(f"«{a.name}» ({a.kind})" for a in sp.approaches))
    if m.holders():
        lines.append("Привязки (каждую — в anchors ровно одной части): "
                     + "; ".join(f"{h.key} «{h.name}»" for h in m.holders()))  # fmt: skip
    return lines


def brief(m: Mandate) -> str | None:
    """Запрос в бюджете ``MAX_IN``: сначала уходит настроение, потом пояснения частей. Обязательное не урезается;
    не помещается и оно — None (исполнитель уходит в fallback ``context_budget``)."""
    fixed = estimate(SYSTEM) + estimate(json.dumps(spec(m), ensure_ascii=False))
    for mood, purposes in ((True, True), (False, True), (False, False)):
        text = "\n".join(_lines(m, mood=mood, purposes=purposes))
        if fixed + estimate(text) <= MAX_IN:
            return text
    return None


def to_intent(m: Mandate, args: Any) -> LayoutIntent:
    """Ответ модели → замысел. Подходы всегда ведут в само место: outside_id модель не задаёт."""
    if not isinstance(args, dict) or set(args) - {"entry", "parts", "approaches", "bands"}:
        raise Blocked("invalid_proposal", "допустимы только поля entry, parts, approaches, bands")
    for ap in args.get("approaches") or []:
        if isinstance(ap, dict) and ap.get("outside_id") is not None:
            raise Blocked("invalid_proposal", "подход: outside_id не задаётся, снаружи — само место")
    try:
        intent = LayoutIntent.model_validate({**args, "schema_version": 1})
    except ValidationError as e:
        why = "; ".join(f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in e.errors()[:6])
        raise Blocked("invalid_proposal", why) from e
    errors = obligations(intent, m)
    if errors:
        raise Blocked("invalid_proposal", "; ".join(errors[:8]))
    return intent


async def ask(
    llm, m: Mandate, *, model: str, api_base: str | None, msgs: list, check: Callable[[LayoutIntent], None]
) -> tuple[LayoutIntent | None, Attempt, str | None]:
    """Один вызов. (замысел или None, учёт, причина для корректирующей попытки или None — сбой модели)."""
    if not msgs:
        text = brief(m)
        if text is None:
            raise Blocked("context_budget", "обязательные факты места не помещаются в бюджет запроса")
        msgs += [{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}]
    attempt = Attempt(model=model)
    try:
        reply = await asyncio.wait_for(
            llm.complete(
                msgs,
                model=model,
                tools=[spec(m)],
                tool_choice="required",
                max_tokens=MAX_OUT,
                temperature=0.7,
                api_base=api_base,
            ),  # fmt: skip
            TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 — сбой или таймаут модели ведёт к fallback, а не к ошибке хода
        attempt.error = f"{type(e).__name__}: {e}"[:2000]
        return None, attempt, None
    attempt.model = reply.model or model
    attempt.tokens_in, attempt.tokens_out = reply.tokens_in, reply.tokens_out
    attempt.tokens_reasoning = reply.reasoning_tokens
    attempt.cost, attempt.latency_ms = reply.cost or 0.0, reply.latency_ms or 0
    tc = next((t for t in reply.tool_calls if t.name == TOOL), None)
    try:
        if tc is None:
            raise Blocked("invalid_proposal", "нужен вызов submit_layout")
        intent = to_intent(m, tc.arguments)
        try:
            check(intent)
        except LayoutError as e:
            raise Blocked("invalid_proposal", "; ".join(e.errors[:8])) from e
        return intent, attempt, None
    except Blocked as e:
        attempt.error = e.detail[:2000]
        msgs.append(reply.message or {"role": "assistant", "content": reply.text})
        msgs.append({"role": "user", "content": f"Сервер не принял план: {e.detail}. Исправь и сдай заново."})
        return None, attempt, e.detail
```

  Примечание: `test_brief_trims_optional_context_but_not_obligations` рассчитывает порог так, что полный brief не помещается, а без настроения — помещается; если первая ступень сокращения окажется недостаточной из-за округления, допустимо уменьшить на `-1` вместо `-5` — проверяется только поведение: настроение уходит первым, привязки остаются.

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_layout_model.py -q` — PASS. `uv run ruff check app/agents/layout_model.py tests/test_layout_model.py`.

- [ ] **Step 5: Commit.**

```bash
git add app/agents/layout_model.py tests/test_layout_model.py
git commit -m "Техническая модель предлагает устройство места по мандату без секретов каркаса"
```

---

### Task 6: Модель в фазе структуры: лимит, расходы, сбои

**Files:**
- Modify: `app/core/layout/executor.py` (`_draft`, новый `_ask_model`), `app/core/world_generation/service.py` (`_model_of` — без изменений, переиспользуется)
- Create: `tests/test_layout_model_phase.py`

**Interfaces:**
- Consumes: `layout_model.ask/brief/PURPOSE` (Task 5), `storage.reserve_llm_call`, `service.LLM_LIMIT`, `service._model_of`, `LlmCall.generation_id/tokens_reasoning` (Task 4), флаг `location_layouts_llm` (Task 7 добавляет его в API; здесь читается из `campaign.settings`).
- Produces: заметки фазы `fallback:{llm_limit|invalid_proposal|llm_failed|context_budget|spend_limit}`; `LlmCall(purpose="location_layout", generation_id=ref)`.

- [ ] **Step 1: Написать failing tests** `tests/test_layout_model_phase.py` (образец — `tests/test_scene_model.py`):

```python
# ruff: noqa: F811
"""Модель в фазе структуры (спецификация 2026-10-12, §8): один вызов и одна коррекция, fallback, лимит в БД."""

from datetime import timedelta

from app.agents import layout_model
from app.agents.llm import ScriptedLLM
from app.core.world_generation.service import Orchestrator
from app.db.models import Campaign, LlmCall, WorldGenerationState, now
from app.gateway.coordination import InMemoryCoordination
from tests.game import run
from tests.layout_plan_pilot import model_layout
from tests.test_layout_plan_phase import _plan_root
from tests.test_layout_preparation import _areas, _setup
from tests.test_master import rows
from tests.test_scene_model import _with
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура

KEYS = ["clue_relic", "npc:npc_warden"]


def _good(messages, tools):
    return {"tool_calls": [(layout_model.TOOL, model_layout(KEYS))]}


def _bad(messages, tools):
    raw = model_layout(KEYS)
    raw["parts"] = [p for p in raw["parts"] if p["part_ref"] != "crypt"]
    return {"tool_calls": [(layout_model.TOOL, raw)]}


def _flags(settings, cid, **flags):
    async def go(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), **flags}
        await s.commit()

    run(settings, go)


def _orch(llm):
    return Orchestrator(InMemoryCoordination(), llm=llm)


def _on(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _flags(settings, cid, location_layouts_llm=True)
    return cid


def test_model_layout_is_used_and_counted(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    row = _row(settings, ref)
    assert row.quality == "normal" and row.llm_attempt_count == 1 and row.result_manifest["notes"] == []
    assert set(_areas(settings, root)) == {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}
    (call,) = rows(settings, LlmCall, LlmCall.generation_id == ref)
    assert call.purpose == layout_model.PURPOSE and call.error is None


def test_one_correction_then_deterministic_fallback(client, admin, settings):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_bad, _good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    assert _row(settings, ref).llm_attempt_count == 2 and _row(settings, ref).quality == "normal"
    assert "Сервер не принял план" in llm.requests[1]["messages"][-1]["content"]

    cid2 = cid
    root2, ref2 = _plan_root(settings, cid2)
    llm = ScriptedLLM([_bad, _bad, _good])
    assert _prepare(settings, cid2, ref2, _orch(llm)) == "ready"
    row = _row(settings, ref2)
    assert row.quality == "fallback" and row.llm_attempt_count == 2 and len(llm.requests) == 2
    assert "fallback:invalid_proposal" in row.result_manifest["notes"]
    assert set(_areas(settings, root2)) == {"road", "narthex", "nave", "chapel", "crypt", "vault"}
    assert len(rows(settings, LlmCall, LlmCall.generation_id == ref2)) == 2


def test_limit_survives_restart_retry_and_reentry(client, admin, settings):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)

    async def spent(s):
        (await s.get(WorldGenerationState, ref)).llm_attempt_count = 2
        await s.commit()

    run(settings, spent)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready"
    assert llm.requests == [] and "fallback:llm_limit" in _row(settings, ref).result_manifest["notes"]
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []  # готово: ни одного вызова


def test_flag_off_spend_limit_and_model_down(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
    assert _row(settings, ref).quality == "normal"  # модель выключена: детерминированный путь — обычный

    _flags(settings, cid, location_layouts_llm=True, spend_limit_usd=0.0)
    _root2, ref2 = _plan_root(settings, cid)
    assert _prepare(settings, cid, ref2, _orch(llm)) == "ready" and llm.requests == []
    assert "fallback:spend_limit" in _row(settings, ref2).result_manifest["notes"]

    _flags(settings, cid, spend_limit_usd=None)
    _root3, ref3 = _plan_root(settings, cid)
    down = ScriptedLLM([])
    assert _prepare(settings, cid, ref3, _orch(down)) == "ready"
    row = _row(settings, ref3)
    assert row.llm_attempt_count == 1 and "fallback:llm_failed" in row.result_manifest["notes"]


def test_context_over_budget_skips_model(client, admin, settings, monkeypatch):
    cid = _on(client, admin, settings)
    _root, ref = _plan_root(settings, cid)
    monkeypatch.setattr(layout_model, "MAX_IN", 50)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
    row = _row(settings, ref)
    assert row.llm_attempt_count == 0 and "fallback:context_budget" in row.result_manifest["notes"]


def test_late_answer_after_lost_lease_is_dropped(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)

    def slow(messages, tools):
        async def expire(s):
            row = await s.get(WorldGenerationState, ref)
            row.lease_until = now() - timedelta(seconds=1)
            row.lease_token = "чужой"
            row.revision += 1
            await s.commit()

        import asyncio
        import threading

        done = threading.Event()
        threading.Thread(target=lambda: (asyncio.run(_with(settings, expire)), done.set())).start()
        done.wait()
        return _good(messages, tools)

    assert _prepare(settings, cid, ref, _orch(ScriptedLLM([slow]))) == "lost"
    assert _areas(settings, root) == {}


def test_host_intent_never_calls_model(client, admin, settings):
    from tests.test_layout_preparation import _complex

    cid = _on(client, admin, settings)
    _village, _temple, ref = _complex(settings, cid)
    llm = ScriptedLLM([_good])
    assert _prepare(settings, cid, ref, _orch(llm)) == "ready" and llm.requests == []
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_model_phase.py -q` — FAIL: модель не вызывается, заметок нет.

- [ ] **Step 3: Подключить модель** в `app/core/layout/executor.py`. `_draft` целиком (Task 3 + модель):

```python
async def _draft(maker, claim: storage.Claim, provider, llm=None) -> tuple[Blueprint, str, list[str], storage.Claim]:
    """Замысел резерва → blueprint. Ручной замысел ведущего — как в поставке 1. Мандат каркаса — сначала модель
    (если включена и расходы позволяют), затем лестница детерминированных замыслов. Ни один не лёг — ``blocked``."""
    from app.core import plot_anchors
    from app.core.layout import spatial
    from app.core.world_generation.service import _model_of

    async with maker() as s:
        row = await s.get(WorldGenerationState, claim.ref)
        res = dict(row.reservation or {})
        waiting = [b.anchor_id for b in await plot_anchors.reserved_for(s, claim.campaign_id, row.target_entity_id)]
        campaign = await s.get(Campaign, claim.campaign_id)
        wants = llm is not None and "mandate" in res and bool((campaign.settings or {}).get("location_layouts_llm"))
        model = await _model_of(s, campaign) if wants else None
        over = wants and await _over_spend(s, campaign)
    kw = {"seed": int(res["seed"]), "root_id": res["root_id"], "plot_id": res.get("plot_id")}
    notes: list[str] = []
    try:
        mandate = spatial.Mandate.model_validate(res["mandate"]) if "mandate" in res else None
        intent0 = None if mandate is not None else LayoutIntent.model_validate(res["intent"])
    except (KeyError, ValidationError) as e:
        raise Blocked("unsupported_source", str(e)[:500]) from e
    if mandate is not None:
        if over:
            notes.append("fallback:spend_limit")
        elif model is not None:
            intent, reason, claim = await _ask_model(maker, claim, llm, model, mandate, provider, kw)
            if intent is not None:
                return _with_anchors(provider.propose(intent, **kw), waiting), "normal", notes, claim
            notes.append(f"fallback:{reason}")
        candidates = spatial.intent_candidates(mandate)
    else:
        candidates = [intent0]
    errors: list[str] = []
    for i, intent in enumerate(candidates):
        for fallback in (False, True):
            try:
                bp = provider.propose(intent, fallback=fallback, **kw)
            except LayoutError as e:
                errors += e.errors[:3]
                log.info("структура %s: замысел %d%s не прошёл (%s)", claim.ref, i, " fallback" if fallback else "",
                         "; ".join(e.errors[:3]))  # fmt: skip
                continue
            quality = "normal" if i == 0 and not fallback and not notes else "fallback"
            if i > 0 or fallback:
                notes.append("fallback:layout")
            return _with_anchors(bp, waiting), quality, notes, claim
    raise Blocked("layout_unsatisfiable", "; ".join(errors[:6]))
```

  После заметки модели (`fallback:<причина>`) даже первый детерминированный кандидат даёт `quality="fallback"`; `fallback:layout` добавляется только при сходе по лестнице.

```python
async def _over_spend(s, campaign) -> bool:
    limit = (campaign.settings or {}).get("spend_limit_usd")
    if limit is None:
        return False
    spent = await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == campaign.id))
    return float(spent or 0.0) >= float(limit)


async def _ask_model(maker, claim, llm, model, mandate, provider, kw) -> tuple[LayoutIntent | None, str, Claim]:
    """Замысел модели в пределах лимита фазы (``LLM_LIMIT``); вызов занимается до сетевого запроса, учёт —
    в ``LlmCall`` с ``generation_id``. Возвращает (замысел или None, причина fallback, обновлённый claim)."""
    from app.agents import layout_model
    from app.core.world_generation.service import LLM_LIMIT

    name, api_base, seat_id = model
    if layout_model.brief(mandate) is None:
        return None, "context_budget", claim
    msgs: list = []
    calls: list[LlmCall] = []
    reason = "llm_failed"

    def check(intent: LayoutIntent) -> None:
        provider.propose(intent, **kw)

    try:
        while True:
            held = await storage.reserve_llm_call(maker, claim, LLM_LIMIT)
            if held is None:
                reason = reason if calls else "llm_limit"
                break
            claim = held
            got, attempt, retry = await layout_model.ask(llm, mandate, model=name, api_base=api_base, msgs=msgs,
                                                         check=check)  # fmt: skip
            calls.append(LlmCall(campaign_id=claim.campaign_id, seat_id=seat_id, turn_id=None,
                                 purpose=layout_model.PURPOSE, model=attempt.model, tokens_in=attempt.tokens_in,
                                 tokens_out=attempt.tokens_out, tokens_reasoning=attempt.tokens_reasoning,
                                 cost=attempt.cost, latency_ms=attempt.latency_ms, error=attempt.error,
                                 generation_id=claim.ref))  # fmt: skip
            if got is not None:
                return got, "", claim
            if retry is None:
                break  # сбой модели, а не ошибка ответа: корректировать нечего
            reason = "invalid_proposal"
    finally:
        if calls:
            async with maker() as s:
                s.add_all(calls)
                await s.commit()
    log.info("структура %s: fallback (%s)", claim.ref, reason)
    return None, reason, claim
```

  `_model_of` — `from app.core.world_generation.service import _model_of` внутри `_draft` (как `LLM_LIMIT`: циклический импорт на уровне модуля недопустим, `service` импортирует `executor` лениво). Импорты модуля: `from sqlalchemy import func, select`, `from app.db.models import Campaign, Entity, LlmCall, WorldGenerationState`, `from app.core.world_generation.storage import Claim`.

  Ответ после потери lease: `commit_with` → `_own` бросает `LeaseLost` → `Orchestrator._run` возвращает `lost` (поставка 1); `reserve_llm_call` следующей попытки тоже бросит `LeaseLost`. Ничего не публикуется.

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_layout_model_phase.py tests/test_layout_plan_phase.py tests/test_scene_model.py tests/test_layout_preparation.py -q` — PASS.

- [ ] **Step 5: Commit.**

```bash
git add app/core/layout/executor.py tests/test_layout_model_phase.py
git commit -m "Структуру места предлагает модель в пределах лимита фазы и расходов"
```

---

### Task 7: Флаги кампании и разворот места каркаса в комплекс

**Files:**
- Create: `app/core/layout/plan.py`, `tests/test_layout_develop.py`
- Modify: `app/config.py:35` (`CAMPAIGN_FLAGS`), `app/api/schemas.py:349-352` (`CampaignPatch`), `app/api/campaigns.py:258-279`, `app/tools/plot.py` (`develop`), `app/core/world_generation/service.py::_dependencies`, `web/src/lib/campaign.ts:42-43`, `web/src/cabinet/SettingsTab.tsx` (секция «Наполнение мест»), `web/openapi.json`, `web/src/lib/api.gen.ts`

**Interfaces:**
- Consumes: `store.reserve_plan_layout`, `Mandate` (Tasks 2–3); `plot_anchors.reserved_for`, `anchor_reserve`; `adventure.module_place`; `relocate_scene` (async после поставки 2).
- Produces: `layout_plan.eligible/mandate_for/reserve_from_plan`; результат `develop` получает `layout: {accepted, operation_ref}`; флаги `location_layouts`, `location_layouts_llm`.

- [ ] **Step 1: Написать failing tests** `tests/test_layout_develop.py`:

```python
# ruff: noqa: F811
"""Разворот места каркаса в комплекс (спецификация 2026-10-12, §3.1, §3.2, §8, §9)."""

import copy

from app.core.layout import store
from app.core.world_generation import storage
from app.db.models import Campaign, Entity, WorldGenerationState
from app.tools.registry import execute
from tests.game import import_base, party, quiet, run
from tests.layout_plan_pilot import temple_plan
from tests.test_lead import set_plan
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _campaign(client, admin, settings, plan=None, **flags):
    import_base(settings)
    c, heads, hero = party(client, admin)
    quiet(client)
    set_plan(settings, c["id"], plan or temple_plan())

    async def go(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {**(campaign.settings or {}), **flags}
        await s.commit()

    run(settings, go)
    return c["id"]


def _develop(settings, cid, sketch_id="loc_port", here=False):
    return _play(settings, cid, lambda ctx: _ok(ctx, "develop", {"sketch_id": sketch_id, "details": "-", "here": here}))


def test_develop_reserves_layout_with_mandate(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    out = _develop(settings, cid)
    ref = out["layout"]["operation_ref"]
    row = _row(settings, ref)
    assert row.phase == "location_layout" and row.requested_at is not None and row.target_entity_id == out["entity_id"]
    mandate = row.reservation["mandate"]
    assert mandate["place"] == "Старый храм" and [p["ref"] for p in mandate["spatial"]["parts"]][0] == "road"
    assert [h["name"] for h in mandate["anchors"]] == ["Журнал смотрителя"]
    assert [h["key"] for h in mandate["residents"]] == ["npc:npc_warden"]
    assert "Смотритель порта в культе" not in str(mandate)  # секрет места в мандат не попадает
    assert _prepare(settings, cid, ref) == "ready"
    assert len(rows(settings, Entity, Entity.location_id == out["entity_id"])) == 6


def test_no_layout_without_flag_spatial_or_for_modules(client, admin, settings):
    cid = _campaign(client, admin, settings)
    assert "layout" not in _develop(settings, cid)
    plan = temple_plan()
    for loc in plan["locations"]:
        loc.pop("spatial", None)
    cid2 = _campaign(client, admin, settings, plan=plan, location_layouts=True)
    assert "layout" not in _develop(settings, cid2)
    assert not rows(settings, WGS, WGS.phase == "location_layout")


def test_root_preparation_waits_for_structure(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True, scene_generation=True)
    out = _develop(settings, cid, here=True)
    root_id = out["entity_id"]
    initial = run(settings, lambda s: storage.find(s, cid, root_id, "location_initial"))
    assert initial is not None and initial.requested_at is not None
    assert _prepare(settings, cid, initial.id) == "ready"  # тянет за собой структуру
    layout = run(settings, lambda s: storage.find(s, cid, root_id, "location_layout"))
    assert layout.status == "ready"
    journal = [e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Журнал смотрителя"]
    assert journal == []  # носитель ждёт часовню, а не лёг у корня


def test_flags_are_patchable_and_known(client, admin, settings):
    from app.config import CAMPAIGN_FLAGS

    assert {"location_layouts", "location_layouts_llm"} <= set(CAMPAIGN_FLAGS)
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    r = client.patch(f"/api/campaigns/{c['id']}", json={"location_layouts": True, "location_layouts_llm": True},
                     headers=admin)  # fmt: skip
    assert r.status_code == 200 and r.json()["settings"]["location_layouts"] is True
    r = client.patch(f"/api/campaigns/{c['id']}", json={"location_layouts": None}, headers=admin)
    assert r.json()["settings"]["location_layouts"] is True  # None не сбрасывает флаг, как scene_generation


def test_enabling_mid_campaign_keeps_developed_places(client, admin, settings):
    cid = _campaign(client, admin, settings)
    out = _develop(settings, cid, here=True)

    async def on(s):
        campaign = await s.get(Campaign, cid)
        campaign.settings = {**campaign.settings, "location_layouts": True}
        await s.commit()

    run(settings, on)

    async def again(ctx):
        return await execute(ctx, "develop", {"sketch_id": "loc_port", "details": "-"})

    assert not _play(settings, cid, again)["ok"]  # уже развёрнут: ничего не пересобирается
    assert not rows(settings, WGS, WGS.target_entity_id == out["entity_id"], WGS.phase == "location_layout")
    assert store.blueprint_of(run(settings, lambda s: s.get(Entity, out["entity_id"]))) is None
```

  Проверка книги: `test_no_layout_without_flag_spatial_or_for_modules` дополнить вариантом из `tests/test_opening_scene.py::test_module_opening_npc_is_registered_in_entered_room` (кампания-приключение `publish_sample`, флаг включён, `spatial` у места модуля) — `develop` не возвращает `layout`. Используйте `publish_sample(settings)` и `party(..., module_id=..., module_hook="board")` как там.

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_develop.py -q` — FAIL.

- [ ] **Step 3: Разворот.** Создать `app/core/layout/plan.py`:

```python
"""Место каркаса становится комплексом (спецификация 2026-10-12, §3.1, §3.2, §9): при развороте наброска с
пространством резервируется структура с мандатом — замысел и сюжетные привязки на этот момент. Секрет места,
тайны NPC и тексты зацепок в мандат не идут. Готовое приключение и уже устроенное место не трогаются."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.layout import store
from app.core.layout.spatial import MAX_HOLDERS, Holder, Mandate, SpatialPlan
from app.db.models import Entity, WorldGenerationState


def eligible(world, root: Entity) -> bool:
    from app.core import adventure

    st = root.state or {}
    if root.kind != "location" or store.complex_of(root) is not None or st.get("blueprint") or st.get("sketch"):
        return False
    return adventure.module_place(root, world.catalog, world.entities) is None


async def mandate_for(session, campaign_id: str, plan: dict, sketch: dict, root: Entity) -> Mandate:
    from app.core import plot_anchors

    anchors = [Holder(key=b.anchor_id, name=plot_anchors.anchor_reserve(b)["name"][:80])
               for b in await plot_anchors.reserved_for(session, campaign_id, root.id)][:MAX_HOLDERS]  # fmt: skip
    room = MAX_HOLDERS - len(anchors)
    residents = [Holder(key=f"npc:{n['id']}", name=str(n.get("name") or n["id"])[:80])
                 for n in plan.get("npcs") or [] if n.get("location_id") == sketch["id"]][:room]  # fmt: skip
    return Mandate(place=root.name, mood=str(sketch.get("mood") or "")[:300],
                   spatial=SpatialPlan.model_validate(sketch["spatial"]), anchors=anchors,
                   residents=residents)  # fmt: skip


async def reserve_from_plan(ctx, root: Entity, sketch: dict[str, Any], inverse: list) -> WorldGenerationState | None:
    """Резерв структуры из наброска; None — у наброска нет пространства или место не подходит."""
    from app.core.world_generation import storage

    if not isinstance(sketch.get("spatial"), dict) or not eligible(ctx.world, root):
        return None
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    if row is not None:
        return row
    try:
        mandate = await mandate_for(ctx.session, ctx.campaign.id, ctx.world.plot, sketch, root)
    except ValidationError:
        return None  # каркас проверен архитектором; испорченный вручную набросок — место без комплекса
    row = await store.reserve_plan_layout(ctx.session, ctx.campaign, root, mandate)
    inverse.append({"table": "world_generation_states", "op": "delete", "id": row.id})
    return row
```

  В `app/tools/plot.py::develop` после `result = await _change(...)` и до `if arrived:`:

```python
    if kind == "location" and (ctx.campaign.settings or {}).get("location_layouts"):
        from app.core.layout import plan as layout_plan
        from app.core.preparation import receipt
        from app.core.world_generation import storage

        row = await layout_plan.reserve_from_plan(ctx, en, sketch, inverse)
        if row is not None:
            storage.activate(row)
            ctx.operation_refs.add(row.id)  # ход и вступление дождутся структуры до описания
            result["layout"] = receipt(row.id)
```

  `ctx.world.plot` после `_change` уже содержит `entity_id` наброска, `sync_bindings` создал привязки к корню — поэтому мандат берёт их здесь.

- [ ] **Step 4: Порядок фаз.** `app/core/world_generation/service.py::_dependencies` — обстановка корня ждёт структуру, обстановка участка — геометрию:

```python
async def _dependencies(maker, campaign_id: str, ref: str) -> list[str]:
    """Неготовые фазы, без которых эту не выполнить: обстановке корня нужна структура комплекса (иначе носители
    лягут у корня), обстановке участка — его геометрия."""
    async with maker() as s:
        row = await s.get(WorldGenerationState, ref)
        if row is None or row.campaign_id != campaign_id or row.phase != "location_initial":
            return []
        deps = []
        for phase in ("location_layout", "location_geometry"):
            dep = await storage.find(s, campaign_id, row.target_entity_id, phase)
            if dep is None or dep.status in ("ready", "blocked"):
                continue
            if await storage.activate_cas(s, dep):
                await s.commit()
            deps.append(dep.id)
        return deps
```

- [ ] **Step 5: Флаги.**
  - `app/config.py`: `CAMPAIGN_FLAGS = ("audio_enabled", "sfx_enabled", "scene_generation", "scene_generation_llm", "location_layouts", "location_layouts_llm")`.
  - `app/api/schemas.py` (`CampaignPatch`): `location_layouts: bool | None = None  # места каркаса с пространством становятся комплексами при развороте` и `location_layouts_llm: bool | None = None  # устройство места предлагает техническая модель`.
  - `app/api/campaigns.py`: добавить оба ключа в кортеж копируемых и в кортеж «None не сбрасывает».
  - `web/src/lib/campaign.ts`: `location_layouts?: boolean; location_layouts_llm?: boolean;`.
  - `web/src/cabinet/SettingsTab.tsx`: в секцию «Наполнение мест» после второй строки — две такие же строки `ActionButton`: «● устройство из каркаса / ○ места без устройства» (`location_layouts`; кнопки «Включить устройство мест» / «Выключить устройство мест»; done-тексты: «Новые места каркаса будут собираться из частей при развороте» / «Новые места останутся одним местом; готовые комплексы сохранятся») и «● устройство от модели / ○ устройство по шаблону» (`location_layouts_llm`; «Устройство от модели» / «Устройство по шаблону»; done: «Устройство места предложит модель; если ответ не подойдёт, сервер соберёт его сам» / «Устройство места собирает сервер без модели»). Пояснение раздела дополнить фразой: «Устройство места — из каких частей оно состоит; посещённые места не перестраиваются».
  - Регенерация: `uv run python -m app.contract` и в `web/` `npm run gen:api`.

- [ ] **Step 6: Проверить GREEN.** `uv run pytest tests/test_layout_develop.py tests/test_lead.py tests/test_opening_scene.py tests/test_world_generation.py tests/test_contract.py -q`; `cd web && npm test && npm run build`.

- [ ] **Step 7: Commit.**

```bash
git add app/core/layout/plan.py app/tools/plot.py app/core/world_generation/service.py app/config.py app/api/schemas.py app/api/campaigns.py web/src/lib/campaign.ts web/src/cabinet/SettingsTab.tsx web/openapi.json web/src/lib/api.gen.ts tests/test_layout_develop.py
git commit -m "Место каркаса с пространством становится комплексом при развороте"
```

---

### Task 8: Жители и носители в своих участках

**Files:**
- Modify: `app/core/layout/executor.py::_publish_layout`, `app/tools/plot.py::develop` (ветка NPC)
- Create: `tests/test_layout_residents.py`

**Interfaces:**
- Consumes: `store.home_of` (Task 3), `Blueprint.anchors` с ключами `npc:<id>` (Task 2), `request_preparation` (поставка 1).
- Produces: manifest структуры `"residents": [entity_id, ...]`; `develop` NPC без `here` ставит жителя в его участок.

- [ ] **Step 1: Написать failing tests** `tests/test_layout_residents.py`:

```python
# ruff: noqa: F811
"""Жители и носители каркаса в своих участках (спецификация 2026-10-12, §3.1, §10: NPC и носители по каркасу)."""

from app.core.layout import store
from app.db.models import Entity
from app.tools.master.places import request_preparation
from tests.game import run
from tests.test_layout_develop import _campaign, _develop
from tests.test_layout_preparation import _areas
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура


def test_resident_developed_before_structure_moves_in_on_publish(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    npc = _play(settings, cid, lambda ctx: _ok(ctx, "develop", {"sketch_id": "npc_warden", "details": "-",
                                                                 "here": False}))  # fmt: skip
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == place["entity_id"]
    ref = place["layout"]["operation_ref"]
    assert _prepare(settings, cid, ref) == "ready"
    areas = _areas(settings, place["entity_id"])
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == areas["road"].id
    assert _row(settings, ref).result_manifest["residents"] == [npc["entity_id"]]


def test_resident_developed_after_structure_goes_home(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    _prepare(settings, cid, place["layout"]["operation_ref"])
    npc = _play(settings, cid, lambda ctx: _ok(ctx, "develop", {"sketch_id": "npc_warden", "details": "-",
                                                                 "here": False}))  # fmt: skip
    root = run(settings, lambda s: s.get(Entity, place["entity_id"]))
    home = store.area_ids(root)[store.blueprint_of(root).anchors["npc:npc_warden"]]
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == home


def test_carrier_appears_in_its_area_not_at_root(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    _prepare(settings, cid, place["layout"]["operation_ref"])
    root = run(settings, lambda s: s.get(Entity, place["entity_id"]))
    chapel_ref = store.blueprint_of(root).anchors[next(k for k in store.blueprint_of(root).anchors
                                                       if not k.startswith("npc:"))]  # fmt: skip
    chapel_id = store.area_ids(root)[chapel_ref]

    async def enter(ctx):
        return await request_preparation(ctx, ctx.world.entities[chapel_id], [])

    out = _play(settings, cid, enter)
    assert _prepare(settings, cid, out["operation_ref"]) == "ready"
    journal = [e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Журнал смотрителя"]
    assert len(journal) == 1 and journal[0].location_id == chapel_id
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_residents.py -q` — FAIL: житель остаётся у корня.

- [ ] **Step 3: Реализовать.**
  - `_publish_layout` после создания участков (`ids` заполнен) и до записи `root.state`:

```python
    residents: list[str] = []
    for key, ref in bp.anchors.items():
        if not key.startswith("npc:"):
            continue
        for en in list(ctx.world.entities.values()):
            if en.kind == "creature" and en.location_id == root.id and (en.state or {}).get("plot_id") == key[4:]:
                en.location_id = ids[ref]  # житель каркаса переходит в свой участок вместе с публикацией
                residents.append(en.id)
```

    и в manifest: `"residents": residents`.
  - `app/tools/plot.py::develop`, ветка NPC: заменить `home = plot.sketch_entity(p, sketch.get("location_id"))` на

```python
        from app.core.layout import store as layout_store

        home = layout_store.home_of(ctx.world.entities, plot.sketch_entity(p, sketch.get("location_id")),
                                    f"npc:{sketch['id']}")  # fmt: skip
```

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_layout_residents.py tests/test_layout_develop.py tests/test_lead.py tests/test_plot_anchors.py -q` (если файла `test_plot_anchors.py` нет — `-k anchor`).

- [ ] **Step 5: Commit.**

```bash
git add app/core/layout/executor.py app/tools/plot.py tests/test_layout_residents.py
git commit -m "Жители и носители каркаса оказываются в своих участках комплекса"
```

---

### Task 9: Первая сцена внутри комплекса

**Files:**
- Create: `app/core/layout/entry.py`, `tests/test_opening_complex.py`
- Modify: `app/agents/prelude.py::_open_first_place` (вынести цикл NPC в `_opening_npcs`)

**Interfaces:**
- Consumes: `transit.begin/finish` (поставки 1–2), `store.blueprint_of/passage_live/area_ids`, `svc.preparer`, `svc._settle_preparation`, `observe_area` в `move_heroes` (поставка 2), `MapMemory`.
- Produces: `entry.entry_approach`, `entry.enter_complex` (см. «Контракты»).

- [ ] **Step 1: Написать failing tests** `tests/test_opening_complex.py`:

```python
# ruff: noqa: F811 — shared integration fixtures
"""Первая сцена внутри комплекса (спецификация 2026-10-12, §6, §8): вход фиксируется до вступления."""

from sqlalchemy import select

from app.agents import prelude
from app.core.layout import spatial, store
from app.db.models import Campaign, Character, Entity, Event, LlmCall, MapMemory, Scene, WorldGenerationState
from tests.game import party, run
from tests.layout_plan_pilot import temple_plan
from tests.test_lead import set_plan
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401

WGS = WorldGenerationState


def _start(game_client, admin_g, settings, **flags):
    c, _, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, c["id"])
    plan = temple_plan()
    plan["acts"][0]["nodes"][0]["npc_ids"] = ["npc_warden"]
    set_plan(settings, c["id"], plan)

    async def on(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {**campaign.settings, "location_layouts": True, **flags}
        await s.commit()

    run(settings, on)
    return c["id"], master, plan["locations"][0]


def _root(settings, cid):
    async def go(s):
        found = await s.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.kind == "location"))
        return next(e for e in found if (e.state or {}).get("blueprint") or (e.state or {}).get("plot_id"))

    return run(settings, go)


def test_opening_walks_into_entry_before_intro(game_client, admin_g, llm, settings):
    cid, master, where = _start(game_client, admin_g, settings)
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    root = _root(settings, cid)
    areas = store.area_ids(root)
    entry = areas[store.blueprint_of(root).entry]
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    heroes = rows(settings, Character, Character.campaign_id == cid)
    assert scene.location_id == entry and all(h.location_id == entry for h in heroes if h.status in ("approved",
                                                                                                    "active"))  # fmt: skip
    memories = rows(settings, MapMemory)
    assert memories and {m.entity_id for m in memories} == {entry}  # открыт только входной участок
    warden = next(e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Бертольд")
    assert warden.location_id == entry
    initial = rows(settings, WGS, WGS.phase == "location_initial")
    assert {r.target_entity_id for r in initial} <= {root.id, entry}  # соседей не наполняли


def test_second_opening_does_not_enter_again(game_client, admin_g, llm, settings):
    cid, master, where = _start(game_client, admin_g, settings)
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    before = (len(rows(settings, WGS)), len(rows(settings, Event, Event.tool == "traverse_passage")))
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    assert (len(rows(settings, WGS)), len(rows(settings, Event, Event.tool == "traverse_passage"))) == before
    assert not rows(settings, LlmCall, LlmCall.purpose == "location_layout")


def test_blocked_structure_keeps_heroes_outside(game_client, admin_g, llm, settings, monkeypatch):
    cid, master, where = _start(game_client, admin_g, settings)
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [])
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    root = _root(settings, cid)
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.location_id == root.id and store.blueprint_of(root) is None
    assert not rows(settings, Entity, Entity.location_id == root.id, Entity.kind == "location")
    assert not rows(settings, MapMemory)


def test_intro_text_is_written_after_entry(game_client, admin_g, llm, settings, monkeypatch):
    cid, master, _where = _start(game_client, admin_g, settings)
    seen = []

    async def write(svc, campaign, *_args, **_kwargs):
        async with svc.maker() as s:
            seen.append((await s.get(Scene, campaign.id)).location_id)
        return "Дорога у храма."

    monkeypatch.setattr(prelude, "_intro_text", write)
    game_client.portal.call(prelude.introduce_campaign, master, cid)
    root = _root(settings, cid)
    assert seen == [store.area_ids(root)[store.blueprint_of(root).entry]]
```

  Примечание: если `introduce_campaign` в тестовом окружении не доходит до `_intro_text` (нужна активная сессия и ИИ-мастер), взять подготовку из `tests/test_opening_scene.py::test_background_intro_shares_start_lock_and_reuses_prepared_text` и вызывать тот же путь, что там; суть проверки — состояние сцены в момент генерации текста.

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_opening_complex.py -q` — FAIL: отряд остаётся у корня.

- [ ] **Step 3: Вход в комплекс** `app/core/layout/entry.py`:

```python
"""Вход отряда в комплекс в первой сцене (спецификация 2026-10-12, §6, §8): после готовности структуры отряд
проходит первым открытым подходом во входной участок — тем же путём ``transit.begin``/``finish``, что и переход
мастера: подготовка участка, повторная проверка, перемещение и память вошедших. В игре вход выбирают сами герои."""

from __future__ import annotations

import logging
from typing import Any

from app.core.layout import store, transit
from app.core.layout.contracts import Blueprint
from app.db.models import Campaign, Entity
from app.tools.registry import ToolError

log = logging.getLogger(__name__)


def entry_approach(root: Entity, bp: Blueprint) -> str | None:
    """Открытый подход снаружи (из самого корня) ко входному участку; по ``passage_ref`` для повторяемости."""
    for p in sorted(bp.passages, key=lambda x: x.passage_ref):
        live = {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}
        if live["hidden"] or live["state"] != "open":
            continue
        ends = {e.area_ref for e in p.ends if not e.external}
        outside = [e for e in p.ends if e.external and (e.place_id or root.id) == root.id]
        if outside and ends == {bp.entry}:
            return p.passage_ref
    return None


async def enter_complex(maker, preparer, dice_factory, campaign_id: str, root_id: str, bus=None) -> dict[str, Any]:
    from app.core.world import PLAYABLE
    from app.tools.runtime import flush_outbox, open_context, publish_changes

    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        root = ctx.world.entities.get(root_id)
        bp = store.blueprint_of(root)
        if root is None or bp is None:
            return {"moved": False, "reason": "no_blueprint"}
        heroes = [h.id for h in ctx.world.characters.values()
                  if h.status in PLAYABLE and ctx.world.actor_place(h.id) == root_id]  # fmt: skip
        if not heroes:
            return {"moved": False, "reason": "no_heroes"}  # уже внутри или ушли: повтор ничего не делает
        ref = entry_approach(root, bp)
        if ref is None:
            return {"moved": False, "reason": "no_approach"}
        inverse: list = []
        try:
            req = await transit.begin(ctx, heroes, ref, inverse)
        except ToolError as e:
            await s.rollback()
            return {"moved": False, "reason": str(e)}
        await ctx.record("request_passage", target_id=req.dest_id, payload={"passage_ref": ref, "refs": list(req.refs)},
                         inverse=inverse, hidden=True)  # fmt: skip
        messages = await flush_outbox(s, ctx)
        await s.commit()
    if bus is not None:
        await publish_changes(bus, ctx, messages)
    if req.refs and preparer is not None:
        await preparer.settle(maker, campaign_id, list(req.refs))
    async with maker() as s:
        c = await s.get(Campaign, campaign_id)
        ctx = await open_context(s, c, dice_factory(), turn_id=None, seat_id=None)
        out = await transit.finish(ctx, req)
        messages = await flush_outbox(s, ctx)
        await s.commit()
    if bus is not None:
        await publish_changes(bus, ctx, messages)
    if not out.get("moved"):
        log.info("отряд не вошёл в комплекс %s: %s", root_id, out.get("reason"))
    return out
```

- [ ] **Step 4: Перестроить `_open_first_place`.** Вынести цикл NPC первого узла в `async def _opening_npcs(ctx, node, fresh_where, where) -> bool` без изменения логики (возвращает False при ошибке `develop`). Новый порядок:

```python
async with svc.maker() as s:
    ...  # как сейчас: свежий каркас, develop места (если не создано), ветка готового приключения
    from app.core.world_generation import storage

    layout = await storage.find(s, cid, place.id, "location_layout")
    deferred = layout is not None  # комплекс: участники узла встанут рядом с героями уже внутри
    if not deferred and not await _opening_npcs(ctx, node, fresh_where, where):
        await s.rollback()
        return False
    messages = await flush_outbox(s, ctx)
    await s.commit()
await publish_changes(svc.bus, ctx, messages)
if ctx.operation_refs:
    await svc._settle_preparation(cid, list(ctx.operation_refs))
if deferred:
    from app.core.layout import entry

    await entry.enter_complex(svc.maker, svc.preparer, svc.dice_factory, cid, place.id, bus=svc.bus)
    async with svc.maker() as s:
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, svc.dice_factory(), turn_id=None, seat_id=master_seat(c).id)
        node, fresh_where = _first_scene(ctx.world.plot)
        if not await _opening_npcs(ctx, node, fresh_where, where):
            await s.rollback()
            return False
        messages = await flush_outbox(s, ctx)
        await s.commit()
    await publish_changes(svc.bus, ctx, messages)
    if ctx.operation_refs:
        await svc._settle_preparation(cid, list(ctx.operation_refs))
return True
```

  `_opening_npcs` использует `ctx.world.scene.location_id` как `location_id` NPC — после входа это входной участок; при `blocked` — корень (герои снаружи, вступление описывает место без выдуманной комнаты). Повторный вызов: место уже есть (`created=False`), `enter_complex` возвращает `no_heroes`, участники узла уже в реестре и пропускаются существующей проверкой `npc.get("entity_id") in ctx.world.entities`.

- [ ] **Step 5: Проверить GREEN.** `uv run pytest tests/test_opening_complex.py tests/test_opening_scene.py tests/test_layout_transit.py tests/test_map_memory.py tests/test_location_map_privacy.py -q` — PASS (последние два — тесты поставки 2).

- [ ] **Step 6: Commit.**

```bash
git add app/core/layout/entry.py app/agents/prelude.py tests/test_opening_complex.py
git commit -m "Первая сцена начинается во входном участке подготовленного комплекса"
```

---

### Task 10: Ограниченная подготовка вперёд

**Files:**
- Create: `app/core/layout/ahead.py`, `tests/test_layout_ahead.py`
- Modify: `app/core/layout/transit.py::finish`, `app/gateway/ws.py::_traverse`

**Interfaces:**
- Consumes: `storage.find/activate`, `store.*` (поставка 1); `transit.finish` (поставки 1–2); `master.signal_recovery()`; проекция карты поставки 2 (для проверок).
- Produces: `ahead.AHEAD = 2`, `ahead.request_ahead(ctx, area) -> list[str]`.

- [ ] **Step 1: Написать failing tests** `tests/test_layout_ahead.py`:

```python
# ruff: noqa: F811
"""Подготовка вперёд (спецификация 2026-10-12, §8): геометрия до двух соседей, без модели и без раскрытия."""

import json

from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import MapMemory, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_layout_transit import _go
from tests.test_map import _map
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _with_maker  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _geo(settings, cid, area_id):
    return run(settings, lambda s: storage.find(s, cid, area_id, "location_geometry"))


def test_arrival_requests_geometry_of_at_most_two_neighbours(client, admin, settings):
    cid, heads, _hid, _village, _temple, ids = _built(client, admin, settings)
    assert _go(client, heads[0], cid, "in_road_w")["moved"]  # road: соседи brook и narthex
    requested = {k for k, v in ids.items() if _geo(settings, cid, v).requested_at is not None}
    assert requested <= {"road", "brook", "narthex"} and {"brook", "narthex"} <= requested
    assert _geo(settings, cid, ids["nave"]).requested_at is None
    assert not [r for r in rows(settings, WGS, WGS.phase == "location_initial")
                if r.target_entity_id in (ids["brook"], ids["narthex"])]  # fmt: skip


def test_secret_neighbour_is_never_prepared_ahead(client, admin, settings):
    cid, heads, hid, _village, _temple, ids = _built(client, admin, settings)
    _play(settings, cid, lambda ctx: _enter(ctx, hid, ids["nave"]))  # мастер ставит героя в неф
    out = _go(client, heads[0], cid, "p_sacristy")  # ризница: соседи — неф и тайник за тайной дверью
    assert out["moved"] and out["area_id"] == ids["sacristy"]
    assert _geo(settings, cid, ids["vault"]).requested_at is None


def test_prepared_neighbour_stays_unknown_to_players(client, admin, settings):
    cid, heads, _hid, _village, _temple, ids = _built(client, admin, settings)
    assert _go(client, heads[0], cid, "in_road_w")["moved"]
    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))
    assert _geo(settings, cid, ids["narthex"]).status == "ready"
    packet = json.dumps(_map(client, heads[0], cid), ensure_ascii=False)
    assert ids["narthex"] not in packet and "Притвор" not in packet
    assert {m.entity_id for m in rows(settings, MapMemory)} == {ids["road"]}
```

  Импорты для второго теста: `from tests.test_layout_passages import _enter` и `from tests.test_map import _play`. Дверь ризницы в пилоте открыта (`passage_state` по умолчанию), геометрия нефа не построена — `_approach` тогда не требует клетки у прохода (поставка 1).

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_layout_ahead.py -q` — FAIL: соседи не запрашиваются.

- [ ] **Step 3: Реализовать** `app/core/layout/ahead.py`:

```python
"""Ограниченная подготовка вперёд (спецификация 2026-10-12, §8): после входа в участок — геометрия его
непосредственных соседей, не больше ``AHEAD``. Только фаза ``location_geometry`` (код, без модели): наполнение,
знание героев и описание не трогаются, и готовая геометрия игроку ничего не открывает (поставка 2). Тайный
проход соседства не даёт. Исполняет восстановитель (``run_due``), ход и переход её не ждут."""

from __future__ import annotations

from app.core.layout import store
from app.db.models import Entity

AHEAD = 2


async def request_ahead(ctx, area: Entity) -> list[str]:
    from app.core.world_generation import storage

    cx = store.complex_of(area)
    root = ctx.world.entities.get(cx["root_id"]) if cx else None
    bp = store.blueprint_of(root)
    if bp is None:
        return []
    ids = store.area_ids(root)
    out: list[str] = []
    for p, end in sorted(bp.ends_of(cx["area_ref"]), key=lambda x: x[0].passage_ref):
        live = {"state": p.state, "hidden": p.hidden, **store.passage_live(root, p.passage_ref)}
        other = bp.other(p, end)
        if live["hidden"] or other.external:
            continue
        row = await storage.find(ctx.session, ctx.campaign.id, ids.get(other.area_ref) or "", "location_geometry")
        if row is None or not storage.activate(row):
            continue  # уже готово, готовится или заблокировано
        out.append(row.id)
        if len(out) >= AHEAD:
            break
    return out
```

  В `transit.finish` после `cell = _arrive(...)`: `await ahead.request_ahead(ctx, dest)` (импорт внутри функции; результат в ответ/событие **не** включать — id строк фаз игроку не нужны). В `app/gateway/ws.py::_traverse` в блоке `finally` после публикации: `if published: app.state.master.signal_recovery()  # подготовка вперёд не ждёт 15 с`. Ход мастера: восстановитель подхватит активированные строки в своём цикле (`run_due`).

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_layout_ahead.py tests/test_layout_transit.py tests/test_layout_turn.py tests/test_location_map_contract.py tests/test_location_map_privacy.py -q` — PASS (последние два — поставка 2).

- [ ] **Step 5: Commit.**

```bash
git add app/core/layout/ahead.py app/core/layout/transit.py app/gateway/ws.py tests/test_layout_ahead.py
git commit -m "Вход в участок готовит геометрию двух соседей, ничего не раскрывая"
```

---

### Task 11: Явная подготовка места ведущим

**Files:**
- Modify: `app/tools/master/generation.py` (`prepare_location`, `HOST_TOOLS`)
- Create: `tests/test_prepare_location.py`

**Interfaces:**
- Consumes: `layout_plan.reserve_from_plan/eligible` (Task 7), `storage.find/activate/reserve_root`, `store.*`, `plot._index`.
- Produces: инструмент `prepare_location(location_id: str, furnish: bool = False)` → `{location_id, structure, operation_refs, blueprint_ready, estimate: {structure_calls_max, furnish_calls_max}}`.

- [ ] **Step 1: Написать failing tests** `tests/test_prepare_location.py`:

```python
# ruff: noqa: F811
"""Явная подготовка места ведущим (спецификация 2026-10-12, §8): структура, геометрия и по желанию обстановка
всех участков без раскрытия и без перемещения героев."""

from app.db.models import Campaign, Entity, MapMemory, WorldGenerationState
from app.tools.registry import execute
from tests.game import run
from tests.test_layout_develop import _campaign, _develop
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _prep(settings, cid, location_id, **kw):
    return _play(settings, cid, lambda ctx: execute(ctx, "prepare_location", {"location_id": location_id, **kw}))


def test_two_calls_prepare_structure_then_all_geometry(client, admin, settings):
    cid = _campaign(client, admin, settings)  # флаг выключен: ведущий готовит явно
    place = _develop(settings, cid)
    first = _prep(settings, cid, place["entity_id"])
    assert first["ok"] and not first["result"]["blueprint_ready"]
    assert _prepare(settings, cid, first["result"]["structure"]["operation_ref"]) == "ready"
    second = _prep(settings, cid, place["entity_id"])["result"]
    geometry = rows(settings, WGS, WGS.phase == "location_geometry")
    assert len(geometry) == 6 and all(g.requested_at for g in geometry)
    assert second["operation_refs"][0] == first["result"]["structure"]["operation_ref"]
    assert set(second["operation_refs"][1:]) == {g.id for g in geometry}
    assert not rows(settings, WGS, WGS.phase == "location_initial") and not rows(settings, MapMemory)
    assert second["estimate"] == {"structure_calls_max": 0, "furnish_calls_max": 0}


def test_furnish_reserves_every_area_and_estimates_calls(client, admin, settings):
    cid = _campaign(client, admin, settings, scene_generation=True, scene_generation_llm=True,
                    location_layouts_llm=True)  # fmt: skip
    place = _develop(settings, cid)
    structure = _prep(settings, cid, place["entity_id"])["result"]
    assert structure["estimate"]["structure_calls_max"] == 2
    _prepare(settings, cid, structure["structure"]["operation_ref"])
    out = _prep(settings, cid, place["entity_id"], furnish=True)["result"]
    initial = rows(settings, WGS, WGS.phase == "location_initial")
    assert len(initial) == 6
    activated = [r for r in initial if r.requested_at is not None]  # профиль, не прошедший проверку, — blocked
    assert out["estimate"]["furnish_calls_max"] == 2 * len(activated)


def test_refuses_visited_books_and_places_without_space(client, admin, settings):
    cid = _campaign(client, admin, settings)
    visited = _develop(settings, cid, here=True)
    assert "посещ" in _prep(settings, cid, visited["entity_id"])["error"]
    tavern = _develop(settings, cid, sketch_id="loc_tavern")
    assert "пространств" in _prep(settings, cid, tavern["entity_id"])["error"]


def test_ai_master_does_not_see_it():
    from app.tools.master.generation import HOST_TOOLS

    assert {"prepare_location", "preparation_cost"} <= HOST_TOOLS
```

  `preparation_cost` в `HOST_TOOLS` добавляется в Task 12; до тех пор последняя проверка падает — держать её в Task 12 или добавить оба имени в `HOST_TOOLS` сразу (инструмент `preparation_cost` появится в Task 12). Выбрать второе: множество — константа, неизвестное имя в нём безвредно.

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_prepare_location.py -q` — FAIL: нет инструмента.

- [ ] **Step 3: Реализовать** в `app/tools/master/generation.py`:

```python
HOST_TOOLS = frozenset({"resolve_location", "retry_preparation", "bind_plot_anchor", "prepare_complex",
                        "prepare_location", "preparation_cost"})  # fmt: skip


class PrepareLocationArgs(BaseModel):
    location_id: str = Field(description="реальный id места каркаса с пространством")
    furnish: bool = Field(False, description="ещё и наполнить все участки обстановкой (вызовы модели — по бюджету)")


def _visited(ctx: ToolContext, place) -> bool:
    w = ctx.world
    here = {w.actor_place(h.id) for h in w.characters.values()} | {w.scene.location_id}
    return place.id in here or bool((place.state or {}).get("visited_by"))


@tool(
    "prepare_location",
    "Команда ведущего: заранее готовит место каркаса с пространством — структуру, затем геометрию всех участков и "
    "по желанию обстановку. Героям ничего не открывает и никого не перемещает. Первый вызов принимает структуру; "
    "после её готовности повторный вызов готовит участки. Возвращает квитанции и верхнюю оценку вызовов модели.",
    PrepareLocationArgs,
    ids={"location_id": "locations"},
    closes=False,
)
async def prepare_location(ctx: ToolContext, a: PrepareLocationArgs) -> dict:
    from app.core import plot as plot_mod
    from app.core.layout import plan as layout_plan
    from app.core.layout import store as layout_store
    from app.core.world_generation.service import LLM_LIMIT

    root = ctx.world.entities.get(a.location_id)
    if root is None or root.kind != "location" or root.campaign_id != ctx.campaign.id:
        raise ToolError("локация не принадлежит этой кампании")
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    inverse: list = []
    if row is None:
        if _visited(ctx, root):
            raise ToolError("отряд здесь уже был: устройство посещённого места не перестраивается")
        kind, sketch = plot_mod._index(ctx.world.plot or {}).get((root.state or {}).get("plot_id") or "", (None, None))
        if kind != "location" or not (sketch or {}).get("spatial"):
            raise ToolError("у места нет пространственного замысла в каркасе: используйте prepare_complex")
        row = await layout_plan.reserve_from_plan(ctx, root, sketch, inverse)
        if row is None:
            raise ToolError("это место не становится комплексом (готовое приключение или уже есть план)")
    storage.activate(row)
    refs = [row.id]
    settings = ctx.campaign.settings or {}
    furnish_calls = 0
    bp = layout_store.blueprint_of(root)
    if bp is not None:
        for area_id in layout_store.area_ids(root).values():
            area = ctx.world.entities[area_id]
            geo = await storage.find(ctx.session, ctx.campaign.id, area_id, "location_geometry")
            if geo is not None and storage.activate(geo):
                refs.append(geo.id)
            if a.furnish:
                initial = await storage.find(ctx.session, ctx.campaign.id, area_id, "location_initial")
                if initial is None:
                    initial = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, area,
                                                         minimal=not settings.get("scene_generation"))  # fmt: skip
                    inverse.append({"table": "world_generation_states", "op": "delete", "id": initial.id})
                if storage.activate(initial):
                    refs.append(initial.id)
                    if settings.get("scene_generation_llm"):
                        furnish_calls += max(0, LLM_LIMIT - int(initial.llm_attempt_count or 0))
    structure_calls = 0
    if row.status not in ("ready", "blocked") and settings.get("location_layouts_llm"):
        structure_calls = max(0, LLM_LIMIT - int(row.llm_attempt_count or 0))
    ctx.operation_refs.update(refs)
    result = {"location_id": root.id, "structure": receipt(row.id), "operation_refs": refs,
              "blueprint_ready": bp is not None,
              "estimate": {"structure_calls_max": structure_calls, "furnish_calls_max": furnish_calls}}  # fmt: skip
    await ctx.record("prepare_location", target_id=root.id, payload=result, inverse=inverse, hidden=True)
    return result
```

  Примечание: обстановка участка ждёт его геометрию через `_dependencies` (поставка 1), поэтому порядок соблюдается и при параллельной активации. Результат не содержит ключа `operation_ref` верхнего уровня — `execute` его не добавит; квитанции явно положены в `ctx.operation_refs`.

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_prepare_location.py tests/test_master_panel.py tests/test_layout_develop.py -q` — PASS.

- [ ] **Step 5: Commit.**

```bash
git add app/tools/master/generation.py tests/test_prepare_location.py
git commit -m "Ведущий заранее готовит место каркаса с оценкой вызовов модели"
```

---

### Task 12: Сводка расходов подготовки места

**Files:**
- Modify: `app/core/preparation.py` (`location_cost`), `app/tools/master/generation.py` (`preparation_cost`)
- Create: `tests/test_location_cost.py`

**Interfaces:**
- Consumes: `LlmCall.generation_id/tokens_reasoning` (Task 4); строки фаз корня, участков и контейнеров в них.
- Produces: `preparation.location_cost(...)`; инструмент `preparation_cost(location_id)` (`mutating=False`).

- [ ] **Step 1: Написать failing tests** `tests/test_location_cost.py`:

```python
# ruff: noqa: F811
"""Сводка расходов подготовки места (спецификация 2026-10-12, §8, §10): все фазы, исправления и рассуждения."""

from app.agents.llm import LLMReply, ScriptedLLM, ToolCall
from app.agents import layout_model
from app.core import preparation
from app.core.world_generation.service import Orchestrator
from app.gateway.coordination import InMemoryCoordination
from app.tools.registry import execute
from tests.game import run
from tests.layout_plan_pilot import model_layout
from tests.test_layout_model_phase import _bad, _flags, _on
from tests.test_layout_plan_phase import _plan_root
from tests.test_map import _play
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура

KEYS = ["clue_relic", "npc:npc_warden"]


def _priced(messages, tools):
    return LLMReply(text="", tool_calls=[ToolCall("c", layout_model.TOOL, model_layout(KEYS))], model="tech",
                    tokens_in=1200, tokens_out=800, reasoning_tokens=300, cost=0.004, latency_ms=50)  # fmt: skip


def test_cost_sums_structure_corrections_and_reasoning(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    assert (
        _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_bad, _priced]))) == "ready"
    )
    cost = run(settings, lambda s: preparation.location_cost(s, cid, root))
    layout = cost["phases"]["location_layout"]
    assert layout["calls"] == 2 and layout["errors"] == 1 and layout["tokens_reasoning"] == 300
    assert layout["tokens_in"] == 1210 and layout["ready"] == 1 and layout["duration_ms"] >= 0
    assert cost["phases"]["location_geometry"]["rows"] == 8 and cost["phases"]["location_geometry"]["calls"] == 0
    assert cost["total"]["calls"] == 2 and round(cost["total"]["cost"], 6) == 0.004


def test_reentry_adds_no_structure_calls(client, admin, settings):
    cid = _on(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_priced])))
    before = run(settings, lambda s: preparation.location_cost(s, cid, root))["phases"]["location_layout"]["calls"]
    _prepare(settings, cid, ref, Orchestrator(InMemoryCoordination(), llm=ScriptedLLM([_priced])))
    after = run(settings, lambda s: preparation.location_cost(s, cid, root))["phases"]["location_layout"]["calls"]
    assert before == after == 1


def test_host_tool_reads_without_writing(client, admin, settings):
    cid = _on(client, admin, settings)
    root, _ref = _plan_root(settings, cid)
    out = _play(settings, cid, lambda ctx: execute(ctx, "preparation_cost", {"location_id": root}))
    assert out["ok"] and out["result"]["root_id"] == root
```

  (`ScriptedLLM` для `_bad` отдаёт `tokens_in=10`: отсюда `1210`.)

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_location_cost.py -q` — FAIL.

- [ ] **Step 3: Реализовать** в `app/core/preparation.py`:

```python
def _bucket() -> dict[str, Any]:
    return {"rows": 0, "ready": 0, "pending": 0, "blocked": 0, "calls": 0, "errors": 0, "tokens_in": 0,
            "tokens_out": 0, "tokens_reasoning": 0, "cost": 0.0, "duration_ms": 0}  # fmt: skip


async def location_cost(session: AsyncSession, campaign_id: str, root_id: str) -> dict[str, Any]:
    """Расходы подготовки места по фазам (спецификация 2026-10-12, §8): структура, геометрия участков, обстановка
    и содержимое контейнеров в них; вызовы модели — по ``LlmCall.generation_id``, включая отклонённые ответы и
    токены рассуждений. Длительность фазы — от запроса до готовности. Только чтение."""
    from app.core.layout import store
    from app.db.models import LlmCall, as_utc

    root = await session.get(Entity, root_id)
    if root is None or root.campaign_id != campaign_id or root.kind != "location":
        raise NotFound("место не найдено")
    places = [root.id, *store.area_ids(root).values()]
    containers = list(await session.scalars(select(Entity.id).where(
        Entity.campaign_id == campaign_id, Entity.location_id.in_(places), Entity.kind == "object")))  # fmt: skip
    q = select(WorldGenerationState).where(WorldGenerationState.campaign_id == campaign_id,
                                           WorldGenerationState.target_entity_id.in_(places + containers))  # fmt: skip
    found = {r.id: r for r in await session.scalars(q)}
    phases: dict[str, dict[str, Any]] = {}
    for r in found.values():
        b = phases.setdefault(r.phase, _bucket())
        b["rows"] += 1
        status = public_status(r)
        b[{"ready": "ready", "blocked": "blocked"}.get(status, "pending")] += 1
        if r.requested_at is not None and r.completed_at is not None:
            b["duration_ms"] += max(0, int((as_utc(r.completed_at) - as_utc(r.requested_at)).total_seconds() * 1000))
    if found:
        for c in await session.scalars(select(LlmCall).where(LlmCall.generation_id.in_(list(found)))):
            b = phases[found[c.generation_id].phase]
            b["calls"] += 1
            b["errors"] += 1 if c.error else 0
            b["tokens_in"] += c.tokens_in or 0
            b["tokens_out"] += c.tokens_out or 0
            b["tokens_reasoning"] += c.tokens_reasoning or 0
            b["cost"] += c.cost or 0.0
    total = _bucket()
    for b in phases.values():
        for k in total:
            total[k] += b[k]
    return {"root_id": root.id, "phases": phases, "total": total}
```

  Инструмент в `app/tools/master/generation.py`:

```python
class PreparationCostArgs(BaseModel):
    location_id: str = Field(description="реальный id места (корня комплекса или обычного)")


@tool(
    "preparation_cost",
    "Только чтение: сколько стоила подготовка места — по фазам: вызовы модели, исправления, токены (и рассуждений), "
    "цена и длительность. Ничего не запускает и не меняет.",
    PreparationCostArgs,
    ids={"location_id": "locations"},
    mutating=False,
    closes=False,
)
async def preparation_cost(ctx: ToolContext, a: PreparationCostArgs) -> dict:
    from app.core import preparation
    from app.core.campaigns import NotFound

    try:
        return await preparation.location_cost(ctx.session, ctx.campaign.id, a.location_id)
    except NotFound as e:
        raise ToolError(str(e)) from e
```

- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_location_cost.py tests/test_prepare_location.py -q` — PASS.

- [ ] **Step 5: Commit.**

```bash
git add app/core/preparation.py app/tools/master/generation.py tests/test_location_cost.py
git commit -m "Ведущий видит расходы подготовки места по фазам"
```

---

### Task 13: Пилот, живой замер и итог поставки

**Files:**
- Create: `tests/test_location_maps_delivery3.py`, `tools/pilot_location_layout.py`, `docs/location-maps-delivery3.md`
- Modify: `docs/README.md` (ссылка на итог)

**Interfaces:**
- Consumes: все предыдущие задачи; `MapMemory` и проекция карты поставки 2 (проверки — через `rows(settings, MapMemory, ...)` и `_map`).
- Produces: итоговый документ: флаги, мандат, лимиты, учёт, решения, граница поставки, команды воспроизведения и живого замера.

- [ ] **Step 1: Написать failing acceptance tests** `tests/test_location_maps_delivery3.py`. Сценарий на `game_client` (как `tests/test_opening_complex.py`), каркас `temple_plan()`, флаги `location_layouts`, `location_layouts_llm`, `scene_generation`; у `Orchestrator` мастера — `ScriptedLLM` с ответом `model_layout(...)` (подменить `master.preparer.llm` тестовой моделью, где ответы структуры идут из своего списка):
  - `test_pilot_opening_generates_temple_and_field_once`: `_open_first_place` → отряд на дороге (`road`), blueprint из ответа модели (8 участков: `road, brook, narthex, nave, chapel, sacristy, vault, crypt`), рельеф дороги, ручья и моста у `road`/`brook` (`sketch.terrain`), `quality == "normal"`, ровно 1 `LlmCall(purpose="location_layout")` с `generation_id` строки структуры; у героев `MapMemory` только для `road`.
  - `test_pilot_round_trip_keeps_structure_and_costs_nothing_new`: игрок проходит `p_brook` (луг) и обратно, затем `p_narthex` после открытия дверей мастером; blueprint revision, id участков и объектов неизменны; новых `LlmCall(purpose="location_layout")` — 0; `preparation.location_cost` показывает фазы `location_layout`, `location_geometry`, `location_initial` с ненулевыми строками и `total.calls` = сумма по фазам.
  - `test_pilot_model_failure_falls_back_and_is_diagnosable`: модель отвечает дважды невалидно → `quality="fallback"`, заметка `fallback:invalid_proposal`, отряд всё равно во входном участке, `location_cost` считает 2 вызова с ошибками.
  - `test_pilot_secret_vault_is_not_disclosed_by_preparation`: после `prepare_location(furnish=True)` и `run_due` — ни у одного героя нет `MapMemory` для `vault`/`nave`; `_map` игрока не содержит их id и имён (`rows(settings, MapMemory, MapMemory.entity_id.in_(...))`).
  - `test_pilot_brief_has_no_plot_secrets`: запрос структуры, сохранённый `ScriptedLLM.requests[0]`, не содержит `secret` места, тайн и страхов NPC, текстов зацепок и имён антагонистов.

  В живом мандате ключ носителя — сгенерированный id зацепки, а не `clue_relic`. Ответ модели в пилоте строить из схемы запроса:

```python
def _layout_answer(messages, tools):
    keys = tools[0]["function"]["parameters"]["properties"]["parts"]["items"]["properties"]["anchors"]["items"]["enum"]
    return {"tool_calls": [(layout_model.TOOL, model_layout(keys))]}
```

- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_location_maps_delivery3.py -q`. Если тесты сразу проходят — проверить, что они идут через `_open_first_place`/`map.traverse`/исполнитель, а не подставляют blueprint напрямую, и что подсчёт вызовов не сравнивает результат функции с ней самой.

- [ ] **Step 3: Живой замер** `tools/pilot_location_layout.py` — без pytest, только по явному флагу:

```python
"""Живой замер структуры пилота (спецификация 2026-10-12, §8, §10): один вызов технической модели по мандату храма
и поля, без БД. Печатает токены (и рассуждений), цену, задержку, качество и устройство. Запуск только явно:

    TALEFORGE_LIVE_PILOT=1 uv run python tools/pilot_location_layout.py

Ключи провайдера — из обычного .env проекта. В CI и тестах не запускается."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> int:
    if os.environ.get("TALEFORGE_LIVE_PILOT") != "1":
        print("живой замер выключен: задайте TALEFORGE_LIVE_PILOT=1")
        return 2
    from app.agents import layout_model
    from app.agents.llm import LiteLLMClient, parser_model_for
    from app.core.layout.contracts import LayoutError
    from app.core.layout.provider import DeterministicLayoutProvider
    from tests.layout_plan_pilot import temple_mandate

    m = temple_mandate()
    provider = DeterministicLayoutProvider()
    msgs: list = []
    total = {"tokens_in": 0, "tokens_out": 0, "tokens_reasoning": 0, "cost": 0.0, "latency_ms": 0}
    for attempt_no in (1, 2):
        intent, attempt, retry = await layout_model.ask(
            LiteLLMClient(), m, model=parser_model_for(), api_base=None, msgs=msgs,
            check=lambda i: provider.propose(i, seed=12345, root_id="root"))  # fmt: skip
        for k in total:
            total[k] += getattr(attempt, k)
        print(f"попытка {attempt_no}: {attempt.model} in={attempt.tokens_in} out={attempt.tokens_out} "
              f"reasoning={attempt.tokens_reasoning} cost={attempt.cost:.5f} {attempt.latency_ms} мс "
              f"ошибка={attempt.error or '-'}")  # fmt: skip
        if intent is not None:
            bp = provider.propose(intent, seed=12345, root_id="root")
            print("принято:", ", ".join(f"{a.area_ref}({a.cols}×{a.rows}, ур.{a.level})" for a in bp.areas))
            break
        if retry is None:
            break
    else:
        print("модель не уложилась в две попытки: в игре будет детерминированный fallback")
    print("итого:", total)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
```

  Если `tests` не импортируется как пакет из `tools/`, перенести `temple_mandate` в `app/core/layout/pilot_data.py` не нужно — достаточно `sys.path` выше (корень проекта). Запуск по флагу записать в итог; результаты живого замера (если запускался) — таблицей в итоге с датой и моделью, без обещания цены «за комнату».

- [ ] **Step 4: Итог** `docs/location-maps-delivery3.md` (по образцу `docs/location-maps-delivery1.md`): что есть (пространство в каркасе, мандат, лестница замыслов, модель структуры, флаги, разворот, жители и носители, первая сцена, подготовка вперёд, `prepare_location`, `preparation_cost`, учёт `generation_id`/`tokens_reasoning`); решения поставки (из раздела «Решения и совместимость»); граница: дальние ориентиры и межкомплексные проходы — вне поставки, с причиной; команды воспроизведения тестов и живого замера; таблица результатов прогонов. В `docs/README.md` — строка-ссылка рядом с итогами поставок 1–2.

- [ ] **Step 5: Финальная проверка.**
  - `uv run python -m app.contract --check`
  - `uv run pytest -q -n auto -rs` — всё PASS; новые skips объяснены; сравнить с baseline.
  - Отдельная регрессия: `uv run pytest tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_adventure.py tests/test_modules.py tests/test_layout_pilot.py tests/test_layout_turn.py tests/test_opening_scene.py tests/test_scene_model.py -q`.
  - `uv run ruff check` и `uv run ruff format --check` только для изменённых Python-файлов.
  - В `web/`: `npm test`, `npm run build`.
  - `git diff --check`.
  - Пройти шесть пунктов Review Focus: у каждого есть зелёный тест (назвать его в итоге).
  - Независимое ревью всей ветки (свежий ревьюер) с акцентом: секреты в запросе модели, лимит вызовов при рестарте/повторе, порядок фаз корня, первая сцена при сбое, отсутствие раскрытия при подготовке, старые кампании и книга.

- [ ] **Step 6: Commit.**

```bash
git add tests/test_location_maps_delivery3.py tools/pilot_location_layout.py docs/location-maps-delivery3.md docs/README.md
git commit -m "Пилот подтверждает генерацию храма и поля из каркаса с учётом расходов"
```

  Merge/PR — только по отдельному решению пользователя; worktree не удалять без его согласия.

---

## Порядок и зависимости

`1 spatial → 2 mandate → 3 executor (детерминированно)` — независимы от поставки 2.
`2 → 5 модель структуры` — независима от поставки 2.
`(поставка 2 влита) → 4 учёт (миграция 0023) → 6 модель в фазе`.
`3 → 7 флаги и разворот → 8 жители и носители`.
`7 + 8 + (поставка 2) → 9 первая сцена`.
`(поставка 2) → 10 вперёд`.
`7 → 11 prepare_location`; `4 + 6 → 12 сводка расходов`.
`1–12 → 13 пилот и итог`.

Параллелить можно 1–3 и 5 до слияния поставки 2. При subagent-driven исполнении каждому исполнителю — спека, этот план целиком (секции Global Constraints, Решения, Контракты, Зависимости) и его задача; ревьюеру — то же плюс дифф.

## Проверка покрытия плана

- §3.1 каркас и пространственный замысел; ключевые факты как ограничения → Tasks 1, 2, 7, 8.
- §3.2 структура комплекса: модель предлагает, сервер назначает id и проверяет; лимиты 12/8/30 → Tasks 2, 3, 5, 6.
- §3.4 носители и обстановка после геометрии → Tasks 7 (порядок фаз), 8.
- §4 мандат в резерве, явная связь наброска и сущности (`plot_id`, `entity_id`) → Tasks 3, 7.
- §6 раскрытие только вошедшим; подготовка не раскрывает → Tasks 9, 10, 11, 13 (на контрактах поставки 2).
- §8 порядок первого входа; подготовка назначения до описания; один вызов + одна коррекция; бюджет 6000/3000; fallback; `blocked`; повторы не открывают лимит; геометрия без LLM; вперёд ≤2 без наполнения; явная большая подготовка; недоступная модель; ручная правка защищена; суммарная стоимость с исправлениями и рассуждениями → Tasks 3–7, 9–12.
- §9 книга не пересобирается; старые кампании без новых полей; посещённые места не генерируются заново; поставка 3 = архитектор, текстовый provider, первая сцена, вперёд, расходы → Tasks 1, 7, 11, 13.
- §10 приёмка: NPC и носители по каркасу; описание после фиксации; ошибка не оставляет полураскрытый участок; 0 вызовов структуры при повторном входе; пилот измеряет длительность, вызовы и токены всех фаз; сбой, устаревший результат, ручная правка, книга → Tasks 6, 8, 9, 12, 13.
- §5 дальние ориентиры — сознательно вне поставки (см. «Вне поставки»).

План прошёл inline self-review: имена контрактов (`Mandate`, `intent_candidates`, `obligations`, `reserve_plan_layout`, `home_of`, `reserve_from_plan`, `enter_complex`, `request_ahead`, `location_cost`) совпадают между задачами; лестница замыслов проверена прототипом на настоящем provider поставки 1 до записи плана. Перед кодом исполнитель сверяет план с фактическим main после поставки 2 (раздел «Перед исполнением», п. 2); этот документ не разрешает слияние и публикацию.
