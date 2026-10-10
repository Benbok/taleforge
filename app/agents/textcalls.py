"""Вызовы инструментов, которые модель написала текстом, а не через function calling.

Слабые модели (техническая Gemini, локальные в LM Studio) иногда отвечают строками вида
``action: spawn_entity(template_id='monster.skeleton', cell=(15, 20))`` или списком
``* `advance_plot(node_id='n1', outcome='done')` ``. Мир от этого не меняется, а игрок видит код.
Фаза решения разбирает такие строки в настоящие вызовы, повествование вычищает их из текста.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from typing import Any

_NAME = re.compile(r"\b([a-z][a-z0-9_]*)\s*\(")
# строки, что остаются от списка вызовов: заголовок «Выполняю действия:», разделитель, пустой пункт, ограда кода
_LEFTOVER = re.compile(
    r"^\s*(?:(?:выполняю|выполняем|выполнено|выполненные|вызываю|вызовы|действия|actions?|tool[ _]?calls?)"
    r"[^:\n]{0,40}:\s*|[*_\-=]{3,}|[-*•]\s*`*\s*|`{3}[a-z_]*)\s*$",
    re.IGNORECASE,
)


def _span(text: str, start: int) -> int | None:
    """Конец вызова, открытого скобкой на ``start``: скобки считаются вне строк. None — вызов не закрыт."""
    depth, quote, i = 0, "", start
    while i < len(text):
        ch = text[i]
        if quote:
            if ch == "\\":
                i += 1
            elif ch == quote:
                quote = ""
        elif ch in "'\"":
            quote = ch
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return None


def _value(node: ast.AST) -> Any:
    v = ast.literal_eval(node)
    return _plain(v)


def _plain(v: Any) -> Any:
    # кортеж — привычка Python (cell=(15, 20)); в схемах инструментов это массив
    if isinstance(v, tuple | list):
        return [_plain(x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    return v


def _find(text: str, names: Iterable[str]) -> list[tuple[int, int, str, str]]:
    """(начало, конец, имя, исходник) каждого вызова известного инструмента в тексте."""
    known = set(names)
    out: list[tuple[int, int, str, str]] = []
    pos = 0
    while m := _NAME.search(text, pos):
        name = m.group(1)
        if name not in known:
            pos = m.end()
            continue
        end = _span(text, m.end() - 1)
        if end is None:
            pos = m.end()
            continue
        out.append((m.start(), end, name, text[m.start() : end]))
        pos = end
    return out


def _open(text: str, names: set[str]) -> bool:
    """В тексте начат, но не закрыт вызов известного инструмента (аргументы на нескольких строках)."""
    return any(m.group(1) in names and _span(text, m.end() - 1) is None for m in _NAME.finditer(text))


def parse(text: str, names: Iterable[str]) -> list[tuple[str, dict[str, Any]]]:
    """Вызовы инструментов из ``names``, записанные в тексте как ``name(key=value, …)``.
    Значения — только литералы Python или JSON; вызов с позиционными или нелитеральными аргументами пропускается."""
    calls: list[tuple[str, dict[str, Any]]] = []
    for _, _, name, src in _find(text or "", names):
        src = re.sub(r"\btrue\b", "True", re.sub(r"\bfalse\b", "False", re.sub(r"\bnull\b", "None", src)))
        try:
            node = ast.parse(src, mode="eval").body
        except SyntaxError:
            continue
        if not isinstance(node, ast.Call) or node.args or any(k.arg is None for k in node.keywords):
            continue
        try:
            args = {k.arg: _value(k.value) for k in node.keywords}
        except (ValueError, TypeError, SyntaxError):
            continue
        calls.append((name, args))
    return calls


def strip(text: str, names: Iterable[str]) -> str:
    """Убирает из текста для игроков строки с вызовами инструментов и то, что от их списка осталось."""
    found = _find(text or "", names)
    if not found:
        return text
    cut = text
    for start, end, _, _ in reversed(found):
        # строка вызова целиком: «action: …», «* `…`», «- …» вместе с префиксом
        line_start = cut.rfind("\n", 0, start) + 1
        line_end = cut.find("\n", end)
        line_end = len(cut) if line_end == -1 else line_end
        before = cut[line_start:start]
        after = cut[end:line_end]
        if re.fullmatch(r"\s*(?:[-*•]\s*)?(?:\d+[.)]\s*)?(?:[a-z_ ]{0,20}:\s*)?`*\s*", before, re.IGNORECASE) and (
            re.fullmatch(r"\s*`*\s*[;,.]?\s*", after)
        ):
            cut = cut[:line_start] + cut[line_end + 1 :]
        else:
            cut = cut[:start] + cut[end:]
    lines = [ln for ln in cut.split("\n") if not _LEFTOVER.fullmatch(ln) or not ln.strip()]
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return out


def tool_names() -> set[str]:
    """Все инструменты мастера: импорт поздний, реестр тянет за собой модели и правила."""
    import app.agents.master  # noqa: F401 — инструменты встают в реестр при импорте своих модулей
    from app.tools.registry import REGISTRY

    return set(REGISTRY)


def clean(text: str) -> str:
    """Текст для игроков без вызовов любых инструментов мастера."""
    return strip(text, tool_names())


# начало строки, которое ещё может стать вызовом или заголовком списка вызовов: такую строку держим до конца
_MAYBE = re.compile(
    r"\s*(?:[-*•]\s*)?(?:\d+[.)]\s*)?(?:[a-z_ ]{0,20}:\s*)?`*\s*[a-z0-9_]*\s*"
    r"|\s*(?:[*_\-=`]{1,})\s*",
    re.IGNORECASE,
)
_HEADS = ("выполн", "вызов", "вызыв", "действ", "action", "tool")


def _maybe(line: str) -> bool:
    """Недописанная строка ещё может оказаться вызовом или заголовком списка вызовов."""
    low = line.lstrip().lower()
    return bool(_MAYBE.fullmatch(line)) or any(h.startswith(low) or low.startswith(h) for h in _HEADS)


class StreamFilter:
    """Поток повествования без строк с вызовами инструментов: обычный текст идёт сразу, строка, похожая на вызов
    или заголовок их списка, — только когда ясно, что это не вызов. Хвост в конце не нужен: финальный текст
    сообщения всё равно заменит черновик."""

    def __init__(self, push, names: Iterable[str] | None = None) -> None:
        self.push = push
        self.names = set(names) if names is not None else tool_names()
        self.line = ""  # недописанная строка, которую держим
        self.passing = False  # текущая строка уже признана текстом и идёт сразу
        self.held = ""  # заголовок вроде «Выполняю действия:» — ждёт, что за ним

    async def __call__(self, chunk: str) -> None:
        for part in re.split(r"(\n)", chunk):
            if not part:
                continue
            if self.passing:
                await self.push(part)
                if part == "\n":
                    self.passing = False
                continue
            self.line += part
            if part == "\n" and not _open(self.line, self.names):
                await self._decide(self.line)
                self.line = ""
            elif not _maybe(self.line) and not _open(self.line, self.names) and not _find(self.line, self.names):
                await self._flush(self.line)
                self.line, self.passing = "", True

    async def _decide(self, line: str) -> None:
        body = line.rstrip("\n")
        if _find(body, self.names):
            rest = strip(body, self.names)
            self.held = ""
            if rest.strip():
                await self.push(rest + "\n")
            return
        if body.strip() and _LEFTOVER.fullmatch(body):
            self.held += line
            return
        await self._flush(line)

    async def _flush(self, text: str) -> None:
        if self.held:
            text, self.held = self.held + text, ""
        await self.push(text)
