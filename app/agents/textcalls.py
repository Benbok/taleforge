"""Вызовы инструментов, которые модель написала текстом, а не через function calling.

Модели иногда выводят имитации вызовов вместо структурированных tool_calls.
Разбор используется для обнаружения и удаления технического текста, но не даёт разрешение на исполнение.
Поддерживаются также markdown-формы ``[spawn_entity](...)``.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable
from typing import Any

_NAME = re.compile(r"(?<![\w])(?:\\?\[\s*)?([a-z][a-z0-9_]*)(?:\s*\\?\])?\s*\\?\(")
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
        out.append((m.start(), end, name, name + text[m.end() - 1 : end]))
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
    known = set(names)
    found = _find(text or "", known)
    if not found and not _open(text or "", known):
        return text
    cut = text or ""
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
    # Незакрытый вызов не может быть опубликован даже при обрыве ответа модели.
    pending = [m.start() for m in _NAME.finditer(cut) if m.group(1) in known and _span(cut, m.end() - 1) is None]
    if pending:
        cut = cut[: min(pending)]
    cut = re.sub(r"\\?</?center(?:\s[^>]*)?>\\?", "", cut, flags=re.IGNORECASE)
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


def contains(text: str, names: Iterable[str]) -> bool:
    """Есть ли в тексте попытка вызвать инструмент, включая незавершённый вызов."""
    known = set(names)
    return bool(_find(text or "", known)) or _open(text or "", known)


class StreamFilter:
    """Строковый барьер для публичного потока повествования.

    До завершения строки и проверки её содержимого она не попадает игрокам.
    Незавершённый вызов удерживается, даже если аргументы занимают несколько строк.
    Неполный хвост не публикуется: после коммита его заменит проверенный финальный текст.
    """

    def __init__(self, push, names: Iterable[str] | None = None) -> None:
        self.push = push
        self.names = set(names) if names is not None else tool_names()
        self.pending = ""

    async def __call__(self, chunk: str) -> None:
        self.pending += chunk
        while True:
            # Многострочный вызов удерживается до закрывающей скобки.
            boundary = next(
                (
                    i + 1
                    for i, char in enumerate(self.pending)
                    if char == "\n" and not _open(self.pending[: i + 1], self.names)
                ),
                None,
            )
            if boundary is None:
                return
            line, self.pending = self.pending[:boundary], self.pending[boundary:]
            if line.strip().lower().strip("\\") in ("<center>", "</center>") or _LEFTOVER.fullmatch(line.rstrip("\n")):
                continue
            safe = strip(line, self.names)
            if safe.strip():
                await self.push(safe + ("\n" if line.endswith("\n") and not safe.endswith("\n") else ""))
