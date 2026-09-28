"""Ошибки проверки запросов — по-русски и одной строкой, чтобы клиент показал их человеку как есть."""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

FIELDS = {
    "name": "Имя",
    "password": "Пароль",
    "text": "Текст",
    "comment": "Комментарий",
    "players": "Число игроков",
    "public_bio": "Внешность и история",
    "private_backstory": "Тайная предыстория",
    "new_password": "Новый пароль",
    "api_base": "Адрес сервера",
    "model": "Модель",
    "temperature": "Температура",
}


def _field(loc: tuple[Any, ...]) -> str:
    parts = [str(x) for x in loc if x not in ("body", "query", "path")]
    if not parts:
        return "Запрос"
    return FIELDS.get(parts[-1], ".".join(parts))


def describe(err: dict[str, Any]) -> str:
    ctx = err.get("ctx") or {}
    t = err.get("type", "")
    what = {
        "missing": "нужно заполнить",
        "string_too_short": f"не короче {ctx.get('min_length')} символов",
        "string_too_long": f"не длиннее {ctx.get('max_length')} символов",
        "string_pattern_mismatch": "адрес вида http://host:port/v1"
        if ctx.get("pattern", "").startswith("^https?")
        else "только буквы, цифры, пробел, точка, дефис и подчёркивание",
        "greater_than_equal": f"не меньше {ctx.get('ge')}",
        "less_than_equal": f"не больше {ctx.get('le')}",
        "literal_error": f"одно из: {ctx.get('expected')}",
        "int_parsing": "нужно целое число",
        "string_type": "нужна строка",
    }.get(t, err.get("msg", "неверное значение"))
    return f"{_field(tuple(err.get('loc') or ()))}: {what}"


async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    return JSONResponse(
        {"detail": "; ".join(describe(e) for e in errors), "errors": [describe(e) for e in errors]},
        status_code=422,
    )
