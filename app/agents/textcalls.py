"""Вызовы инструментов, которые модель написала текстом, а не через function calling.

Модели иногда выводят имитации вызовов вместо структурированных tool_calls.
Разбор используется для обнаружения и удаления технического текста, но не даёт разрешение на исполнение.
Поддерживаются также markdown-формы ``[spawn_entity](...)`` и JSON — ``{"call": "add_landmark", "args": {…}}``,
списком или одним объектом, в ограде ```json или без неё.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterable
from typing import Any

_NAME = re.compile(r"(?<![\w])(?:\\?\[\s*)?([a-z][a-z0-9_]*)(?:\s*\\?\])?\s*\\?\(")
_CALL_KEYS = ("call", "tool", "tool_name", "function", "name")
_ARG_KEYS = ("args", "arguments", "parameters", "params", "input")
_JSON_CALL = re.compile(r'"(?:' + "|".join(_CALL_KEYS) + r')"\s*:\s*"([^"\\]*)"')
_JSON_PARTIAL = re.compile(r'"(?:' + "|".join(_CALL_KEYS) + r')"\s*:\s*"?([^"\\]*)$')
# строки, что остаются от списка вызовов: заголовок «Выполняю действия:», разделитель, пустой пункт, ограда кода
_LEFTOVER = re.compile(
    r"^\s*(?:(?:выполняю|выполняем|выполнено|выполненные|вызываю|вызовы|действия|actions?|tool[ _]?calls?)"
    r"[^:\n]{0,40}:\s*|[*_\-=]{3,}|[-*•]\s*`*\s*|(?:\\?`){3}[a-z_]*)\s*$",
    re.IGNORECASE,
)


def _json_containers(text: str) -> list[tuple[int, int, bool]]:
    """Outer JSON-like containers, including an unfinished tail; no evaluation."""
    out = []
    start, depth, quoted, escaped = 0, 0, False, False
    for i, char in enumerate(text):
        if not depth:
            if char in "[{":
                start, depth = i, 1
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
            if not depth:
                out.append((start, i + 1, True))
    if depth:
        out.append((start, len(text), False))
    return out


def _json_find(text: str, names: set[str]) -> list[tuple[int, int, str]]:
    found = []
    for start, end, closed in _json_containers(text):
        source = text[start:end]
        try:
            value = json.loads(source)
        except ValueError:
            known = any(m.group(1) in names for m in _JSON_CALL.finditer(source))
        else:
            known = any(
                any(isinstance(entry.get(key), str) and entry[key] in names for key in _CALL_KEYS)
                and (any(key in entry for key in _CALL_KEYS[:-1]) or any(key in entry for key in _ARG_KEYS))
                for entry in _json_entries(value)
            )
        partial = _JSON_PARTIAL.search(source) if not closed else None
        if known or (partial and any(n.startswith(partial.group(1)) for n in names)):
            found.append((start, end, source))
    return found


def _json_entries(value: Any) -> list[dict]:
    if isinstance(value, dict) and isinstance(value.get("tool_calls"), list):
        value = value["tool_calls"]
    entries = value if isinstance(value, list) else [value]
    return [
        {"tool_name": entry["function"].get("name"), **entry["function"]}
        if isinstance(entry.get("function"), dict)
        else entry
        for entry in entries
        if isinstance(entry, dict)
    ]


def stream_prefix(text: str) -> str:
    """Withhold unfinished containers before their tool discriminator is known."""
    pending = [start for start, _, closed in _json_containers(text) if not closed]
    return text[: min(pending)] if pending else text


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
    """Вызовы инструментов из ``names``, записанные в тексте как ``name(key=value, …)`` или JSON-блоком.
    Значения — только литералы Python или JSON; вызов с позиционными или нелитеральными аргументами пропускается."""
    names = set(names)
    calls: list[tuple[int, str, dict[str, Any]]] = []
    json_spans = _json_find(text or "", names)
    for start, _, name, src in _find(text or "", names):
        if any(a <= start < b for a, b, _ in json_spans):
            continue
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
        calls.append((start, name, args))
    for start, _, src in json_spans:
        try:
            value = json.loads(src)
        except ValueError:
            continue  # damaged commands are still removed, never repaired or executed
        for entry in _json_entries(value):
            name = next(
                (entry[key] for key in _CALL_KEYS if isinstance(entry.get(key), str) and entry[key] in names), None
            )
            args = next((entry[key] for key in _ARG_KEYS if key in entry), {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    continue
            if isinstance(name, str) and name in names and isinstance(args, dict):
                calls.append((start, name, args))
    return [(name, args) for _, name, args in sorted(calls, key=lambda c: c[0])]


def strip(text: str, names: Iterable[str]) -> str:
    """Убирает из текста для игроков строки с вызовами инструментов и то, что от их списка осталось."""
    known = set(names)
    json_spans = _json_find(text or "", known)
    if not json_spans and not _find(text or "", known) and not _open(text or "", known):
        return text
    cut = text or ""
    for start, end, _ in reversed(json_spans):
        line_start = cut.rfind("\n", 0, start) + 1
        line_end = cut.find("\n", end)
        line_end = len(cut) if line_end == -1 else line_end
        if re.fullmatch(r"\s*(?:[-*•]\s*)?", cut[line_start:start]) and not cut[end:line_end].strip():
            cut = cut[:line_start] + cut[line_end + 1 :]
        else:
            cut = cut[:start] + cut[end:]
    cut = re.sub(r"(?:\\?`){3}(?:json)?\s*(?:\\?`){3}", "", cut, flags=re.IGNORECASE)
    found = _find(cut, known)
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
    return bool(_find(text or "", known) or _json_find(text or "", known)) or _open(text or "", known)


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
                    if char == "\n"
                    and not _open(self.pending[: i + 1], self.names)
                    and not any(not closed for _, _, closed in _json_containers(self.pending[: i + 1]))
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

    async def finish(self) -> None:
        """Выпустить проверенный хвост после завершения потока (текст без перевода строки)."""
        safe = strip(self.pending, self.names)
        self.pending = ""
        if safe.strip() and safe.strip().lower().strip("\\") not in ("<center>", "</center>"):
            await self.push(safe)
