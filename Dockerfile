# Сборка веб-клиента (web/, React). Готовые файлы кладутся в app/web/dist, их раздаёт FastAPI.
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build -- --outDir /dist

FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# pdftotext — текст книг готовых приключений (app/core/modules.py)
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
# Cache runtime dependencies independently from application source changes.
RUN --mount=type=cache,target=/root/.cache/pip python -c "import subprocess,tomllib; subprocess.check_call(['pip','install',*tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']])"
COPY app ./app
COPY --from=web /dist ./app/web/dist
RUN --mount=type=cache,target=/root/.cache/pip pip install --no-deps .

COPY alembic.ini ./
COPY alembic ./alembic
COPY content ./content

EXPOSE 8000
# Миграции при каждом старте: на свежей базе создают схему, на старой — доводят до текущей версии.
CMD ["sh", "-c", "alembic upgrade head && python -m app.content import content/dnd5e-srd && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
