# Main Menu Music Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить выбранную пользователем тему `Edge of the World` в кабинет Taleforge, с независимой громкостью и выключением в профиле, сохранением настроек аккаунта и плавным переходом к звуку игры.

**Architecture:** Существующий SoundMixer становится ресурсом уровня приложения и получает поверхности menu/scene/silent; отдельный gain меню сохраняет независимость от игровых настроек. Сервер выдаёт фиксированный MP3 из подкаталога AUDIO_DIR и хранит две настройки User. Координатор React связывает маршруты, аккаунт и visibility с микшером.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy, Alembic; React 19, TypeScript, Zustand, Vite, Vitest, Testing Library; существующий Web Audio/HTMLAudioElement.

**Spec:** [2026-10-12-menu-music-design.md](../specs/2026-10-12-menu-music-design.md).

## Global Constraints

- Основной трек: `D:\Загрузки\Edge-of-the-World.mp3` → `audio/menu/edge_of_the_world.mp3`, только копирование оригинала.
- SHA-256: `2366ac3207692661f96760f888e817b10b7142a188dbfb7dc894330c3c4d1671`; 5 980 756 байт; 190.016 s; MP3 stereo / 48 000 Hz.
- Не назначать треку лицензию или авторство Tabletop Audio.
- Настройки по умолчанию: `enabled=true`, `volume=0.2`; диапазон 0..1, конечное число; громкость 0 не меняет enabled.
- Переход меню↔сцена и возобновление: 0.5 s; выключение/visibility pause: 0.15 s; переход треков сцены остаётся 3.5 s.
- PATCH объединяет изменения с задержкой 250 ms; не больше одного запроса одновременно.
- Авторизованные маршруты меню: `/`, `/new`, `/profile`, `/heroes/:hid`, `/c/:id/manage`, `/c/:id/hero`.
- Точный `/c/:id` — scene; `/admin`, `/invite/:token`, экран входа и неизвестные маршруты — silent.
- Не менять игровые настройки `tf_sound`; общий AudioContext/разблокировка, два переиспользуемых аудиоэлемента.
- Новые зависимости, генерация музыки, смена темы пользователем, отдельная админка выбора трека, несколько тем, звук на странице входа и межвкладочный лидер воспроизведения в эту поставку не входят.
- Сохранить текущие чужие изменения карт, повествования и оформления сцен. Перед началом проверить `git status` и актуальный Alembic head; номер миграции согласовать с фактической цепочкой, не создавать случайную вторую head.

## Review Focus

1. Быстрые переключения меню→сцена→меню во время fetch/priming: устаревшая музыка не стартует. Тесты Task 2 и 3.
2. Autoplay отказал, пользователь повторил нажатие: текущий выбранный трек сохранён и запускается. Task 2.
3. Поздний PATCH или fetch после logout/login другим пользователем: настройки/звук чужого аккаунта не применяются. Task 3.
4. Ползунок быстро меняется при медленной сети/ошибке: последний выбор сохраняется и не откатывается старым ответом. Task 3 и 4.
5. Прямой вход в игру, отключённый звук кампании, скрытая вкладка и отсутствие MP3: тишина вместо неверной темы; понятное повторное включение. Tasks 1–3 и 5.

## Файлы и ответственности

| Область | Файлы |
|---|---|
| Тема, настройки, API | `audio/menu/edge_of_the_world.mp3`, `audio/menu/README.md`, `app/core/menu_music.py`, `app/api/audio.py`, `app/api/profile.py`, `app/api/auth.py`, `app/api/schemas.py`, `app/db/models.py`, миграция |
| Существующий микшер | `web/src/game/sound.ts`, `sound.playback.test.ts`, `music.test.ts`; `music.ts` менять только при необходимости переиспользования ресурсов |
| Состояние аккаунта | `web/src/audio/menuMusicPreferences.ts`, `web/src/stores/session.ts`, `web/src/lib/types.ts` |
| Управление приложением | `web/src/audio/applicationAudio.ts`, `ApplicationAudio.tsx`, `web/src/App.tsx`, `web/src/lib/useGameSocket.ts` |
| Интерфейс | `web/src/audio/MenuMusicControl.tsx`, `web/src/profile/AudioSettingsSection.tsx`, `web/src/components/Header.tsx`, `web/src/pages/ProfilePage.tsx` |
| Контракт | `web/openapi.json`, `web/src/lib/api.gen.ts`, `web/src/lib/contract.check.ts` |

### Task 1: Тема и сохраняемые настройки аккаунта

**Files:** Create `app/core/menu_music.py`, `tests/test_menu_music.py`, `audio/menu/README.md`, `audio/menu/edge_of_the_world.mp3`, `alembic/versions/0023_user_menu_audio.py` (если 0023 ещё свободен; down_revision — актуальная head).
Modify `app/db/models.py`, `app/api/schemas.py`, `app/api/auth.py`, `app/api/profile.py`, `app/api/audio.py`, `tests/test_profile.py` и файлы контракта.

**Interfaces:**
- `MenuMusicPreferences(Out)`: `enabled: bool = True`, `volume: float = 0.2`.
- `MenuMusicPreferencesPatch(BaseModel)`: строгие enabled/volume с теми же defaults, extra forbid; null запрещён. Применять только `model_fields_set`/`model_dump(exclude_unset=True)`.
- `User.menu_music_enabled`, `User.menu_music_volume` → `UserOut.menu_music: MenuMusicPreferences` через `user_out()`.
- `PATCH /api/me/menu-music` → `MenuMusicPreferences`.
- `theme_path(audio_dir: Path) -> Path`, `theme_track(audio_dir: Path) -> dict[str, Any] | None` в `app/core/menu_music.py`.
- `GET /api/menu-music` → `AudioTrack | None`, `GET /api/menu-music/file` → `FileResponse`; обе ручки с UserDep.

- [ ] **1. Написать тесты API до реализации.** `test_menu_theme_requires_login`, `test_menu_theme_is_not_in_scene_library`, `test_missing_menu_theme`, `test_menu_preferences_defaults_and_partial_patch`, `test_menu_preferences_are_per_user`, `test_menu_preferences_invalid_values`:

```python
assert prefs == {"enabled": True, "volume": 0.2}
assert patch({"enabled": False}) == {"enabled": False, "volume": 0.2}
assert patch({"volume": 0}) == {"enabled": False, "volume": 0}
assert patch({}) == {"enabled": False, "volume": 0}
# Другой пользователь сохраняет defaults. null, -0.1, 1.1, "0.2", enabled="true", неизвестное поле → 422.
# Прямой model_validate для volume NaN/+Inf/-Inf отвергается; HTTP с неконечным числом также не сохраняет его.
# Без входа обе ручки темы/PATCH → 401. Нет файла → metadata null, file 404.
# Файл темы отсутствует среди Library.all()/unsorted()/for_pack().
```

- [ ] **2. Убедиться в красной фазе.** `.venv/Scripts/python.exe -m pytest tests/test_menu_music.py tests/test_profile.py -n 0 -q -p no:cacheprovider --basetemp tools/.cache/menu-red-1` — новые утверждения FAIL.
- [ ] **3. Реализовать перечисленные интерфейсы.** Миграция задаёт NOT NULL и server defaults для двух новых колонок, обратима; проверить старого пользователя после upgrade на изолированной SQLite БД, не на `taleforge.db`. Тему отдавать по фиксированному пути с версионированием/FOREVER. PATCH касается только текущего User.
- [ ] **4. Скопировать MP3 и проверить SHA-256.** PowerShell `Copy-Item -LiteralPath 'D:\Загрузки\Edge-of-the-World.mp3' -Destination 'audio/menu/edge_of_the_world.mp3'`; предварительно создать подкаталог, существующий другой файл не перезаписывать без сравнения. README фиксирует проверенные свойства и источник пользователя. Карточку в `tracks.yaml` не добавлять.
- [ ] **5. Обновить контракт.** `.venv/Scripts/python.exe -m app.contract`; из `web/`: `npm.cmd run gen:api`. Обновить тип User и REST-проверки клиента; сохранить параллельные изменения других контрактов.
- [ ] **6. Зелёная фаза и миграция.** Повторить Task 1 tests плюс `tests/test_audio.py tests/test_contract.py`; изолированная миграция upgrade→downgrade→upgrade сохраняет прежние колонки и выставляет defaults. Проверить хэш файла и отсутствие новой темы в каталоге сцен.
- [ ] **7. Коммит** только файлов Task 1: `feat(audio): add menu theme and account preferences`.

### Task 2: Поверхности и общий жизненный цикл микшера

**Files:** Modify `web/src/game/sound.ts`, `sound.playback.test.ts`, `music.test.ts`; при необходимости `music.ts`.

**Interfaces:**
- `AudioSurface = "menu" | "scene" | "silent"`.
- `SoundMixer.setSurface(surface: AudioSurface): Promise<void>`.
- `SoundMixer.setMenuMusic(track: AudioTrack | null, prefs: MenuMusicPreferences): Promise<void>`.
- `SoundMixer.setDocumentVisible(visible: boolean): Promise<void>`.
- `SoundMixer.clearScene(): void` очищает только сцену; `stop(): void` полностью завершает приложение.
- `menuStatus: "disabled" | "locked" | "loading" | "playing" | "paused" | "error"`, `menuError: string | null` — доступные getter; существующие `subscribe/snapshot/unlock/apply/cue/generated/duck` сохраняются.
- По умолчанию новый микшер остаётся на `scene` для существующих вызовов/тестов; App явно выставляет начальную поверхность до включения звука.

- [ ] **1. Добавить тесты переходов и отказов.** `menu_is_independent_of_scene_preferences`, `cabinet_navigation_keeps_position`, `scene_audio_off_means_silence`, `hidden_menu_pauses_at_saved_position`, `stale_load_never_starts`, `autoplay_retry_keeps_target`, `clear_scene_keeps_unlock_and_menu`, `stop_disposes_everything`:

```ts
// При menu и prefs {enabled:true,volume:0.2} gain меню=0.2 даже при scene master=0/muted=true.
// menu→menu: play/prepare не вызываются повторно; menu→scene: fade=0.5, offset сцены от сервера.
// scene→menu: прежняя позиция меню, fade=0.5; disabled/volume=0/hidden: отмена fetch, fade=0.15, pause.
// Загрузка A, surface→silent, завершение A: play не вызван; быстрые переходы не плодят элементы (ровно 2).
// Отказ prime/play и retry: цель сохранена, повтор запускает её; clearScene не закрывает контекст.
// cue/generated на menu/silent не звучат; hidden scene не выключает сцену.
```

- [ ] **2. Красная фаза.** Из `web/`: `npm.cmd test -- src/game/sound.playback.test.ts src/game/music.test.ts` — новые тесты FAIL.
- [ ] **3. Реализовать интерфейсы и выбор единственной актуальной цели.** Хранить scene snapshot отдельно от menu track/preferences/offset. У меню отдельный gain, подключённый независимо от игрового master; исключить серверный clock skew из позиции меню. Все async старты проверяют поколение цели/context и account teardown. Смена surface не создаёт новый AudioContext и сохраняет primed decks. Полный teardown только через stop.
- [ ] **4. Зелёная фаза.** `npm.cmd test -- src/game/sound.playback.test.ts src/game/music.test.ts src/game/sound.test.ts`; все старые scene/SFX/duck проверки остаются зелёными. Добавить точные утверждения fade 0.5/0.15/3.5 и освобождения object URL/таймеров.
- [ ] **5. Коммит:** `feat(audio): coordinate menu and scene playback`.

### Task 3: Состояние аккаунта и координатор App

**Files:** Create `web/src/audio/menuMusicPreferences.ts`, `menuMusicPreferences.test.ts`, `applicationAudio.ts`, `applicationAudio.test.ts`, `ApplicationAudio.tsx`.
Modify `web/src/stores/session.ts`, `web/src/App.tsx`, `web/src/lib/useGameSocket.ts`, `web/src/lib/socket.test.ts` при необходимости, `web/src/lib/types.ts`.

**Interfaces:**
- `MenuMusicPreferences = { enabled: boolean; volume: number }`, `MenuMusicSaveState = "saved" | "saving" | "error"`.
- `useMenuMusicPreferences` Zustand store: `userId`, `prefs`, `saveState`, `bindUser(user: User | null): void`, `update(patch: Partial<MenuMusicPreferences>): void`, `retry(): void`; bind другого/null аккаунта инвалидирует pending ответы/таймеры.
- `audioSurfaceFor(pathname: string, signedIn: boolean): AudioSurface` — точный route allowlist из Global Constraints.
- `ApplicationAudio` — компонент без UI, один экземпляр внутри BrowserRouter; использует Task 2 методы и query `GET /api/menu-music` с ключом пользователя.

- [ ] **1. Написать тесты.** Route matrix проверяет каждую разрешённую страницу, `/c/id`, `/admin`, `/invite/t`, unknown и anonymous. Fake timers проверяют `update(volume=.4)→.6→.8` до 250 ms: один PATCH `.8`; новое изменение при pending PATCH отправляется после него, старый ответ не откатывает prefs. Ошибка → `error`, локальный выбор сохранён, retry отправляет последнее значение. Logout/account switch во время fetch/PATCH не применяет результат; прямой вход в `/c/id` никогда не запускает меню.
- [ ] **2. Красная фаза.** `npm.cmd test -- src/audio/menuMusicPreferences.test.ts src/audio/applicationAudio.test.ts` — FAIL.
- [ ] **3. Реализовать store и координатор.** Использовать UserOut из Task 1; settings синхронизировать с текущим user в session только при совпадении account generation. Update оптимистический; один writer с объединением полей, задержка 250 ms, последующий запрос ждёт предыдущий. Theme query не скачивает MP3, а отменяется при logout. Visibility listener относится к меню; route reconcile не перезапускает один и тот же трек.
- [ ] **4. Интегрировать App и socket cleanup.** При уходе из кампании вызвать `sound.clearScene()` вместо `sound.stop()`. Полный stop вызывает App при logout/unmount. Не допустить cleanup старого маршрута, который гасит новый menu target. Account/theme loading оставляет приложение тихим до достоверных настроек.
- [ ] **5. Зелёная фаза.** Task 3 tests плюс существующие socket/game/audio tests; React StrictMode mount/cleanup не дублирует visibility listeners, воспроизведение и запросы сохранения.
- [ ] **6. Коммит:** `feat(audio): persist and route application music state`.

### Task 4: Контрол меню и пользовательские настройки

**Files:** Create `web/src/audio/MenuMusicControl.tsx`, `MenuMusicControl.test.tsx`, `web/src/profile/AudioSettingsSection.tsx`, `AudioSettingsSection.test.tsx`.
Modify `web/src/components/Header.tsx`, `web/src/pages/ProfilePage.tsx`; `web/src/game/SoundControl.tsx` менять только если нужна корректная общая индикация unlock.

**Interfaces:** `MenuMusicControl(): JSX.Element | null`, `AudioSettingsSection(): JSX.Element`; оба читают store Task 3 и `sound.subscribe/snapshot/menuStatus/menuError` Task 2.

- [ ] **1. Написать UI tests.** Выключение в шапке отражается в профиле и сохраняет прежнюю volume. Slider «Громкость музыки меню» имеет min=0/max=100/step=5 и сразу меняет звук. Error save показывает «Не удалось сохранить настройки музыки» и «Повторить». Locked state имеет «Включить музыку»; click вызывает unlock прямо в обработчике, до await. Ошибка play сохраняет retry control; busy не выдаёт success. При отсутствии темы контрола воспроизведения нет, но настройки доступны.
- [ ] **2. Красная фаза.** `npm.cmd test -- src/audio/MenuMusicControl.test.tsx src/profile/AudioSettingsSection.test.tsx` — FAIL.
- [ ] **3. Реализовать UI.** Точный текст: «Звук приложения», «Музыка главного меню», «Громкость музыки меню», `Edge of the World`. Быстрый контрол в Header только на menu surface. Оба компонента используют один store; изменение enabled не означает успешное autoplay. Сохранять доступные подписи, keyboard управление и компоновку на узком экране.
- [ ] **4. Зелёная фаза.** UI tests плюс проверка мобильной ширины 360 px: доступны кнопка, slider, ошибка/retry; theme toggle и профиль не вытесняются. Проверить состояние профиля после перехода из кабинета без restart трека.
- [ ] **5. Коммит:** `feat(ui): add menu music controls and profile settings`.

### Task 5: Проверка всей поставки и документация

**Files:** Modify `docs/audio-mixer.md`, `audio/menu/README.md`; при необходимости добавить регрессионные тесты в уже созданные файлы. Не добавлять браузерные зависимости в package.json.

**Interfaces:** Все интерфейсы Tasks 1–4; новых нет.

- [ ] **1. Выполнить серверные проверки.** `.venv/Scripts/python.exe -m pytest tests/test_menu_music.py tests/test_profile.py tests/test_audio.py tests/test_contract.py -n 0 -q -p no:cacheprovider --basetemp tools/.cache/menu-final`; Ruff на изменённых Python-файлах; изолированная миграция старого пользователя; SHA-256 исходника и копии совпадают.
- [ ] **2. Выполнить клиентские проверки.** Из `web/`: `npm.cmd test`, `npm.cmd run build`; контракт актуален, typecheck/build/test PASS.
- [ ] **3. Реальное браузерное воспроизведение.** Chromium с обычной/строгой autoplay policy: click, движущаяся позиция MP3, nonzero audio signal; кабинет→профиль→игра→кабинет; hidden/visible; выключенная кампания; прямой URL игры; logout во время загрузки. При доступном Safari/WebKit повторить первый click, auto swap и retry; при недоступности честно записать, что Safari runtime не проверен.
- [ ] **4. Финальная проверка.** Review Focus покрыт тестами; `git diff --check` чист; нет лишнего изменения сцен, карт, чужих документов или настроек `tf_sound`. Независимое ревью всей поставки; существенные замечания исправлены до завершения.
- [ ] **5. Документировать поведение и закоммитить финальные исправления.** `docs(audio): document application menu theme`. Отчёт пользователю: что работает, как включить, результаты проверок и фактические ограничения браузерного прогона.

## Исполнение

План создан по прямому запросу пользователя; код и MP3 пока не изменяются. Рекомендуется последовательное
исполнение в текущей сессии (`superpowers:executing-plans`): задачи связаны общими интерфейсами микшера и аккаунта,
а в рабочей папке одновременно идёт другая разработка. Перед реализацией пользователь просматривает этот план
и выбирает исполнение в текущей сессии или с подагентами; затем исполнитель соблюдает выбранный метод.
