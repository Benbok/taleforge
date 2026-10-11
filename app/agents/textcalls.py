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


# JSON-форма вызова: имя инструмента — значение одного из этих ключей, аргументы — объект под другим
_CALL_KEYS = ("call", "tool", "tool_name", "function", "name")
_ARG_KEYS = ("args", "arguments", "parameters", "params", "input")
_JSON_NAME = re.compile(r'"(?:' + "|".join(_CALL_KEYS) + r')"\s*:\s*"([a-z][a-z0-9_]*)"')
_FENCE = re.compile(r"```[\w-]*[ \t]*\n?(.*?)```", re.S)
# JSON с начала строки: «[» или «{», но не разметка сущности «[[id|текст]]»
_JSON_START = re.compile(r"^[ \t]*(?:[-*•][ \t]*)?(\{|\[(?!\[))", re.M)


def _json_calls(obj: Any, known: set[str]) -> list[tuple[str, dict[str, Any]]]:
    if isinstance(obj, list):
        return [c for x in obj for c in _json_calls(x, known)]
    if not isinstance(obj, dict):
        return []
    for key in _CALL_KEYS:
        v = obj.get(key)
        if isinstance(v, dict):  # {"function": {"name": …, "arguments": …}} — форма OpenAI
            return _json_calls(v, known)
        if isinstance(v, str) and v in known:
            args = next((obj[k] for k in _ARG_KEYS if k in obj), {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = {}
            return [(v, args if isinstance(args, dict) else {})]
    return []


def _json_blocks(text: str, known: set[str]) -> list[tuple[int, int, list[tuple[str, dict[str, Any]]]]]:
    """(начало, конец, вызовы) каждого JSON-блока с вызовом известного инструмента: ограда кода или скобка
    с начала строки. Блок с битым JSON всё равно технический текст — вызовы тогда пусты."""
    out: list[tuple[int, int, list[tuple[str, dict[str, Any]]]]] = []

    def take(start: int, end: int, body: str) -> None:
        if not any(m.group(1) in known for m in _JSON_NAME.finditer(body)):
            return
        try:
            calls = _json_calls(json.loads(body), known)
        except ValueError:
            calls = []
        out.append((start, end, calls))

    fences = [(m.start(), m.end()) for m in _FENCE.finditer(text)]
    for m in _FENCE.finditer(text):
        take(m.start(), m.end(), m.group(1).strip())
    for m in _JSON_START.finditer(text):
        start = m.start(1)
        if any(s <= start < e for s, e in fences) or any(s <= start < e for s, e, _ in out):
            continue
        end = _span(text, start)
        if end is not None:
            take(start, end, text[start:end])
    return sorted(out)


def _json_open(text: str, known: set[str] | None = None) -> int | None:
    """Начало незакрытого JSON-блока (ограды или скобки с начала строки). С ``known`` — только если в нём
    уже видно имя известного инструмента; без него — любой: поток держит блок, пока не поймёт, что в нём."""
    fences = [m.start() for m in re.finditer(r"```", text)]
    starts = [fences[-1]] if len(fences) % 2 else []
    closed = [(m.start(), m.end()) for m in _FENCE.finditer(text)]
    for m in _JSON_START.finditer(text):
        s = m.start(1)
        if not any(a <= s < b for a, b in closed) and _span(text, s) is None:
            starts.append(s)
            break
    for s in sorted(starts):
        if known is None or any(x.group(1) in known for x in _JSON_NAME.finditer(text, s)):
            return s
    return None


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
    known = set(names)
    blocks = _json_blocks(text or "", known)
    found: list[tuple[int, tuple[str, dict[str, Any]]]] = [(s, c) for s, _, cs in blocks for c in cs]
    for start, _, name, src in _find(text or "", known):
        if any(s <= start < e for s, e, _ in blocks):
            continue  # строка внутри JSON-аргумента — не отдельный вызов
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
        found.append((start, (name, args)))
    return [c for _, c in sorted(found, key=lambda x: x[0])]


def strip(text: str, names: Iterable[str]) -> str:
    """Убирает из текста для игроков строки с вызовами инструментов и то, что от их списка осталось."""
    known = set(names)
    cut = text or ""
    blocks = _json_blocks(cut, known)
    for start, end, _ in reversed(blocks):
        # блок, занявший строки целиком, уходит вместе с ними
        line_start = cut.rfind("\n", 0, start) + 1
        line_end = cut.find("\n", end)
        line_end = len(cut) if line_end == -1 else line_end
        if re.fullmatch(r"[ \t]*(?:[-*•][ \t]*)?", cut[line_start:start]) and not cut[end:line_end].strip():
            start, end = line_start, min(line_end + 1, len(cut))
        cut = cut[:start] + cut[end:]
    if (pending := _json_open(cut, known)) is not None:
        cut = cut[:pending]  # оборванный JSON-вызов не публикуется
    found = _find(cut, known)
    if not blocks and pending is None and not found and not _open(cut, known):
        return text
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
    text = text or ""
    if _find(text, known) or _json_blocks(text, known):
        return True
    return _open(text, known) or _json_open(text, known) is not None


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
            # Многострочный вызов удерживается до закрывающей скобки, JSON-блок — пока не закроется:
            # имя инструмента в нём может прийти позже первой строки.
            boundary = next(
                (
                    i + 1
                    for i, char in enumerate(self.pending)
                    if char == "\n"
                    and not _open(self.pending[: i + 1], self.names)
                    and _json_open(self.pending[: i + 1]) is None
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
