FROM python:3.12-slim

WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic
COPY content ./content

EXPOSE 8000
# Миграции при каждом старте: на свежей базе создают схему, на старой — доводят до текущей версии.
CMD ["sh", "-c", "alembic upgrade head && python -m app.content import content/dnd5e-srd && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
