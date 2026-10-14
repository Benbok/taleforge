# Отчёт об улучшении эталонных шаблонов локаций TaleForge

В данном отчёте зафиксированы результаты выполнения трёх задач ревью по доработке эталонных шаблонов коллекции локаций:
1. `tavern_roadside` (Придорожная таверна)
2. `port_quay_warehouse` (Портовая набережная, причал и склад)
3. `cave_passages_grotto` (Пещера: узкие переходы, грот и озеро)

---

## 1. Восстановление ссылок между участками в превью

### Причина проблемы
В первоначальной версии скрипта сборки `experiments/location-layout-templates/scripts/build_templates.py` при экспорте геометрии вызов `build_area(bp, area)` выполнялся без передачи словаря соответствий `ids` и корневого идентификатора `root_id`. В результате функция `build_area` не могла сопоставить ссылки `passage.target_area_ref` с итоговыми ID участков, и во всех внутренних переходах свойство `sketch.exits[].to` оставалось равным `None`.

### Реализованное решение
1. **Передача соответствий в `build_area`**:
   При формировании `render_payload.json` в `build_templates.py` подготовлен маппинг `ids = {a.area_ref: a.area_ref}` и `root_id = f"tpl_{tid}"`.
   Теперь:
   - Внешние выходы локации (ведущие наружу) имеют `to: root_id` (`tpl_tavern_roadside`, `tpl_port_quay_warehouse` и т.д.).
   - Внутренние выходы между участками имеют строгое соответствие `to: target_area_id`, совпадающее с полем `areas[].id` в `render_payload.json`.
2. **Семантика и фильтрация в виде игрока (`player_view.svg`)**:
   - В скрипте рендеринга `web/scripts/render-experiment-previews.tsx` входной участок помечается статусом `here`.
   - Смежные участки, соединённые с входным через открытые проходы (`!exit.hidden`), получают статус `remembered`.
   - **Исключение тайных зон**: проверка исключения тайных комнат выполняется строго по данным blueprint (`!dest.secret`), а не только по флагу выхода. Участки с `area.secret = True` (например, тайный погреб `secret_vault` в `tavern_urban_cellar`) никогда не попадают в начальный вид игрока.
   - **Явное предупреждение о статусе игрока**: в результирующий SVG внедрён метатег `<desc>`:
     > *«Пример состояния игрока (player_view): отряд на входном участке, смежные открытые участки запомнены. Соседство на карте само по себе не означает, что участок уже посещён.»*

---

## 2. Разделение сравнений «до / после»

Чтобы исключить смешение изменений планировки и изменений графического рендерера, сравнения разделены на два независимых набора артефактов:

### А. Сравнение данных планировки на одном рендерере (`layout_comparison/`)
Демонстрирует эволюцию геометрии и расстановки объектов. Оба состояния (исходное и доработанное) визуализируются одним и тем же актуальным рендерером с одинаковым масштабом клетки (1 unit / 24px) и viewBox:
- `before_layout_overview.svg` vs `after_layout_overview.svg` (общий план локации);
- `before_layout_key.svg` vs `after_layout_key.svg` (фокусный ключевой участок);
- `before_layout_player.svg` vs `after_layout_player.svg` (вид от лица игрока).

### Б. Сравнение старой и новой отрисовки на одинаковых данных (`renderer_comparison/`)
Демонстрирует влияние изменений стилей, материалов и контуров рендерера на идентичных исходных данных `before/render_payload.json`:
- `old_renderer_overview.svg` — оригинальный SVG общего плана, созданный старым рендерером до правок (скопирован из сохранённого архива `before/overview_level_0.svg`, без повторной перезаписи);
- `new_renderer_overview.svg` — тот же самый исходный payload, отрисованный новым рендерером с волновой текстурой воды, контрастным контуром препятствий и палитрой материалов;
- `old_renderer_key_area.svg` — оригинальный SVG ключевого участка старого рендерера (скопирован из `before/area_*.svg`);
- `new_renderer_key_area.svg` — ключевой участок исходных данных в новой отрисовке.

---

## 3. Сохранение визуальной категории и семантики твёрдых деталей (`solid=True`)

### Архитектурная проблема
Ранее при компиляции шаблона флаг `solid=True` в `DetailIntent` приводил к тому, что занимаемые объектом клетки помещались только в массив непроходимых клеток `sketch.walls`. При этом объект исключался из `sketch.features`, теряя имя, категорию (`kind`), глиф и метаданные. Барная стойка, обеденный стол или очаг визуально превращались в безликие чёрные блоки каменной стены.

### Минимальное решение по передаче данных
1. **Сохранение в `sketch.features`**:
   В `build_templates.py` все детали шаблона (как лёгкие, так и твёрдые) теперь экспортируются в `sketch.features` с сохранением имени, семантической категории (`furniture`, `light`, `object`, `cover`), координат занимаемых клеток и явного флага `"solid": True`.
2. **Исключение из `sketch.walls`**:
   Клетки твёрдых деталей сохраняются в `sketch.walls`: это механическая геометрия для движения и прямой видимости. Renderer пропускает заливку стен только на клетках видимых твёрдых features, сохраняя визуальную категорию без двойной заливки.
3. **Механическая проходимость в ядре TaleForge**:
   Анализ серверной механики подтвердил, что проходимость полностью сохраняется:
   - В `app/core/positions.py` функция `cell_problem` проверяет занятость клетки:
     `if any(cell in f["cells"] for f in sk.get("features", [])): return f"на клетке стоит «{f['name']}»"`
   - В `app/core/reach.py` функция `blocked_cells` объединяет стены и декорации:
     `out = _walls(sk); for f in sk.get("features", []): out |= footprint(f)`
   Эти проверки движения не заменяют `sketch.solid_cells()`, который читает стены и маску пола. Поэтому твёрдые объекты остаются одновременно в walls и features. Обычный `geometry.build_area()` теперь сохраняет визуальные сведения; экспериментальный экспорт использует его результат без собственной подмены геометрии.

### Реализация в рендерере (`web/src/game/SketchSurface.tsx` и `map.ts`)
1. Интерфейс `SketchFeature` дополнен опциональным свойством `solid?: boolean`.
2. В `SketchSurface.tsx` для твердых деталей добавлен селектор `data-feature-solid="true"`.
3. Подложка твёрдой детали отображается с увеличенным заполнением клетки (`0.9 x 0.9` против `0.8 x 0.8`), повышенной плотностью (`opacity=".42"` против `.18`) и контрастной обводкой `stroke={visual.color} strokeWidth=".04"`.
4. **Различие со стеной**:
   - Каменная стена `sketch.walls` рисуется монолитным тёмным токеном `var(--tf-map-wall)` с нейтральной фаской `var(--tf-map-wall-stroke)`.
   - Твёрдая деталь рисуется цветом своей семантической категории (золотой дуб для `furniture`, оранжевый уголь для `light`, бронзовая патина для `object`, защитный камень для `cover`), с иконкой по центру и всплывающей подсказкой `<title>{feature.name}</title>`.
5. **Отсутствие хаков**:
   Стиль определяется исключительно полями `feature.kind` и `feature.solid`. Никаких проверок по подстрокам («стол», «стойка») или template ID в коде нет.
6. **Отсутствие скрытых боевых бонусов**:
   Наличие `solid=True` или `kind="cover"` не начисляет автоматически бонусы к классу защиты (+2 КЗ за полуукрытие) и не создает боевых эффектов — правила укрытий определяются логикой конкретного энкаунтера.

### Возможное расширение классификации (RFC)
Существующего набора категорий (`furniture`, `light`, `object`, `cover`, `nature`) достаточно для базового различения мебели, света и контейнеров. Если для ИИ-мастера потребуется различать сиденья, столы и стойки на уровне системы подсказок, рекомендуется добавить опциональное поле `subkind`:
```json
{
  "kind": "furniture",
  "subkind": "counter",
  "name": "Барная стойка",
  "solid": true,
  "cells": [[1, 1, 1, 2]]
}
```

---

## 4. Сводные визуальные сравнения эталонов

### 1. Придорожная таверна (`tavern_roadside`)

#### Сравнение планировки (один рендерер, разные данные)
| План | Исходная планировка (`before`) | Доработанная планировка (`after`) |
|---|---|---|
| **Общий вид** | [before_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/before_layout_overview.svg) | [after_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/after_layout_overview.svg) |
| **Общий зал** | [before_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/before_layout_key.svg) | [after_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/after_layout_key.svg) |
| **Вид игрока** | [before_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/before_layout_player.svg) | [after_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/layout_comparison/after_layout_player.svg) |

#### Сравнение рендерера (одинаковые исходные данные)
| План | Старый рендерер | Новый рендерер |
|---|---|---|
| **Общий вид** | [old_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/renderer_comparison/old_renderer_overview.svg) | [new_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/renderer_comparison/new_renderer_overview.svg) |
| **Общий зал** | [old_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/renderer_comparison/old_renderer_key_area.svg) | [new_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/tavern_roadside/renderer_comparison/new_renderer_key_area.svg) |

---

### 2. Портовая набережная и склад (`port_quay_warehouse`)

#### Сравнение планировки (один рендерер, разные данные)
| План | Исходная планировка (`before`) | Доработанная планировка (`after`) |
|---|---|---|
| **Общий вид** | [before_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/before_layout_overview.svg) | [after_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/after_layout_overview.svg) |
| **Грузовой пирс** | [before_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/before_layout_key.svg) | [after_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/after_layout_key.svg) |
| **Вид игрока** | [before_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/before_layout_player.svg) | [after_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/layout_comparison/after_layout_player.svg) |

#### Сравнение рендерера (одинаковые исходные данные)
| План | Старый рендерер | Новый рендерер |
|---|---|---|
| **Общий вид** | [old_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/renderer_comparison/old_renderer_overview.svg) | [new_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/renderer_comparison/new_renderer_overview.svg) |
| **Грузовой пирс** | [old_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/renderer_comparison/old_renderer_key_area.svg) | [new_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/port_quay_warehouse/renderer_comparison/new_renderer_key_area.svg) |

---

### 3. Пещера с гротом и озером (`cave_passages_grotto`)

#### Сравнение планировки (один рендерер, разные данные)
| План | Исходная планировка (`before`) | Доработанная планировка (`after`) |
|---|---|---|
| **Общий вид** | [before_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/before_layout_overview.svg) | [after_layout_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/after_layout_overview.svg) |
| **Большой грот** | [before_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/before_layout_key.svg) | [after_layout_key.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/after_layout_key.svg) |
| **Вид игрока** | [before_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/before_layout_player.svg) | [after_layout_player.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/layout_comparison/after_layout_player.svg) |

#### Сравнение рендерера (одинаковые исходные данные)
| План | Старый рендерер | Новый рендерер |
|---|---|---|
| **Общий вид** | [old_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/renderer_comparison/old_renderer_overview.svg) | [new_renderer_overview.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/renderer_comparison/new_renderer_overview.svg) |
| **Большой грот** | [old_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/renderer_comparison/old_renderer_key_area.svg) | [new_renderer_key_area.svg](file:///d:/Workspace/Projects/taleforge/experiments/location-layout-templates/comparisons/cave_passages_grotto/renderer_comparison/new_renderer_key_area.svg) |

---

## 5. Результаты проверок

1. **Мульти-сидовая сборка**:
   Все 12 шаблонов коллекции успешно скомпилированы и валидированы на наборе сидов `[1, 7, 42, 99, 123]` без ошибок геометрии, разрывов связности или перекрытия проходов.
2. **Backend-тесты качества раскладки и геометрии**:
   `uv run pytest tests/test_layout_quality.py tests/test_layout_geometry.py` — **116 пройденных тестов из 116**.
3. **Frontend-типизация**:
   `npm run typecheck` — **0 ошибок типизации TypeScript**.
4. **Frontend-тесты**:
   `npm test` — **225 пройденных тестов из 225**.
