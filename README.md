# Taleforge

Текстовая ролевая игра с ИИ-мастером по правилам D&D 5e (SRD 5.1).

ИИ — голос, приложение — мир: вся механика, числа и состояние живут в коде и данных, модель только описывает и вызывает инструменты.

Техническое задание — документ «ТЗ: AI-Мастер для текстовых ролевых игр» в проекте.

## Структура

```
app/
  rules/          # движок правил: интерфейс RulesEngine, кубики
    dnd5e/        # реализация по SRD 5.1
  content/        # загрузка и проверка пакетов контента, ядровая схема
  core/           # кампании, места, приглашения, чат и сеансы
  api/            # REST: вход, кампании, приглашения, админка
  gateway/        # WebSocket-шлюз и доставка событий (память или Redis)
  db/             # модели SQLAlchemy; схема меняется миграциями alembic/
  web/static/     # временный веб-клиент для проверки каркаса
  tools/ agents/  # следующие этапы
content/
  dnd5e-srd/      # базовый пакет правил (SRD 5.1, CC BY 4.0)
tests/
```

Пакеты сеттинга лежат рядом с базовым в `content/<id>/` и подключают его через `ruleset_base: srd-5.1`.

## Запуск

Игра на своей машине:

```
cp .env.example .env          # задайте SUPERADMIN_*, JWT_SECRET
docker compose up --build     # http://localhost:8000
docker compose --profile tunnel up --build   # то же + публичная ссылка cloudflared (адрес в логах tunnel)
```

С туннелем пропишите его адрес в `PUBLIC_URL`, чтобы ссылки-приглашения вели наружу, и перезапустите `app`.
Первый вход — под Super Admin из `.env`; он заводит админов (`POST /api/admin/users`), админы создают кампании и приглашения.
При старте сервер применяет миграции и импортирует базовый пакет SRD. Свой мир положите в `content/<id>/` и импортируйте:

```
docker compose exec app python -m app.content import content/<id>
```

Разработка:

```
pip install -e ".[dev]"
pytest                                            # SQLite; TEST_DATABASE_URL=postgresql+asyncpg://… — на PostgreSQL
uvicorn app.main:app --reload                     # DATABASE_URL по умолчанию — SQLite-файл
alembic upgrade head                              # схема БД (DATABASE_URL)
python -m app.content validate путь/к/пакету --customs
```

API описан в `/docs` (OpenAPI). Протокол WebSocket — ТЗ, раздел 12: `auth` → `campaign.join` → `state.snapshot` → `message.send`.

## Лицензия SRD

This work includes material taken from the System Reference Document 5.1 ("SRD 5.1") by Wizards of the Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is licensed under the Creative Commons Attribution 4.0 International License available at https://creativecommons.org/licenses/by/4.0/legalcode.
