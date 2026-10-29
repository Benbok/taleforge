# Подложка карты локации Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Администратор вручную создаёт нарисованную подложку вида сверху под схемой «Вокруг»; клики, метки выходов и предметы остаются на прежнем слое.

**Architecture:** Сервер рисует упрощённый каркас области (Pillow) из публичной части сохранённой схемы `location.state["sketch"]`. ComfyUI (RealVisXL, img2img) превращает каркас и описание в картину. Жизненный цикл попытки (квитанция, аренда, устаревание, аудит) живёт в новом общем сервисе `app/core/artwork/` над таблицей `artworks`; карта — его первый «рецепт». Старые иллюстрации локаций, снаряжение и портреты не меняются. На фронтенде картина вставляется `<image>` внутри SVG карты под слоем клеток.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pillow 12, httpx (MockTransport в тестах), ComfyUI, React + Vitest.

**Spec:** `docs/superpowers/specs/2026-10-29-map-backdrop-design.md`

## Global Constraints

- Запуск только вручную; вход, открытие карты и проверка статуса генерацию не запускают.
- Запускает только администратор платформы: `is_admin(viewer.user)` из `app/core/campaigns.py` (`platform_role in ("admin","super_admin")`); сервер отказывает (403), а не только прячет кнопку. Админ, не состоящий в кампании, получает 404 от `get_viewer`, как у иллюстрации.
- Статус и файл доступны всем участникам, которые видят эту область (проекция `universal_scene`).
- В каркас и промпт попадает только публичная часть: без `hidden`-выходов, без `unplaced_exits`, без `features`/предметов, без state/заметок мастера.
- Модель RealVisXL V5.0 (`RealVisXL_V5.0_fp16.safetensors`), img2img, без ControlNet; нужен только `PORTRAIT_COMFYUI_URL`. Тесты не требуют запущенный ComfyUI.
- Размер входного образа: длинная сторона 768, обе стороны кратны 64, короткая не меньше 384; 28 шагов; `denoise` подбирается в Task 7 из {0.55, 0.65, 0.75}.
- Флаг `MAP_BACKDROP_ENABLED`, по умолчанию выключен; при выключенном статус отдаёт `enabled: false`, кнопка скрыта, запуск → 409.
- Старое изображение остаётся при ошибке; ожидающая попытка одна на `(campaign_id, kind, subject_id)`; `request_key` не повторяется.
- Не менять `app/core/location_artwork.py`, `equipment_artwork.py`, их модели, роуты и тесты.
- Тексты интерфейса и ошибок — по-русски, в стиле существующих.
- Миграция: `revision = "universal_0017"`, `down_revision = "universal_0016"`.

## Review Focus

- Область без описания: запуск → 409 «сначала дождитесь описания»; `can_generate` false.
- Сетка нестандартного отношения сторон (1×8, 40×3): каркас укладывается в ограничения размера и не вырождается.
- Схема отсутствует (`state` без `sketch`): статус `idle`, `can_generate` false, запуск → 409 «сначала создайте схему».
- Игрок увидел, как скрытый выход стал открытым: хэш меняется, картинка `stale`, прежний файл продолжает отдаваться.
- Отряд ушёл в другую область, пока шла генерация: результат сохраняется за исходной областью и не публикуется в чужой.
- Запрос с чужим `image_id` или областью, недоступной зрителю: 404.

## File Structure

- Create `app/core/artwork/__init__.py`, `app/core/artwork/recipe.py` — `ArtworkRecipe`, интерфейс рецепта.
- Create `app/core/artwork/service.py` — `status`, `generate`, `read_image`, `ArtworkPending`.
- Create `app/core/universal/backdrop_skeleton.py` — `public_sketch`, `skeleton_size`, `render_skeleton`.
- Create `app/core/map_backdrop.py` — рецепт карты, `current_area`.
- Create `app/agents/map_backdrop_images.py` — фабрики генератора и переводчика.
- Create `content/workflows/map-backdrop-realvisxl-api.json`.
- Create `app/api/map_backdrop.py` — роутер.
- Create `alembic/versions/0017_artworks.py`.
- Modify `app/agents/comfyui_portraits.py`, `app/db/models.py`, `app/config.py`, `app/main.py`, `.env.example`, `web/openapi.json`, `web/src/lib/api.gen.ts` (генерация), `web/src/game/OrientationMap.tsx`, `web/src/game/LocationMap.tsx`.
- Create `web/src/game/MapBackdrop.tsx` (+ `MapBackdrop.test.tsx`), `docs/map-backdrop.md`.
- Tests: `tests/test_comfyui_init_image.py`, `tests/test_backdrop_skeleton.py`, `tests/test_artwork_service.py`, `tests/test_map_backdrop_api.py`.

---

### Task 1: ComfyUI принимает входной образ

**Files:**
- Modify: `app/agents/comfyui_portraits.py` (`ComfyUIPortraitGenerator.__init__`, `generate`)
- Create: `content/workflows/map-backdrop-realvisxl-api.json`
- Test: `tests/test_comfyui_init_image.py`

**Interfaces:**
- Produces: `ComfyUIPortraitGenerator.generate(description: dict, *, init_image: bytes | None = None) -> ImageReply`. Если `init_image` задан, перед `/prompt` делается `POST /upload/image` (multipart, поля `image`, `overwrite=true`, `type=input`), из ответа берётся `name`, и плейсхолдер `{{init_image}}` в workflow заменяется этим именем. Если `init_image` задан, а в workflow нет `{{init_image}}`, или наоборот — `ValueError` → `PortraitError("provider_error")`. Существующие вызовы без `init_image` ведут себя как раньше.
- Workflow `map-backdrop-realvisxl-api.json`: узлы как у `location-realvisxl-api.json`, но `EmptyLatentImage` заменён на `LoadImage` (`"image": "{{init_image}}"`) → `VAEEncode` (`pixels`, `vae` из узла 4) → `KSampler.latent_image`; `steps` 28, `denoise` 0.65 (временно), `filename_prefix` `Taleforge/map-backdrop`; узлы SaveImage = "9", текст "6", негативный "7", checkpoint "4".

- [ ] **Step 1: Write failing tests** в `tests/test_comfyui_init_image.py`: (a) `test_init_image_is_uploaded_and_named_in_graph` — `MockTransport`: `/upload/image` возвращает `{"name": "bd.png"}`, `/prompt` проверяет `graph["10"]["inputs"]["image"] == "bd.png"` и `graph["3"]["inputs"]["denoise"] <= 0.75`, далее как в `tests/test_comfyui_portraits.py`; ожидается `reply.data == PNG`, один `/upload/image` и один `/prompt`. (b) `test_upload_failure_never_submits_prompt` — upload отдаёт 500, ожидается `PortraitError("provider_error")` и ноль вызовов `/prompt`. (c) `test_workflow_without_init_placeholder_rejects_image` — `location-realvisxl-api.json` + `init_image=PNG` → `PortraitError`. (d) `test_existing_workflow_still_works_without_image` — вызов без `init_image` на `location-realvisxl-api.json` не делает upload.
- [ ] **Step 2: Run** `pytest tests/test_comfyui_init_image.py -v` → FAIL (параметр неизвестен).
- [ ] **Step 3: Implement** параметр `init_image` в `generate`: загрузка внутри того же `AsyncClient` и того же `asyncio.timeout`; имя файла — `f"taleforge-{secrets.token_hex(8)}.png"`; `substitute` заменяет `{{init_image}}`. Добавить файл workflow (LoadImage — узел "10", VAEEncode — "11").
- [ ] **Step 4: Run** `pytest tests/test_comfyui_init_image.py tests/test_comfyui_portraits.py -v` → PASS.
- [ ] **Step 5: Commit** `git add app/agents/comfyui_portraits.py content/workflows/map-backdrop-realvisxl-api.json tests/test_comfyui_init_image.py && git commit -m "feat: ComfyUI adapter accepts an optional init image"`

---

### Task 2: Публичный каркас области

**Files:**
- Create: `app/core/universal/backdrop_skeleton.py`
- Test: `tests/test_backdrop_skeleton.py`

**Interfaces:**
- Produces:
  - `public_sketch(sketch: dict) -> dict` — глубокая копия только с ключами `shape, cols, rows, walls, mask, edges, terrain, material, environment, exits`; из `exits` убраны `hidden=True`, у остальных оставлены `name, side, at, kind, state, width`; `features`, `unplaced_exits`, `party`, `to`, `room_ref`, `beyond`, `cells`, `passage_ref`, `route_ref` отброшены.
  - `skeleton_size(cols: int, rows: int) -> tuple[int, int]` — длинная сторона 768, короткая пропорциональна, кратна 64, не меньше 384 (крайние сетки получают 768×384 / 384×768).
  - `render_skeleton(public: dict) -> bytes` — PNG нужного размера: пол светлый, стены/границы тёмные, `terrain` (road/path — песочный, stream — синий, bridge — коричневый), проходы — яркие отметки на стороне; детерминирован (одинаковый вход → одинаковые байты).

- [ ] **Step 1: Write failing tests**: `test_public_sketch_drops_hidden_and_private_fields` (скрытый выход, `features`, `unplaced_exits`, `party`, `to` исчезают; видимый выход сохраняется с `name/side/at`); `test_skeleton_size_extremes` (`(1,8)→(384,768)`, `(40,3)→(768,384)`, `(10,10)→(768,768)`, обе стороны кратны 64); `test_render_is_deterministic_and_has_requested_size` (PNG открывается Pillow, размер совпадает, два вызова дают равные байты); `test_wall_and_floor_colors_differ` (пиксель стены ≠ пикселя пола); `test_mask_marks_non_floor_dark`.
- [ ] **Step 2: Run** `pytest tests/test_backdrop_skeleton.py -v` → FAIL.
- [ ] **Step 3: Implement** функции в `backdrop_skeleton.py`; клетки рисуются прямоугольниками `PIL.ImageDraw`, `mask[y][x] == "."` — пол (как в `LocationMapSvg`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: public area skeleton renderer for map backdrops`

---

### Task 3: Таблица `artworks` и миграция

**Files:**
- Modify: `app/db/models.py` (после `LocationArtwork`)
- Create: `alembic/versions/0017_artworks.py`
- Test: `tests/test_artwork_service.py` (первый тест — схема)

**Interfaces:**
- Produces: модель `Artwork` (`__tablename__ = "artworks"`): `id` String(32) pk, default `new_id("aw")`; `campaign_id` FK `campaigns.id` ondelete CASCADE, index; `kind` String(32); `subject_id` String(64); `request_key` String(128); `source_digest` String(64); `status` String(16) default `"pending"`; `mime` String(64) nullable; `error` String(64) nullable; `lease_until` DateTime(tz); `created_at` DateTime(tz) default `now`. Ограничения: `UniqueConstraint("campaign_id","kind","request_key", name="uq_artwork_request")`, `CheckConstraint("status IN ('pending','ready','failed')", name="ck_artwork_status")`, частичный уникальный индекс `uq_artwork_pending` по `(campaign_id, kind, subject_id)` при `status = 'pending'` (sqlite_where и postgresql_where, как у `LocationArtwork`); индекс `ix_artwork_subject` по `(campaign_id, kind, subject_id)`.

- [ ] **Step 1: Write failing test** `test_artwork_table_rejects_two_pending_for_one_subject` — вставка двух `pending` с одним `(campaign, kind, subject)` → `IntegrityError`; `ready` рядом с `pending` допустим.
- [ ] **Step 2: Run** `pytest tests/test_artwork_service.py -v` → FAIL (нет модели).
- [ ] **Step 3: Implement** модель и миграцию (`op.create_table`, индексы, `downgrade` с `drop_table`).
- [ ] **Step 4: Run** тест и `pytest tests/test_db_startup.py -v` (проверка, что миграции применяются) → PASS.
- [ ] **Step 5: Commit** `feat: generic artworks table`

---

### Task 4: Общий сервис жизненного цикла

**Files:**
- Create: `app/core/artwork/__init__.py`, `app/core/artwork/recipe.py`, `app/core/artwork/service.py`
- Test: `tests/test_artwork_service.py`

**Interfaces:**
- Consumes: `Artwork` (Task 3); `validate_image`, `PortraitError` из `app/agents/portraits.py`; `AccessDenied, Conflict, NotFound` из `app/core/campaigns.py`; `LlmCall`, `as_utc`, `now` из `app/db/models.py`.
- Produces:
  - `recipe.py`: `@dataclass(frozen=True) class ArtworkRecipe` с полями `kind: str`, `media_subdir: str`, `purpose: str` (метка `LlmCall`), `noun: str` (для сообщений), и методами-вызываемыми: `source: Callable[[Viewer, Entity], dict]` (публичный источник; для субъекта-локации), `can_generate: Callable[[Viewer, dict], bool]`, `init_image: Callable[[dict], bytes | None]`, `prompt_source: Callable[[dict], dict]` (что идёт в переводчик/генератор: `{"identity","appearance","personality"}`).
  - `service.py`: `digest(source: dict) -> str` (sha256 JSON sort_keys), `async status(session, viewer, recipe, subject, enabled) -> dict` (поля `status, image_url, stale, enabled, can_generate, error`; URL строится `recipe.url(viewer.campaign.id, subject.id, image_id)` — добавить в рецепт `url: Callable[[str,str,str], str]`), `async generate(session, viewer, recipe, subject, request_key, regenerate, generator, translator, media_dir) -> dict`, `async read_image(session, viewer, recipe, subject, image_id, media_dir) -> tuple[Path, str]`, `class ArtworkPending(Conflict)`.
  - Правила `generate` — те же, что в `app/core/location_artwork.py:67-187`, с заменой `LocationArtwork` на `Artwork` (фильтр по `kind` и `subject_id`), `path = media_dir / recipe.media_subdir / job.id`, `generator.generate(prepared, init_image=recipe.init_image(source))` только если `init_image` не `None`. Права: `AccessDenied` если `not recipe.can_generate(viewer, source)` (текст «подложку создаёт администратор»); `Conflict` если генератор `None`. Статус `stale` — если дайджест текущего источника ≠ дайджесту последней `ready`.

- [ ] **Step 1: Write failing tests** (фейковый рецепт, фейковые generator/translator как в `tests/test_location_artwork.py`): `test_generate_once_and_cache` (второй запрос с другим ключом без `regenerate` не вызывает генератор); `test_regenerate_creates_new_ready_and_keeps_old_on_failure`; `test_failed_receipt_is_not_replayed`; `test_second_pending_returns_artwork_pending`; `test_expired_pending_is_failed_and_new_attempt_allowed`; `test_stale_source_marks_stale_and_blocks_publish_if_changed_midway` (источник меняется во время генерации → `Conflict`, файл не остаётся); `test_non_permitted_viewer_gets_access_denied_and_generator_not_called`; `test_audit_row_written_with_recipe_purpose`; `test_read_image_rejects_foreign_subject_or_campaign`.
- [ ] **Step 2: Run** `pytest tests/test_artwork_service.py -v` → FAIL.
- [ ] **Step 3: Implement** модули. Копировать не строки, а правила (см. Interfaces); общие мелочи (`validate_image`, `PortraitError`) импортировать.
- [ ] **Step 4: Run** → PASS; затем `pytest tests/test_location_artwork.py -v` → PASS (старое не затронуто).
- [ ] **Step 5: Commit** `feat: generic artwork lifecycle service`

---

### Task 5: Рецепт карты, фабрики и конфиг

**Files:**
- Create: `app/core/map_backdrop.py`, `app/agents/map_backdrop_images.py`
- Modify: `app/config.py` (`map_backdrop_enabled: bool = False`, `MAP_BACKDROP_ENABLED`), `.env.example`
- Test: `tests/test_map_backdrop_api.py` (рецептные тесты)

**Interfaces:**
- Consumes: `public_sketch`, `render_skeleton` (Task 2); `ArtworkRecipe` (Task 4); `public_location_name` из `app/core/universal/places.py`; `universal_scene` из `app/core/universal/scene.py`.
- Produces:
  - `map_backdrop.RECIPE: ArtworkRecipe` с `kind="map_backdrop"`, `media_subdir="map-backdrops"`, `purpose="map_backdrop_illustration"`.
  - `async current_area(session, viewer, location_id) -> Entity` — как `current_location` в `app/core/location_artwork.py:31-39` (та же проекция сцены, иначе `NotFound`).
  - `source(viewer, location) -> dict` = `{"identity": public_location_name(...), "appearance": location.description or "", "personality": "", "sketch": public_sketch(location.state["sketch"])}`; если схемы нет — `Conflict("сначала создайте схему")` при запуске, а в `status` источник считается пустым и `can_generate=False`.
  - `can_generate(viewer, source) -> bool` = `is_admin(viewer.user)` и описание непусто и схема есть.
  - `init_image(source) -> bytes` = `render_skeleton(source["sketch"])`.
  - `prompt_source(source)` → без `sketch`; (переводчик получает только название и описание).
  - `map_backdrop_images.create_map_backdrop_generator(settings)` — `ComfyUIPortraitGenerator` с workflow из Task 1 и `MAP_BACKDROP_STYLE` (вид сверху, «top-down game map, painted fantasy environment, no characters, no text, no frame», с оговоркой «follow the layout of the supplied image»); `create_map_backdrop_translator(llm, settings)` — `TechnicalPortraitTranslator` с `purpose="map_backdrop_translation"` и промптом, адаптированным из `LOCATION_TRANSLATION` (описывает вид сверху, не придумывает объекты и секреты).

- [ ] **Step 1: Write failing tests**: `test_source_excludes_hidden_exit_features_and_secrets` (у области в `state` есть `secret`, скрытый выход и feature — ни одно не попадает в `source`/`prompt_source`); `test_can_generate_requires_admin_description_and_sketch`; `test_digest_changes_when_hidden_exit_becomes_visible`; `test_config_flag_defaults_off`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** модули, поле конфига, строку `MAP_BACKDROP_ENABLED=0` в `.env.example` рядом с `LOCATION_ARTWORK_ENABLED`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat: map backdrop recipe, factories and config flag`

---

### Task 6: API и подключение

**Files:**
- Create: `app/api/map_backdrop.py`
- Modify: `app/main.py` (рядом со строками 38, 131-139, 244)
- Modify: `web/openapi.json`, `web/src/lib/api.gen.ts` (штатная генерация проекта — найти команду в `web/package.json`)
- Test: `tests/test_map_backdrop_api.py`

**Interfaces:**
- Produces: роутер `/api/campaigns/{campaign_id}/locations/{location_id}/map-backdrop` с `GET` (статус), `POST` (`{request_key: str(1..128), regenerate: bool=False}`), `GET /{image_id}` (файл, заголовки как у иллюстрации: `Cache-Control: private, max-age=3600`, `Vary: Authorization`, `X-Content-Type-Options: nosniff`). Ответ — `MapBackdropOut` с теми же полями, что `LocationArtworkOut`. `ArtworkPending` → 409 `{"code":"artwork_pending", ...}`. Состояние приложения: `app.state.map_backdrop_generator`, `map_backdrop_translator`, `map_backdrop_media_dir`; создаются только при `settings.map_backdrop_enabled`.

- [ ] **Step 1: Write failing tests** по образцу `tests/test_location_artwork.py` (сцена с областью `bd_room`, сохранённая схема и скрытый выход в `state`): `test_admin_owner_generates_once_and_players_can_view` (админ-владелец → ready; игрок видит `image_url` и скачивает файл; `can_generate` у игрока false); `test_non_admin_owner_cannot_generate` (владелец без платформенной роли → 403, генератор не вызван); `test_hidden_secrets_never_reach_translator_or_skeleton` (по `payloads` и по байтам init-образа: в запросе нет `SECRET`); `test_disabled_flag_reports_disabled_and_rejects` (`generator=None` → `enabled: false`, POST → 409); `test_foreign_or_unseen_area_is_404`; `test_failed_refresh_keeps_previous_image`; `test_changed_description_marks_stale`; `test_missing_sketch_blocks_generation`; `test_unauthenticated_file_is_401`.
- [ ] **Step 2: Run** `pytest tests/test_map_backdrop_api.py -v` → FAIL.
- [ ] **Step 3: Implement** роутер и подключение; запустить штатную регенерацию OpenAPI и типов, убедиться, что diff `web/openapi.json` и `api.gen.ts` содержит только новые маршруты.
- [ ] **Step 4: Run** `pytest tests/test_map_backdrop_api.py tests/test_location_artwork.py -v` → PASS.
- [ ] **Step 5: Commit** `feat: map backdrop API`

---

### Task 7: Подбор качества на живом ComfyUI

**Files:**
- Modify: `content/workflows/map-backdrop-realvisxl-api.json`, `app/agents/map_backdrop_images.py` (стиль/негатив — по результатам)
- Create: `media/map-backdrop-preview.png` (пример, как `media/location-artwork-preview.png`)

**Interfaces:**
- Consumes: рабочий ComfyUI по `PORTRAIT_COMFYUI_URL`, `render_skeleton`, `create_map_backdrop_generator`.

- [ ] **Step 1:** Скриптом из scratchpad (вне репозитория) отрендерить каркас для области «Задний двор «Зелёного дракона» с коновязью и водостоком» (сетка и выходы с вашего скриншота) и сгенерировать три картинки с `denoise` 0.55 / 0.65 / 0.75 через `create_map_backdrop_generator`.
- [ ] **Step 2:** Показать три картинки владельцу рядом с каркасом, получить выбор значения; записать выбранный `denoise` в workflow; при необходимости поправить стиль и негативный промпт (убрать «portrait, close-up», добавить «text, labels, characters, perspective view»).
- [ ] **Step 3:** Сохранить итоговый пример в `media/map-backdrop-preview.png`; записать время генерации.
- [ ] **Step 4: Run** `pytest tests/test_comfyui_init_image.py -v` → PASS (значение `denoise` ≤ 0.75 остаётся).
- [ ] **Step 5: Commit** `feat: tuned map backdrop workflow and preview`

---

### Task 8: Интерфейс карты

**Files:**
- Create: `web/src/game/MapBackdrop.tsx`, `web/src/game/MapBackdrop.test.tsx`
- Modify: `web/src/game/OrientationMap.tsx`, `web/src/game/LocationMap.tsx` (`LocationMapSvg`, `LocationMap`: проп `backdrop?: {areaId: string; src: string}`)
- Test: `web/src/game/MapBackdrop.test.tsx`, существующий `web/src/game/map.test.ts` остаётся зелёным

**Interfaces:**
- Produces: хук `useMapBackdrop(campaignId: string, locationId: string): {artwork: Artwork | null; src: string | null; busy: boolean; error: string; generate: (regenerate?: boolean) => Promise<void>}` — опрос статуса как в `web/src/game/LocationArtwork.tsx` (2,5 с при `pending`, 15 с иначе, повтор через 5 с после обрыва, ключ запроса сбрасывается при `failed`, ответы после смены области игнорируются); `src` получается через `useAuthedImage(artwork.image_url)`. Компонент `BackdropControls({backdrop})` — кнопка «Создать подложку» / «Обновить подложку» (только при `can_generate`), статус «Создаю подложку…», пометка «Подложка устарела», ошибка с `role="alert"`; при `enabled: false` ничего не рисует.
- `LocationMapSvg`: если `backdrop` и `area.id === backdrop.areaId` и область текущая, перед `SketchSurface` рисуется `<image href={src} x=0 y=0 width={sketch.cols} height={sketch.rows} preserveAspectRatio="none" pointerEvents="none" data-map-backdrop="true"/>` внутри `<g transform=translate(offset)>`, а базовая заливка пола (`SketchSurface`) становится полупрозрачной — добавить необязательный проп `floorOpacity?: number` в `SketchSurfaceProps` (по умолчанию 1; со подложкой 0.18), применяется к двум `<rect>` заливки пола и сетки. Клики и метки не меняются.

- [ ] **Step 1: Write failing tests**: `test_button_shown_only_when_can_generate`; `test_click_posts_with_request_key_and_shows_busy_then_image`; `test_pending_polls_then_ready`; `test_stale_label_and_refresh_sends_regenerate_true`; `test_disabled_renders_nothing`; `test_backdrop_image_rendered_under_current_area_only` (в SVG есть `[data-map-backdrop]` внутри группы текущей области и нет у `remembered`); `test_late_reply_from_previous_area_is_ignored`.
- [ ] **Step 2: Run** `cd web && npx vitest run src/game/MapBackdrop.test.tsx` → FAIL.
- [ ] **Step 3: Implement** хук, компонент и прокидывание `backdrop` по цепочке `OrientationMap → LocationMap → LocationMapSvg → SketchSurface`; `OrientationMap` вызывает `useMapBackdrop(campaignId, map.here.id)` только когда `visual` есть, `<BackdropControls>` ставится над схемой.
- [ ] **Step 4: Run** `cd web && npx vitest run src/game && npx tsc --noEmit` → PASS без ошибок типов.
- [ ] **Step 5: Commit** `feat(ui): map backdrop under the orientation map`

---

### Task 9: Документация и финальная проверка

**Files:**
- Create: `docs/map-backdrop.md` (по образцу `docs/location-artwork.md`: включение, workflow, что идёт в промпт, права, устаревание, хранение)
- Modify: `docs/superpowers/specs/2026-10-29-map-backdrop-design.md` (размер входного образа — по отношению сторон сетки, а не всегда 768×768)

- [ ] **Step 1:** Написать `docs/map-backdrop.md`: `MAP_BACKDROP_ENABLED=1`, ComfyUI, только администратор, хранится в `MEDIA_DIR/map-backdrops`, записи в `artworks`, аудит `map_backdrop_illustration` и `map_backdrop_translation`, проверка с датой и временем генерации из Task 7.
- [ ] **Step 2: Run** `pytest -q` — весь набор зелёный; `cd web && npx vitest run && npx tsc --noEmit` — зелёный.
- [ ] **Step 3: Run** `graphify update .` (требование AGENTS.md).
- [ ] **Step 4:** Ручная проверка в приложении (skill `run`): включить флаг, зайти администратором в игру, открыть карту, нажать «Создать подложку», дождаться картины, убедиться, что клики по выходам и предметам работают, перезагрузить страницу — картина на месте; игроком без роли админа кнопки нет, картина видна.
- [ ] **Step 5: Commit** `docs: map backdrop`

---

## Self-review

- Покрытие спека: ручной запуск и только админ — Task 4–6, 8; каркас без секретов — Task 2, 5, 6; img2img без ControlNet — Task 1, 7; общий слой — Task 3–4; старый код не тронут — Task 4 шаг 4 и Global Constraints; устаревание — Task 4–6; флаг по умолчанию выключен — Task 5–6; cover/привязка к сетке — Task 8 (картина растягивается на прямоугольник сетки, т.к. размер входа пропорционален сетке — уточнение спека в Task 9).
- Типы: `ArtworkRecipe` определён в Task 4 и используется в Task 5–6 с теми же полями (`source`, `can_generate`, `init_image`, `prompt_source`, `url`, `kind`, `media_subdir`, `purpose`, `noun`); `generate(..., init_image=)` из Task 1 вызывается в Task 4.
- Размер: девять задач, из них только Task 4 и 8 крупные; код в плане — только сигнатуры и тесты.
