"""Ссылки в тексте мастера (просьба Arty, этап 7): имена героев, NPC и мест кликабельны всегда, а не только когда
модель не забыла разметку ``[[id|текст]]``.

После ответа мастера сервер сам находит в тексте известные имена, в том числе в других падежах («деревню
Туманный Ручей», «Ивана»), и размечает их. Жирный шрифт модели (``**Иван**``) снимается: выделение имени —
это ссылка. Ссылки ставятся только на тех, кого игрокам уже можно показать: героев отряда, текущее место,
сущности сцены и тех, о ком хоть один герой что-то знает. Имя, общее для двух сущностей, не размечается.
"""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Character, Entity, Knowledge, Scene

MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
BOLD = re.compile(r"\*\*(.+?)\*\*|__(.+?)__", re.S)
WORD = re.compile(r"[\w-]+")
LETTERS = "а-яёa-z"
LINKABLE_HEROES = ("approved", "active", "dead")


def _stem(token: str) -> str:
    """Основа слова для русских падежей: «Ручей» → «Руч», «Иван» → «Иван»."""
    t = token.lower()
    if len(t) <= 4:
        return re.escape(t)
    cut = 2 if len(t) > 6 else 1
    return re.escape(t[:-cut])


def _pattern(alias: str) -> str:
    words = alias.split()
    parts = [_stem(w) + f"[{LETTERS}]{{0,3}}" for w in words]
    return r"(?<![\w-])" + r"\s+".join(parts) + r"(?![\w-])"


ADJ_ENDINGS = ("ый", "ий", "ой", "ая", "яя", "ое", "ее", "ые", "ие")


def _aliases(name: str) -> list[tuple[str, bool]]:
    """Варианты имени и нужна ли заглавная буква в тексте. Полное имя и хвосты из слов с заглавной («Туманный
    Ручей» у «Деревня Туманный Ручей») — в любом регистре; одиночное слово из длинного имени («Иван» у «Иван
    Петров») — только с заглавной, чтобы «тёмный» не стал ссылкой на «Тёмный лес»; голова составного имени
    («гоблин» у «Гоблин-разведчик») — в любом регистре."""
    words = name.split()
    out: list[tuple[str, bool]] = [(name, False)]
    for i in range(1, len(words)):
        if words[i][:1].isupper() and len(words) - i >= 2:
            out.append((" ".join(words[i:]), False))
    seen = {a.lower() for a, _ in out}
    for w in words:
        head = w.split("-")[0]
        for x, strict in ((w, len(words) > 1), (head, len(words) > 1 and head == w)):
            if len(x) < 4 or not x[:1].isupper() or x.lower() in seen:
                continue
            if len(words) > 1 and x.lower().endswith(ADJ_ENDINGS):
                continue  # прилагательное из названия само по себе не имя
            seen.add(x.lower())
            out.append((x, strict))
    return out


def autolink(text: str, names: dict[str, str]) -> str:
    """Размечает известные имена в тексте. ``names``: id → имя. Готовая разметка не трогается."""
    if not text:
        return text
    owners: dict[str, set[str]] = {}
    strict_of: dict[str, bool] = {}
    for eid, name in names.items():
        if name and name.strip():
            for a, strict in _aliases(name.strip()):
                owners.setdefault(a.lower(), set()).add(eid)
                strict_of[a.lower()] = strict_of.get(a.lower(), True) and strict
    aliases = sorted(((a, next(iter(ids))) for a, ids in owners.items() if len(ids) == 1), key=lambda x: -len(x[0]))
    compiled = [(re.compile(_pattern(a), re.I), eid, strict_of[a]) for a, eid in aliases]

    def link_plain(chunk: str) -> str:
        if not compiled:
            return chunk
        spans: list[tuple[int, int, str]] = []
        for rx, eid, strict in compiled:
            for m in rx.finditer(chunk):
                if strict and not m.group(0)[:1].isupper():
                    continue
                if any(m.start() < e and s < m.end() for s, e, _ in spans):
                    continue  # внутри уже найденного длинного имени
                spans.append((m.start(), m.end(), eid))
        out, pos = [], 0
        for s, e, eid in sorted(spans):
            out.append(chunk[pos:s])
            out.append(f"[[{eid}|{chunk[s:e]}]]")
            pos = e
        out.append(chunk[pos:])
        return "".join(out)

    # жирный шрифт модели снимаем: выделение имени — ссылка, прочее выделение в чате не нужно
    text = BOLD.sub(lambda m: m.group(1) or m.group(2) or "", text)
    out, pos = [], 0
    for m in MARKUP.finditer(text):
        out.append(link_plain(text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(link_plain(text[pos:]))
    return "".join(out)


async def linkable(session: AsyncSession, campaign_id: str) -> dict[str, str]:
    """Кого можно размечать: герои отряда, текущее место и его сущности, всё, о чём знает хоть один герой."""
    names: dict[str, str] = {}
    q = select(Character).where(Character.campaign_id == campaign_id, Character.status.in_(LINKABLE_HEROES))
    heroes = (await session.scalars(q)).all()
    for ch in heroes:
        names[ch.id] = ch.name
    scene = await session.get(Scene, campaign_id)
    # места, где стоят герои: разделившийся отряд стоит в нескольких
    spots = {ch.location_id or (scene.location_id if scene else None) for ch in heroes} - {None}
    if scene is not None and scene.location_id:
        spots.add(scene.location_id)
    known = select(Knowledge.entity_id).join(Character, Character.id == Knowledge.character_id)
    known = known.where(Character.campaign_id == campaign_id)
    q = select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind != "object")
    rows = (await session.scalars(q)).all()
    known_ids = set((await session.scalars(known)).all())
    for e in rows:
        here = e.id in spots or e.location_id in spots
        if (here or e.id in known_ids) and not (e.state or {}).get("fled"):
            names[e.id] = e.name
    return names


async def link_text(session: AsyncSession, campaign_id: str, text: str) -> str:
    return autolink(text, await linkable(session, campaign_id))
