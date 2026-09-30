# Пакет контента «Эхо Левиафанов» (база знаний для движка)

Стартовый набор данных мира и правил для приложения «AI-Мастер» (ТЗ: `design/tz-ai-master.md`, раздел 3.1 «Контент — пакеты YAML», раздел 4 «Модель данных»).
Источник смысла — файлы `design/setting/*.md`. Если данные и текст расходятся, прав текст канона; данные чинят.

Основа правил — **SRD 5.1 (CC BY 4.0)**. Всё из SRD подключается ссылкой `srd_ref`, а не копируется. Атрибуция: «This work includes material taken from the System Reference Document 5.1 by Wizards of the Coast LLC, licensed under CC BY 4.0».

## Структура

```
pack.yaml                 паспорт пакета: id, версия, ruleset, зависимости
data/
  stats.yaml              stat_definitions: характеристики, ресурсы, шкалы (Скверна, Перемена, эхо...)
  clocks.yaml             часы мира: резонанс, пробуждение туш, Цветение; пороги и переломы
  effects/*.yaml          effect_templates: состояния, уровни Скверны и Перемены, дары роя, черты выводков
  hazards.yaml            hazard_templates: налёт, Цветение, газ, споры...
  origins.yaml            происхождения героев (вместо рас)
  lineages.yaml           «Сохранивший себя», «Сохранивший сердце» (lineage_overlay)
  classes/*.yaml          классы: пересказ SRD-классов + свои (Диагност), подклассы
  echo.yaml               техники эха (Голод, Отклик)
  spells.yaml             как заклинания SRD подаются в мире, списки для своих классов
  items/*.yaml            item_templates: оружие, броня, снаряжение, расходники, импланты, артефакты
  treasure.yaml           таблицы добычи и индекс цен
  creatures/*.yaml        creature_templates: SRD-база + модификаторы мира
  encounters.yaml         encounter_tables
  factions.yaml           фракции
  locations/*.yaml        location_templates и опорные локации
  atlas/*.yaml            атлас мира: 6 ключевых городов, великие объекты, главы сил, их тайны, номенклатура
  plots.yaml              plot_structures: шаблоны сюжета мира для архитектора кампании
  lore.yaml               lore_facts: канон с уровнями знания
  secrets.yaml            campaign_secrets по умолчанию
schema/schema.yaml        JSON Schema для каждого вида записей
tools/validate.py         проверка: схема, уникальность id, ссылки
```

## Соглашения

- **Файл** — YAML-документ вида `{kind: <вид>, items: [ ... ]}`. Вид совпадает с таблицей ТЗ: `stat_definition`, `clock`, `effect_template`, `hazard_template`, `origin`, `lineage`, `class`, `subclass`, `echo_technique`, `spell_note`, `item_template`, `loot_table`, `price_index`, `creature_template`, `encounter_table`, `faction`, `location_template`, `lore_fact`, `campaign_secret`, `plot_structure`.
- **id** — латиница, `snake_case`, с префиксом вида через точку: `item.chitin_longsword`, `effect.corruption_3`, `creature.brood_swarm`. Уникален во всём пакете.
- **Общие поля** каждой записи:
  - `id`, `name` (по-русски), `description` (1–3 предложения, для мастера);
  - `status`: `canon` (решение Arty) или `proposal` (предложение, ждёт подтверждения);
  - `doc`: ссылка на раздел текста, например `rules.md#3.4` или `canon.md#1.6`;
  - `tags`: список;
  - `srd_ref` — если запись основана на SRD: `{type: monster|item|spell|class|condition, name: "<английское имя в SRD>"}`.
- **Карточка в конструкторе героя** (классы и происхождения): `epithet` — строка под именем, `badge` — метка в 1–3 слова, `summary` — одна-две фразы на карточке, `highlights` — главные особенности списком (видны при наведении или по кнопке «i»). У происхождений без `highlights` в подробностях показываются черты `features` с описаниями. Пакет мира переписывает тексты SRD, поэтому у одного класса в разных мирах своё описание.
- **Ссылки** на другие записи — строкой с id; поля ссылок оканчиваются на `_ref` или `_refs`. Валидатор проверяет, что цель существует (ссылки на SRD — через `srd_ref`, их не проверяем).
- **Числа — в данных, текст — для мастера.** Всё, что движок должен посчитать, записывается структурно (модификаторы, триггеры). То, что пока нельзя выразить, пишется в `modifiers` как `{op: custom, text: "..."}` — это сигнал разработчику, что нужна поддержка в движке.

## Язык модификаторов (`modifiers`)

| op | Поля | Смысл |
|---|---|---|
| `advantage` / `disadvantage` | `on`: `attack\|check\|save\|damage_roll`, `stat`?, `skill`?, `vs`? | Преимущество/помеха |
| `add` | `target`, `value` (число или формула `"1d4"`, `"pb"`, `"int_mod"`) | Прибавка к величине: `ac`, `speed`, `speed_climb`, `hp_max`, `attack`, `damage`, `save_dc`, `initiative`, `echo_pool`... |
| `multiply` | `target`, `factor` | Умножение (например, `hp_max` × 0.5) |
| `set` | `target`, `value` | Задать значение |
| `resistance` / `vulnerability` / `immunity` | `damage` или `condition` | Защиты |
| `sense` | `sense`: `darkvision\|blindsight\|tremorsense`, `range` | Чувства (в футах) |
| `extra_damage` | `dice`, `damage_type`, `when`? | Доп. урон |
| `condition` | `condition` | Наложить состояние SRD |
| `resource` | `stat`, `delta` | Изменить ресурс (например, `corruption` +1) |
| `save` | `stat`, `dc`, `on_fail`: [модификаторы], `on_success`? | Спасбросок с последствиями |
| `check` | `stat`, `add`?, `dc` (число, формула или `dc_ref`), `adv_if`?/`dis_if`?, `outcomes`: [{`result`: `success\|fail\|success_by_5\|fail_by_5`, `do`: [...]}] | Проверка или испытание с исходами (так записан Порог). `closed: true` — к броску применяются только модификаторы самой записи, внешние бонусы отсекаются |
| `run` | `ref` | Запустить другую запись (эффект, испытание, таблицу) |
| `proficiency` | `kind`: `skill\|tool\|weapon\|armor\|save\|language\|vehicle`, `value`, `expertise`? | Владение |
| `move` | `mode`: `teleport\|push\|pull\|climb\|squeeze`, `distance`, `requires`? | Перемещение |
| `remove_condition` | `condition` или `any_of`: [...], `count`? | Снять состояние |
| `choose` | `options`: [[модификаторы], ...], `when`: `short_rest\|long_rest\|use` | Выбор игрока из вариантов |
| `grant_action` | `name`, `action`: `action\|bonus\|reaction\|free`, `uses`: {`count`, `per`: `turn\|short_rest\|long_rest\|scene`}, `range`?, `area`?, `do`: [...] | Новое действие или способность |
| `natural_weapon` | `name`, `damage`: {`dice`, `type`}, `reach`?, `properties`? | Природное оружие |
| `clock` | `clock_ref`, `delta` | Сдвинуть часы мира |
| `spawn` | `creature_ref`, `count` | Создать существ (только сервер) |
| `behavior` | `profile`, `flee_threshold`? | Профиль поведения NPC |
| `custom` | `text`, `engine: dev_request` | **Не формализовано.** Такая механика в живую игру не попадает, только в тестовые кампании. Цель — ноль таких записей |

**Условия** (`if`): `{stat_gte: {corruption: 3}}`, `{has_effect: <id>}`, `{target_tag: brood}`, `{in_area: <hazard id>}`, `{wearing: heavy_armor}`, `{attunement_lte: -3}`, `{not: {...}}`, `{all: [...]}`, `{any: [...]}`.

**События триггеров** (`on`): `turn_start`, `turn_end`, `round_end`, `scene_end`, `short_rest`, `long_rest`, `day_end`, `hour_passed`, `hit`, `hit_by`, `miss`, `crit`, `deal_damage`, `take_damage`, `drop_to_0`, `reduce_target_to_0`, `ally_drop_to_0_nearby`, `spell_cast`, `echo_technique_used`, `feature_used`, `effect_end`, `enter_area`, `resource_changed`, `clock_threshold`, `key_deed`.

**Сложности** берутся только из базы знаний: шаблон объекта или локации, отношение NPC или шкала сложностей пакета (`data/dc_scale.yaml`, по умолчанию SRD 5–30). Мастер сложность не придумывает.

**Триггеры** (`triggers`): `[{on: turn_start|turn_end|long_rest|short_rest|hit|hit_by|drop_to_0|scene_end|enter_area, if?: {...}, do: [модификаторы]}]`.

Загружать YAML нужно с булевыми только `true/false` (как в YAML 1.2), иначе ключ `on` станет `True`. Пример загрузчика — `tools/validate.py`.

Длительность: `duration: {unit: round|minute|hour|day|until_rest|permanent, value: N}`; `stackable: true|false`.

## Как пользоваться

```
python3 tools/validate.py              # проверить весь пакет
python3 tools/validate.py --customs    # список неформализованных механик
python3 tools/validate.py --strict     # ошибка, если остались op: custom
python3 tools/import_srd_spells.py     # пересобрать заклинания SRD
python3 tools/vocab.py                 # пересобрать ENGINE_VOCAB.md
```

`ENGINE_VOCAB.md` — всё, что реально встречается в данных (op, события, условия, цели). Это список того, что должен уметь движок. `ISSUES.md` — открытые вопросы к автору и противоречия.
