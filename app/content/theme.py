"""Тема интерфейса из пакета сеттинга (документ «Дизайн фронтенда», раздел о стиле).

Пакет меняет вид, а не устройство: палитру тёмной и светлой темы, шрифты и подписи. Раскладка, виджеты и цвета
успеха, провала и предупреждения одинаковы для любого мира, поэтому их в теме пакета нет. Тема пакета
накладывается поверх базовой (``DEFAULT``) по цепочке пакетов кампании: база правил, потом мир.
Импорт отклоняет нечитаемую тему: контраст текста и фона ниже 4.5:1.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MIN_CONTRAST = 4.5

# токены цвета, которые пакет может переопределить
COLORS = (
    "bg",
    "surface",
    "raised",
    "border",
    "text",
    "muted",
    "accent",
    "accent_text",
    "entity_creature",
    "entity_npc",
    "entity_item",
    "entity_location",
    "entity_lore",
)
# пары «текст на фоне», которые обязаны читаться
READABLE = (("text", "bg"), ("text", "surface"), ("text", "raised"), ("muted", "bg"), ("accent_text", "accent"))

DEFAULT: dict[str, Any] = {
    "dark": {
        "bg": "#14161a",
        "surface": "#1c1f25",
        "raised": "#252932",
        "border": "#343a45",
        "text": "#e8e4dc",
        "muted": "#a19c93",
        "accent": "#c9954d",
        "accent_text": "#14161a",
        "entity_creature": "#e06c5f",
        "entity_npc": "#6ea8e0",
        "entity_item": "#d9b44a",
        "entity_location": "#6fbf86",
        "entity_lore": "#9a9fa8",
    },
    "light": {
        "bg": "#f6f3ee",
        "surface": "#ffffff",
        "raised": "#efebe4",
        "border": "#d8d2c7",
        "text": "#1f2127",
        "muted": "#5e5a53",
        "accent": "#8a5a1c",
        "accent_text": "#ffffff",
        "entity_creature": "#b3372b",
        "entity_npc": "#2b64a3",
        "entity_item": "#8a6a10",
        "entity_location": "#2f7d49",
        "entity_lore": "#5f646d",
    },
    "fonts": {
        "narration": "'Literata', Georgia, serif",
        "ui": "'Inter', system-ui, sans-serif",
        "heading": "'Literata', Georgia, serif",
    },
    "font_css": "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Literata:ital,wght@0,400;0,600;1,400&display=swap",
    "labels": {
        "master_status.listening": "Мастер слушает…",
        "master_status.remembering": "Мастер вспоминает…",
        "master_status.rolling": "Мастер бросает кубики…",
        "master_status.describing": "Мастер описывает…",
    },
}


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bg: str | None = None
    surface: str | None = None
    raised: str | None = None
    border: str | None = None
    text: str | None = None
    muted: str | None = None
    accent: str | None = None
    accent_text: str | None = None
    entity_creature: str | None = None
    entity_npc: str | None = None
    entity_item: str | None = None
    entity_location: str | None = None
    entity_lore: str | None = None

    @field_validator("*")
    @classmethod
    def _color(cls, v: str | None) -> str | None:
        if v is not None and not COLOR.match(v):
            raise ValueError(f"цвет темы должен быть вида #rrggbb, получено {v!r}")
        return v


class Fonts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    narration: str | None = Field(None, max_length=200)
    ui: str | None = Field(None, max_length=200)
    heading: str | None = Field(None, max_length=200)


class Theme(BaseModel):
    """``theme`` в pack.yaml. Всё необязательно: чего нет, берётся из базовой темы."""

    model_config = ConfigDict(extra="forbid")

    dark: Palette | None = None
    light: Palette | None = None
    fonts: Fonts | None = None
    font_css: str | None = Field(None, description="таблица стилей шрифтов, только Google Fonts")
    labels: dict[str, str] = Field(default_factory=dict)

    @field_validator("font_css")
    @classmethod
    def _font_css(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://fonts.googleapis.com/"):
            raise ValueError("шрифты темы подключаются только с https://fonts.googleapis.com/")
        return v

    @field_validator("labels")
    @classmethod
    def _labels(cls, v: dict[str, str]) -> dict[str, str]:
        for k, text in v.items():
            if len(k) > 64 or len(str(text)) > 120:
                raise ValueError(f"подпись темы {k!r} слишком длинная")
        return v

    @model_validator(mode="after")
    def _readable(self) -> Theme:
        problems = contrast_problems(merge([self.model_dump(exclude_none=True)]))
        if problems:
            raise ValueError("тема нечитаема: " + "; ".join(problems))
        return self


def _channel(c: int) -> float:
    s = c / 255
    return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4


def luminance(color: str) -> float:
    r, g, b = (int(color[i : i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def contrast(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_problems(theme: dict[str, Any]) -> list[str]:
    out = []
    for mode in ("dark", "light"):
        pal = theme[mode]
        for fg, bg in READABLE:
            ratio = contrast(pal[fg], pal[bg])
            if ratio < MIN_CONTRAST:
                out.append(f"{mode}: {fg} на {bg} — контраст {ratio:.2f}, нужно не ниже {MIN_CONTRAST}")
    return out


def merge(layers: list[dict[str, Any]]) -> dict[str, Any]:
    """Базовая тема и слои пакетов по порядку: следующий слой перекрывает предыдущий по отдельным ключам."""
    out = copy.deepcopy(DEFAULT)
    for layer in layers:
        for key in ("dark", "light", "fonts", "labels"):
            out[key].update({k: v for k, v in (layer.get(key) or {}).items() if v is not None})
        if layer.get("font_css"):
            out["font_css"] = layer["font_css"]
    return out
