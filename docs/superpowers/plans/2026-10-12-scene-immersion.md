# Scene Immersion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить атмосферную шапку локации, локальное освещение игрового экрана и читаемую хронику с устойчивыми разделителями мест.

**Architecture:** Сервер выдаёт отдельную публичную проекцию оформления текущего места, а клиент отображает локальные готовые иллюстрации/SVG и декоративный свет внутри GamePage. Контекст места сохраняется вместе с новыми сообщениями и проходит через стриминг и replay; разделители хроники вычисляются из этих снимков. Карты не являются источником данных или зависимостью.

**Tech Stack:** Python 3.11+, Pydantic 2, FastAPI, SQLAlchemy; React 19, TypeScript, Zustand, Tailwind 4, Vite, Vitest и Testing Library; локальные SVG.

**Spec:** [2026-10-12-scene-immersion-design.md](../specs/2026-10-12-scene-immersion-design.md).

## Global Constraints

- Карты исключены из проекта по прямому указанию пользователя.
- Не менять `docs/superpowers/plans/2026-10-12-location-maps-delivery1.md`, спецификацию генеративных карт, компоненты карты, её API, геометрию, раскрытие, построители и подготовку локаций.
- Готовые иллюстрации и SVG-композиции; генерация растровых изображений и новые платные сервисы не нужны.
- Новые данные не берутся из `CampaignSecret`, скрытого каркаса, соседних мест, карты, музыки или системных часов компьютера.
- Погода и период суток показываются только при явном публичном указании мастера.
- Канонической границей доступа остаётся `visible_to`; `scope` задаёт только внешний вид.
- Старым сообщениям без контекста не приписывать текущую локацию.
- Переход параметров длится 400 ms; при `prefers-reduced-motion: reduce` — без перехода.
- Максимальная непрозрачность света: 0.14 для тёмной темы, 0.06 для светлой.
- Шрифт повествования: 18 px desktop / 17 px phone, интервал 1.65, ширина до 65ch.
- Добавления схемы WebSocket совместимы со старыми payload: новые поля необязательны.
- Хранение использует существующие JSON `Entity.state` и `Message.data`; миграция БД не нужна.
- Не менять зависимости, игровой движок, микшер и тему пакета на `:root`.
- Сохранить незакоммиченные изменения пользователя. На момент подготовки были изменения в `app/core/narrative/contracts.py`, `app/core/narrative/ports.py`, `tests/narrative_helpers.py` и отдельные документы карт. При исполнении заново проверить `git status`.

## Review Focus

1. Разделённый отряд: оформление и контекст берутся из места героя; скрытые данные другой группы не попадают в snapshot или replay. Проверки: Tasks 1 и 4.
2. Поток, повтор описания и поздняя озвучка: один контекст и разделитель; прежние голоса/пометки не теряются при merge. Проверки: Tasks 4 и 5.
3. Старые сообщения и совпадающие названия разных мест: никаких угаданных локаций; A → B → A и фильтры сохраняют границы. Проверки: Task 5.
4. Ошибка картинки, отсутствующий preset и старый сервер: читаемая нейтральная/SVG шапка без внешних запросов. Проверки: Tasks 1 и 2.
5. Узкий телефон, светлая тема и reduced motion: видны ввод и обязательные действия, эффекты не ухудшают чтение и не выходят за GamePage. Проверки: Tasks 3 и 6.

## Поставки и ответственность файлов

| Поставка | Задачи | Результат |
|---|---|---|
| A | 1–2 | Шапка с реальным именем места, явной погодой/периодом и локальным рисунком |
| B | 3 | Свет по preset внутри игры, обе темы и отсутствие движения по настройке системы |
| C | 4–6 | Контекст истории, хроника, полная визуальная приёмка |

| Файл | Ответственность |
|---|---|
| `app/core/scene_presentation.py` (новый) | Схема публичного оформления и чистая запасная проекция |
| `app/tools/master/presentation.py` (новый) | Единственная запись оформления через журналируемый инструмент |
| `app/core/chronicle.py` (новый) | Снимок места сообщения и классификация scope |
| `web/src/game/scenePresentation.ts` (новый) | Каталог иллюстраций, подписи, локальные параметры света |
| `web/src/game/SceneArtwork.tsx` (новый) | Декоративный рисунок с SVG fallback |
| `web/src/game/LocationHeader.tsx` (новый) | Адаптивная шапка и сворачивание |
| `web/src/game/scenePreferences.ts` (новый) | Только настройка свёрнутой шапки, безопасное localStorage |
| `web/src/game/chronicle.ts` (новый) | Чистая группировка видимых сообщений до фильтров |
| `web/src/game/ChronicleDivider.tsx` (новый) | Заголовок раздела истории |
| `web/src/game/scene-immersion.css` (новый) | Локальные стили шапки, света и типографики |

Из существующих файлов менять только обозначенные ниже точки интеграции.
`app/gateway/protocol.py` и генерируемые типы — общие файлы с разработкой карт:
добавлять только поля оформления/сообщений, не заменять чужие модели и не
пересобирать старый контракт поверх более новых изменений. После обновления
контракта diff должен содержать только новые поля этого проекта плюс уже
существующие изменения другого проекта; их не включать в свои коммиты.

---

### Task 1: Публичная проекция оформления и инструмент мастера

**Files:**
- Create: `app/core/scene_presentation.py`, `app/tools/master/presentation.py`.
- Modify: `app/tools/master/__init__.py`, `app/tools/runtime.py` (`scene_payload`).
- Modify: `app/gateway/protocol.py` (`Scene`), `web/src/lib/types.ts` (`Scene`).
- Generate: `web/openapi.json`, `web/src/lib/api.gen.ts`.
- Test: `tests/test_scene_presentation.py` (новый), `tests/test_scene_presentation_tools.py` (новый).

**Interfaces:**
- Produces: `LocationPresentation(BaseModel)` с полями и enum из spec §3; `extra="forbid"`.
- Produces: `scene_presentation(location: Entity | None) -> LocationPresentation | None` — чистая функция; при None возвращает None.
- Produces: `Scene.presentation: LocationPresentation | None = None`, TS — `presentation?: LocationPresentation | null` и реэкспорт сгенерированного типа.
- Produces: `set_location_presentation(ctx: ToolContext, a: SetLocationPresentationArgs) -> dict`; плоские args: `location_id: str`, остальные поля как в `LocationPresentation`.
- Consumes: уже выбранный `view.current_location_id` в `scene_payload`; не меняет `visible_scene`.

- [ ] **Step 1: Добавить проверки проекции.** В `tests/test_scene_presentation.py` создать местную фабрику Entity с уникальным ID, kind=location, name и state. Проверить `test_absent_location`, `test_defaults_do_not_invent_weather`, `test_public_name_word_matching`, `test_explicit_presentation`, `test_invalid_legacy_presentation_falls_back`, `test_personal_projection_and_snapshot_agree`.

  Ключевые утверждения:
  ```python
  assert scene_presentation(None) is None
  assert scene_presentation(tavern).preset == "tavern"
  assert scene_presentation(tavern).period is None
  assert scene_presentation(tavern).weather is None
  assert scene_presentation(innocent_name).preset == "neutral"  # "innocent" не "inn"
  assert scene_presentation(secret_tag_only).preset == "neutral"
  assert payload_a["presentation"]["preset"] == "coast"
  assert payload_b["presentation"]["preset"] == "crypt"
  assert snapshot_a["payload"]["scene"] == update_a
  ```
  Для персональных payload использовать настоящие `scene_payload`/`visible_scene`; для snapshot — `tests.test_ws.connect`. В состояние поместить маркер секрета и подтвердить его отсутствие в сериализации. Не создавать зависимость от карты.

- [ ] **Step 2: Запустить тесты до реализации.** Из корня: `python -m pytest tests/test_scene_presentation.py -q`. Ожидается отсутствие нового модуля/поля, а не ошибка существующей фикстуры.

- [ ] **Step 3: Реализовать схему и проекцию.** Валидировать explicit presentation целиком; невалидное старое JSON-состояние заменять запасным preset из публичного имени. Не копировать state или description в payload. Словарь слов и приоритеты строго как в spec §3. В `scene_payload` добавить `presentation` рядом с `location`; snapshot и updates используют эту точку автоматически.

- [ ] **Step 4: Добавить тесты записи инструмента.** В новом файле импортировать `game`/`play`/`call` из `tests.test_tools`. Имена: `test_presentation_preserves_other_state_and_has_inverse`, `test_presentation_rejects_non_location`, `test_presentation_retry_is_idempotent`, `test_invalid_enums_and_image_paths_are_rejected`. Проверить сохранение `links`, `visited_by`, `secret`; поле inverse — прежнее state; повтор по одному key даёт один Event. `illustration_key="../../x"` и URL отклоняются; null очищает необязательное поле. Запустить файл и увидеть отсутствие зарегистрированного инструмента.

- [ ] **Step 5: Реализовать отдельный инструмент.** В существующий импорт регистрации добавить новый модуль. Проверить location_id через World и kind=location. Полностью заменить `state.presentation` через копию JSON, зафиксировать Event с обратной дельтой. Применять стандартную идемпотентность реестра. Инструкция инструмента: только публичное видимое оформление; это не создание погоды, смена игрового времени или механики света. Новая форма автоматически доступна существующему MasterPanel.

- [ ] **Step 6: Обновить контракт и проверить поставку данных.** Из корня `python -m app.contract`; из `web` — `npm run gen:api`. Затем `python -m pytest tests/test_scene_presentation.py tests/test_scene_presentation_tools.py tests/test_contract.py -q`; в `web` — `npm run typecheck`. Ожидается PASS. Сверить, что модели и события карт не изменены этой задачей.

- [ ] **Step 7: Сделать отдельный commit только Task 1.** `feat: expose public scene presentation`. Общие файлы с чужими изменениями добавлять по своим фрагментам, не целиком.

### Task 2: Готовые композиции и адаптивная шапка

**Files:**
- Create: `web/src/game/scenePresentation.ts`, `SceneArtwork.tsx`, `LocationHeader.tsx`, `scenePreferences.ts`, `scene-immersion.css`.
- Create: `web/public/assets/scenes/{neutral,tavern,coast,forest,ruins,crypt,sanctuary}.svg`, `web/public/assets/scenes/README.md`.
- Modify: `web/src/pages/GamePage.tsx`, `web/src/index.css` (только импорт CSS).
- Test: `web/src/game/LocationHeader.test.tsx`, `web/src/game/scenePreferences.test.ts` (новые).

**Interfaces:**
- Consumes: Task 1 `Scene.presentation` и `Scene.location`; `useInspector.open`.
- Produces: `SceneArt { src: string; focus: string }`, `SCENE_ART: Record<string, SceneArt>` с ключами `neutral`, `tavern`, `coast`, `forest`, `ruins`, `crypt`, `sanctuary`.
- Produces: `resolveSceneArt(presentation: LocationPresentation | null | undefined): SceneArt` — неизвестный illustration_key заменяет preset, неизвестный preset заменяет neutral.
- Produces: `presentationSubtitle(presentation: LocationPresentation | null | undefined): string` — русские подписи period/weather, без технического имени preset.
- Produces: `LocationHeader({scene}: {scene: Scene | null})`, `SceneArtwork({presentation}: {presentation: LocationPresentation | null | undefined})`.
- Produces: `useScenePreferences` с `headerCollapsed: boolean`, `setHeaderCollapsed(value: boolean): void`; storage key `tf_scene_header_collapsed`, умолчание false.

- [ ] **Step 1: Добавить функциональные тесты.** Проверить `test/header with known facts`, `unknown location`, `unknown art key`, `failed image`, `long name`, `collapse and restore`. Render LocationHeader с таверной, period=dusk, weather=fog: имя видно, строка «Сумерки · Туман» видна, клик вызывает inspector для этого ID. При null location нет кнопки карточки и есть «Место ещё не названо». fireEvent.error у img показывает SVG fallback. Свернуть → aria-expanded=false → повторно развернуть; полный длинный текст остаётся в accessible name. Для preferences проверить недоступное localStorage и испорченное значение: default false, действие работает без исключения.

- [ ] **Step 2: Запустить эти тесты до реализации.** Из `web`: `npm test -- src/game/LocationHeader.test.tsx src/game/scenePreferences.test.ts`. Ожидается FAIL из-за отсутствия новых компонентов.

- [ ] **Step 3: Подготовить локальные рисунки и каталог.** Семь SVG-композиций по spec §4, не более 30 KiB каждая; только художественные силуэты без игровых объектов и внешних ссылок. README фиксирует происхождение этих авторских SVG. Каталог src — только локальные `/assets/scenes/...`; focus — CSS object-position. Готовый растр в будущем добавляется отдельным ключом каталога с указанием происхождения; Task 2 не ждёт такого файла и не использует внешние изображения.

- [ ] **Step 4: Реализовать Artwork/Header/preferences и CSS.** Fallback встроенный SVG по тому же preset, без повторного broken img. Изображения декоративны. Название/подписи на непрозрачной поверхности темы. Высоты 132/72 px при free и 72/48 px при combat (desktop/phone); collapsed 48 px. Breakpoint 768 px. Состояние кнопки сворачивания доступно через aria-expanded; общий h-dvh/min-h-0 остаётся у GamePage. Header ставится перед CombatStrip и вне скролла ChatFeed; ScenePanel продолжает показывать объекты и действовать как раньше.

- [ ] **Step 5: Проверить поставку A.** Запустить targeted тесты и `npm run build`. В браузере проверить 390×844 и 1440×900, длинное имя, неизвестное место, карточку по клику, шапку во время боя и ошибки SVG. Ввод и реакции должны оставаться доступны. CSS и jsdom-тесты не считать доказательством правильного размера: сохранить снимки в `docs/scene-immersion/` на финальной приёмке.

- [ ] **Step 6: Commit Task 2.** `feat: add atmospheric location header`.

### Task 3: Локальный свет без изменения темы мира

**Files:**
- Modify: `web/src/game/scenePresentation.ts`, `web/src/game/scene-immersion.css`, `web/src/pages/GamePage.tsx`.
- Test: `web/src/game/scenePresentation.test.ts`, `web/src/pages/GameAtmosphere.test.tsx` (новые).

**Interfaces:**
- Consumes: Task 1 presentation, персональный Scene.mode; `useSession.mode` (`dark | light`).
- Produces: `sceneLighting(presentation: LocationPresentation | null | undefined, mode: Mode, combat: boolean): Record<string, string>` — локальные CSS custom properties из spec §5.
- Produces: `.tf-game-atmosphere` на корне GamePage с декоративным слоем за содержимым; ни один эффект не ставит inline style на documentElement.

- [ ] **Step 1: Добавить поведенческие проверки и увидеть FAIL.** `sceneLighting({preset:"coast", period:null, weather:null, illustration_key:null}, "dark", false)` содержит glow `#5fae9f`, opacity `0.14`; light — `0.06`; night+dark — `0.105`; combat edge — `#c4553f`. Component test должен сохранить исходные `document.documentElement.style` и dataset.theme после mount/unmount GamePage и после перехода двух локаций. Замокать API/socket существующими локальными mocks, а не обращаться к серверу. Из `web`: `npm test -- src/game/scenePresentation.test.ts src/pages/GameAtmosphere.test.tsx`.

- [ ] **Step 2: Реализовать параметры и слой.** Цвета строго по таблице spec. Night уменьшает opacity; неизвестный preset использует neutral; погода не меняет тему автоматически. Слой pointer-events:none; панели чтения и ввода непрозрачны. free у одного героя не подсвечивается как combat из-за боя другой группы. Transition 400 ms только для оформления, без анимации тумана и частиц; reduced motion убирает transition. Не использовать фильтр brightness на контейнере с текстом.

- [ ] **Step 3: Проверить поставку B.** Targeted тесты + `npm run typecheck`. Browser: dark/light, base/echo-leviathans, free/combat, переключение кампании, уход на Home и открытие карты как обычного пользователя без изменения её кода. Панели/текст не тонируются, атмосфера не появляется в Home или в модалках; клавиатура и прокрутка проходят через декоративный слой.

- [ ] **Step 4: Commit Task 3.** `feat: add local scene lighting`.

### Task 4: Сохраняемый контекст сообщений и корректный scope

**Files:**
- Create: `app/core/chronicle.py`.
- Modify: `app/core/chat.py` (`post_message`, `message_payload`).
- Modify: `app/agents/master/turn.py` (резервирование), `finish.py` (stream/final/recovery), `stepwise.py` (запись narration).
- Modify: `app/agents/prelude.py` (вступление кампании и introduce), `app/agents/rhythm.py` (`_post`).
- Modify: `app/gateway/events.py` (`Stream`), `app/gateway/protocol.py` (`ChatMessage`, `MessageChunk`).
- Modify: `web/src/lib/types.ts` (`ChatMessage`), `web/src/stores/game.ts` (`message.chunk`).
- Generate: `web/openapi.json`, `web/src/lib/api.gen.ts`.
- Test: `tests/test_chronicle_context.py`, `tests/test_chronicle_stream.py` (новые), `web/src/stores/game.test.ts`.

**Interfaces:**
- Produces: `SceneContext(BaseModel)` в core/chronicle: `location_id: str`, `location_name: str` (до 128 символов), extra=forbid.
- Produces: `scene_context(location: Entity | None) -> SceneContext | None` — снимок только ID/имени.
- Produces: `context_for_message(session: AsyncSession, campaign: Campaign, *, seat_id: str | None = None, place_id: str | None = None) -> SceneContext | None` (async): место автора/явного фокуса; у общего мастера при нескольких группах None.
- Produces: `message_scope(msg: Message) -> Literal["public", "party", "private"]`; whisper/whisper_reply имеют приоритет над place.
- Produces: необязательные верхнеуровневые `scene_context` и `scope` в ChatMessage/MessageChunk; TS SceneContext/MessageScope берутся из generated types.
- Extends: `Stream(..., to=None, *, scope: Literal["public", "party", "private"] = "public")`; копирует scene_context из Message.data и передаёт scope. Не выводит область черновика из visible_to=[].

- [ ] **Step 1: Добавить серверные тесты и увидеть FAIL.** `tests/test_chronicle_context.py`: `test_player_context_is_author_place`, `test_human_master_explicit_place`, `test_common_split_narration_has_no_context`, `test_whisper_never_has_public_context`, `test_message_scope_keeps_party_distinct`, `test_context_survives_location_rename`, `test_legacy_message_is_not_backfilled`. Фикстуры — tests.game и tests.test_ws. Проверить настоящий snapshot/replay без расширения аудитории.

  Существенные утверждения:
  ```python
  assert saved.data["scene_context"] == {"location_id": coast_id, "location_name": "Бухта"}
  assert message_payload(saved)["scope"] == "party"
  assert message_payload(saved)["scene_context"]["location_name"] == "Бухта"  # после переименования
  assert message_payload(private)["scope"] == "private"
  assert message_payload(legacy).get("scene_context") is None
  assert "СЕКРЕТ_ДРУГОЙ_ГРУППЫ" not in json.dumps(player_replay, ensure_ascii=False)
  ```
  Из корня: `python -m pytest tests/test_chronicle_context.py -q`.

- [ ] **Step 2: Реализовать снимок и запись обычных сообщений.** В post_message после проверки прав/аудитории добавлять scene_context только action/speech и не приватному narration, с сохранением прежнего data. message_payload отдаёт сохранённый снимок и scope; ничего не вычисляет из текущего мира при чтении. OOC/system/roll/whisper не обогащаются. Контекст не содержит preset, секретов или описания. При повреждённом старом scene_context выдавать None, не ронять replay.

- [ ] **Step 3: Добавить тесты потока и восстановителя и увидеть FAIL.** `tests/test_chronicle_stream.py`: `test_stream_and_final_share_context`, `test_reset_keeps_context`, `test_narration_retry_keeps_original_context`, `test_recovery_recreates_context`, `test_voice_attachment_preserves_context`, `test_opening_after_location_has_context`, `test_greeting_before_story_has_no_context`. Использовать double модели/голоса по образцу tests/test_opening_scene.py и существующих тестов мастера; место менять между резервированием и завершением. Assert chunk.context == final.context == saved.context, одинаковые ID/seq, голоса и ai/place не потеряны. Из корня: `python -m pytest tests/test_chronicle_stream.py -q`.

- [ ] **Step 4: Обогатить пути мастера.** В turn.py снимок берётся после игровых действий из единственного места действующей группы (`ctx.world.scene_places()`), сохраняется в зарезервированную Message.data и `generation_checkpoint.inputs.scene_context`. При неоднозначном месте — None. finish.py берёт сохранённый снимок, не текущую локацию; финальный data объединяет контекст, place и voiceover.data_of и удаляет только pending. При восстановлении удалённой строки восстановить из checkpoint; у старого checkpoint ничего не угадывать. В stepwise — контекст после действий для narration, не system. В prelude — после открытия места до Stream; начальное greeting оставить без контекста. В rhythm._post использовать context_for_message без выбора произвольной группы. Поздняя voiceover.attach обязана сохранять существующий JSON; если уже делает merge, код не менять, достаточно регрессии.

- [ ] **Step 5: Протянуть метаданные по потоку.** Добавить поля в protocol и Stream, scope передавать явно public/party из подтверждённой аудитории для narrations; reset сохраняет metadata. Новый chunk и последующие chunks обновляют metadata черновика в store, даже если запись уже существует. Финальное message.new заменяет черновик по прежним правилам mergeMessages; metadata не теряется при replay.

- [ ] **Step 6: Добавить client regressions и обновить контракт.** В game.test.ts проверить chunk→reset→chunk→message.new→snapshot(replay=true): один ID/seq, один scene_context, scope=party; также поток старого сервера без новых полей. Обновить `python -m app.contract`, затем из web `npm run gen:api`. Запустить оба новых Python файла + `tests/test_ws.py tests/test_opening_scene.py tests/test_contract.py`; в web — `npm test -- src/stores/game.test.ts` и `npm run typecheck`. Все должны PASS.

- [ ] **Step 7: Commit Task 4.** `feat: persist location context for chronicle`. Не включать изменения нарративных контрактов и карт из параллельной разработки.

### Task 5: Разделители и оформление хроники

**Files:**
- Create: `web/src/game/chronicle.ts`, `ChronicleDivider.tsx`.
- Modify: `web/src/game/ChatFeed.tsx`, `MessageView.tsx`, `RichText.tsx`, `scene-immersion.css`.
- Test: `web/src/game/chronicle.test.ts`, `web/src/game/ChatFeed.test.tsx`, `web/src/game/MessageView.test.tsx`, `web/src/game/RichText.test.tsx` (новые).

**Interfaces:**
- Consumes: Task 4 ChatMessage.scene_context/scope; существующие filtered history, notes, pending и voice.
- Produces: `messageScope(message: ChatMessage): MessageScope` с консервативным legacy fallback из spec §6.
- Produces: `ChronicleEntry { message: ChatMessage; divider: { key: string; context: SceneContext; scope: MessageScope } | null }`.
- Produces: `chronicleEntries(messages: ChatMessage[], options: {onlyStory: boolean; hideOoc: boolean}): ChronicleEntry[]` — сначала разделы полной видимой истории, затем фильтрация и перенос заголовка.
- Produces: `ChronicleDivider({context, scope}: {context: SceneContext; scope: MessageScope})`.
- Extends: `RichText({text, variant="default"}: {text: string; variant?: "default" | "chronicle"})`; parseMarkup и inspector не меняются.

- [ ] **Step 1: Написать таблицу примеров группировки и увидеть FAIL.** В chronicle.test.ts местный helper `msg(id, kind, context, scope)` строит ChatMessage без загрузки store. Имена: `same_location_one_divider`, `return_to_place_starts_new_section`, `same_name_different_ids`, `legacy_context_breaks_known_run`, `ooc_roll_private_do_not_split`, `filters_keep_original_boundaries`, `party_is_not_whisper`, `scope_change_starts_section`, `empty_filtered_section_does_not_show_heading`. Для A,A,B,A ожидать heading IDs первого A,B,последнего A; имена не сравниваются. Action(A), action(B), narration(A) при onlyStory=true оставляет заголовок последнего A, не переносит B. public(A) → party(A) создаёт два раздела. Private и OOC не участвуют в границах. Из web: `npm test -- src/game/chronicle.test.ts`.

- [ ] **Step 2: Реализовать grouping и разделитель.** Вход — только сообщения, уже доставленные сервером. Участвуют action/speech/narration со scope public/party. Сравнивать пару location_id/scope. Сообщение участвующего kind без context сбрасывает известную последовательность. Key раздела — ID первого сообщения; при фильтре он сохраняется. При отсутствии оставшихся сообщений heading не выводится. Не читать scene.location, карту, localStorage или текущее время. При обрезке HISTORY_CAP первое известное сообщение создаёт обычный заголовок; не выдумывать предшествующую историю.

- [ ] **Step 3: Добавить тесты реальных компонентов и увидеть FAIL.** ChatFeed.test.tsx: история A→B→A, переключение обоих фильтров, streaming/final с тем же ID, чтение старой истории и кнопка новых сообщений. MessageView.test.tsx: action/speech свои и чужие, group narration с whisper=true+scope=party, настоящий private, roll, failed и pending/withdraw, voice. RichText.test.tsx: variant chronicle сохраняет доступную кнопку и inspector.open, скрывает только декоративный sup; default сохраняет его. Mocks голоса не вызывают реальное воспроизведение.

- [ ] **Step 4: Интегрировать хронику и типографику.** ChatFeed использует chronicleEntries вместо прямого shown.map; считает last/unseen по сообщениям, а не по заголовкам. MessageView использует messageScope для оформления narration/private; фильтр onlyStory допускает party narration. Действия читаются в одном направлении, имя героя и состояния остаются рядом. Голос, обработка, отмена и карточки бросков сохраняются. В RichText variant chronicle — тонкое подчёркивание с hover/focus, без sup; только narration вызывает этот вариант. Статусы ошибок не сворачивать и не скрывать декоративным оформлением. Цвета интерактивных сущностей не менять.

  Для ресайза контейнера использовать ResizeObserver и якорь первого видимого сообщения (ID + смещение верхнего края относительно viewport ленты). Изменение высоты шапки при stuck=false восстанавливает этот якорь; при stuck=true оставляет конец истории. Observer очищается при unmount, отсутствие ResizeObserver имеет безопасный запасной путь. В component test проверить этот сценарий через mock ResizeObserver; размеры/переносы окончательно проверяются браузером в Task 6. Не добавлять виртуализацию или новую библиотеку.

- [ ] **Step 5: Проверить поставку C по автоматике.** Из web: `npm test -- src/game/chronicle.test.ts src/game/ChatFeed.test.tsx src/game/MessageView.test.tsx src/game/RichText.test.tsx src/stores/game.test.ts`; затем `npm run build`. Ожидается PASS; восстановление после merge не удваивает heading, private не становится публичным или заголовком.

- [ ] **Step 6: Commit Task 5.** `feat: render adventure chronicle with location sections`.

### Task 6: Визуальная приёмка и проверка границ параллельной разработки

**Files:**
- Create: `docs/scene-immersion/verification.md` и снимки из списка ниже.
- Modify: `docs/README.md` (ссылки на spec, plan и verification).
- Correct only if needed: файлы Tasks 1–5; любые исправления сопровождаются соответствующей регрессией.

**Interfaces:**
- Consumes: поставки A/B/C, запущенные существующие backend/frontend.
- Produces: reviewable screenshots + запись фактически выполненных проверок; никакого нового runtime/debug UI.

- [ ] **Step 1: Проверить полный набор в текущей реализации.** Из корня: `python -m pytest tests/test_scene_presentation.py tests/test_scene_presentation_tools.py tests/test_chronicle_context.py tests/test_chronicle_stream.py tests/test_ws.py tests/test_opening_scene.py tests/test_contract.py -q`, `python -m ruff check app/core/scene_presentation.py app/core/chronicle.py app/tools/master/presentation.py app/tools/runtime.py app/core/chat.py app/gateway/events.py app/gateway/protocol.py app/agents/master/turn.py app/agents/master/finish.py app/agents/master/stepwise.py app/agents/prelude.py app/agents/rhythm.py`. Из web: `npm test`, `npm run build`. Проверять exit code и реальные результаты. Не пересобирать/перезапускать production или Docker ради записи плана.

- [ ] **Step 2: Выполнить визуальную матрицу.** Использовать browser automation только если доступна в среде; иначе реальный браузер и ручную проверку, честно указать способ. Desktop 1440×900, phone 390×844, узкий phone 320×568; тёмная/светлая тема; base/echo. Сцены tavern/coast/crypt/neutral, free/combat, длинное имя, отсутствующее место, ошибка картинки, свернуть/развернуть, переход, reconnect, поток. На узком телефоне при открытой клавиатуре ввод достижим, обязательные реакции доступны, горизонтальной прокрутки нет. При reduced motion никаких переходов света. Клавиатурой доступны шапка, ссылки, фильтры и ввод; focus виден.

- [ ] **Step 3: Проверить чтение и взаимодействие.** Прокрутить старую историю, получить chunk и новое сообщение: позиция не прыгает, появилась кнопка «Новые сообщения ↓». Свернуть шапку: положение чтения сохранено. Перейти в Home: атмосфера отсутствует. Открыть существующую карту: она работает с прежними действиями и оформлением; не делать изменения её кода или contract. В разделённой группе видеть свой preset/free, пока соседняя группа в crypt/combat. Whisper не образует раздела.

- [ ] **Step 4: Сохранить свидетельства.** Файлы `desktop-coast-dark.png`, `desktop-tavern-light.png`, `phone-chronicle.png`, `phone-combat.png`, `phone-narrow-collapsed.png`, `header-fallback.png` в `docs/scene-immersion/`. В verification.md записать commit/revision, команды и результаты, браузер/viewport, фактические ограничения и сравнение с исходными снимками. Если браузер недоступен, не отмечать визуальную приёмку как пройденную.

- [ ] **Step 5: Проверить diff и сам план.** `git diff --check`; проверить список изменённых файлов и отсутствие собственных изменений в MapWindow/BookMap/GridBoard/MapGlyph/MapZoom/map/mapPresets, app/core/map, topology, world_generation и документах карт. Проверить общие protocol/runtime/types по своим фрагментам. Не использовать git restore, reset или checkout для удаления чужих изменений. Обновить docs/README.md только ссылками этого проекта.

- [ ] **Step 6: Commit Task 6.** `docs: record scene immersion visual verification`. Итоговый отчёт должен различать автоматические проверки и фактическую визуальную приёмку.

## Порядок выполнения и приёмки

Выполнять 1 → 2 → 3 → 4 → 5 → 6. После Task 2 показать поставку A, после Task 3
поставку B, после Task 6 — готовый игровой экран и ограничения. Tasks 4–5
зависят друг от друга и не требуют готовности карт или новой адаптации истории.

Для этой работы рекомендовано обычное выполнение в текущей сессии:
изменения имеют общие точки scene_payload, protocol, GamePage и ChatFeed,
а параллельно уже идёт отдельная разработка карт. Перед реализацией
пользователь просматривает этот план и выбирает обычное выполнение либо
выполнение через агентов. Сам план не разрешает запуск разработки карт,
генерацию изображений, деплой или изменения чужих незакоммиченных файлов.

## Самопроверка документа

- [x] Все три выбранных изменения имеют свои задачи и критерии приёмки.
- [x] Выбор готовых иллюстраций/SVG отражён в поставке A.
- [x] Исключение карт явно закреплено, источником данных служит только сцена.
- [x] Старые payload и история имеют запасной путь без догадок о месте.
- [x] Контекст определён одинаково в записи, стриминге, восстановлении и клиенте.
- [x] Все пять Review Focus покрыты конкретными задачами и проверками.
- [x] Не добавлены миграции, сервисы, зависимости или изменения механики света.
- [x] Проверки CSS/размеров отдельно от jsdom, результаты выполнения не заявлены заранее.
