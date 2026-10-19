"""Проверки согласованности именованных участников повествования с реестром сцены."""

from __future__ import annotations

import re

_SPEAKS = re.compile(
    r"\b(?:отвечает|говорит|спрашивает|произносит|шепчет|добавляет|восклицает|бурчит|"
    r"сказал[аи]?|ответил[аи]?|спросил[аи]?|прошептал[аи]?)\b",
    re.IGNORECASE,
)


_CONSUMES = re.compile(
    r"(?<!\w)(?:съе[лдс]\w*|проглат\w*|проглот\w*|выпи(?:л|ва)\w*|отправ(?:ля|ил)\w*\s+в\s+рот|жуёт|жует|"
    r"прожёвыва\w+)",
    re.IGNORECASE,
)
_ITEM_USE_TOOLS = {"use_item", "pass_item", "give_item"}


def unconfirmed_item_use(text: str, item_names, attempts) -> list[str]:
    """Предложения, где съедают или выпивают предмет из снаряжения героев без успешного use_item в этом ходе.

    Описывать употребление можно только после результата инструмента: без него эффект не записан в мир,
    а игрок решит, что стражник вылечен. Проверка узкая: нужны и слово употребления, и название предмета."""
    if any(a.get("tool") in _ITEM_USE_TOOLS and (a.get("result") or {}).get("ok") for a in attempts or []):
        return []
    stems = {w[:-1] if len(w) > 4 else w for name in item_names for w in re.findall(r"\w{4,}", str(name).casefold())}
    if not stems:
        return []
    plain = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", text)
    out = []
    for sentence in re.split(r"(?<=[.!?…])\s+", plain):
        low = sentence.casefold()
        if _CONSUMES.search(low) and any(re.search(r"(?<!\w)" + re.escape(s), low) for s in stems):
            out.append(sentence.strip())
    return out


def invented_player_dialogue(text: str, players: dict[str, str], participants: dict[str, str], news: str) -> list[str]:
    """Explicit attributed dialogue needs that player's submitted line.

    This is deliberately limited to quoted speech with a reporting verb;
    atmospheric narration or NPC dialogue must not be classified as a player turn.
    """
    text = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", text)
    patterns = {
        cid: re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", re.IGNORECASE) for cid, name in participants.items()
    }
    submitted_lines: dict[str, list[str]] = {}
    author = None
    for line in news.splitlines():
        header = re.match(r"^(?:- \[[^\]]+\] .*?)?\(([^,)]+)(?:,[^)]*)?\):\s*(.*)$", line)
        if header:
            author = header.group(1)
            submitted_lines.setdefault(author, []).append(header.group(2))
        elif line.startswith("- ["):
            author = None  # A message from someone without a registered hero.
        elif author and not line.startswith("  намерение (разбор парсера):"):
            submitted_lines[author].append(line)
    bad = set()
    quotes = [(m.start(), m.end(), m.group(1) or m.group(2)) for m in re.finditer(r'«([^»\n]+)»|"([^"\n]+)"', text)]
    quotes += [(m.start(), m.end(), m.group(1)) for m in re.finditer(r"(?:^|\n)[ \t]*[—–-][ \t]*([^\n]+)", text)]
    for start, finish, words in quotes:
        before = text[max(0, start - 180) : start].rstrip()
        before = re.split(r'[.!?][»"]?\s+|;\s*', before)[-1]
        after = text[finish : finish + 120]
        speaker = None
        candidates = [(m.end(), cid) for cid, pattern in patterns.items() for m in pattern.finditer(before)]
        if candidates:
            candidates.sort()
            end, cid = candidates[0]
            # An explicit pronoun starts a new clause ('к Emris, та отвечает').
            # Otherwise the first named subject speaks, not the NPC's addressee.
            if re.search(r",\s*(?:та|тот|он|она)\b|,\s*как\b", before, re.IGNORECASE):
                end, cid = candidates[-1]
            if _SPEAKS.search(before[end:]):
                speaker = cid
        if speaker is None:
            said = _SPEAKS.match(re.sub(r"^[\s,.;—–-]+", "", after))
            if said:
                candidates = [(m.start(), cid) for cid, pattern in patterns.items() for m in pattern.finditer(after)]
                if candidates:
                    speaker = min(candidates)[1]
        if speaker not in players:
            continue
        words = " ".join(words.casefold().split())
        submitted = " ".join(submitted_lines.get(speaker, [])).casefold()
        submitted = " ".join(submitted.split())
        if not re.search(r"(?<!\w)" + re.escape(words) + r"(?!\w)", submitted):
            bad.add(speaker)
    return sorted(bad)


# Явно пронумерованные персонажи («Скелет 1», «Страж 2») — экземпляры,
# а не общие слова об атмосфере или слухах.
NUMBERED_NAME = re.compile(r"(?<!\w)([А-ЯЁA-Z][а-яёa-z-]+\s+[1-9]\d*)(?!\w)")
NON_ACTORS = frozenset(
    {
        "комната",
        "глава",
        "акт",
        "сцена",
        "раунд",
        "ход",
        "день",
        "уровень",
        "этаж",
        "зал",
        "этап",
        "часть",
        "пункт",
        "шаг",
        "клетка",
    }
)


def _stem_matches(stem: str, target: str) -> bool:
    """Проверяет совпадение основы слова с зарегистрированным именем с учётом склонения."""
    if stem == target:
        return True
    # Падежные окончания существительных мужского рода (скелет -> скелета, скелету, скелетом, скелете, скелетов)
    if stem.startswith(target) and len(stem) - len(target) <= 3:
        return True
    if target.startswith(stem) and len(target) - len(stem) <= 2:
        return True
    # Падежные окончания женского и среднего рода (крыса -> крысу, крысой; чудище -> чудища)
    if len(stem) >= 3 and len(target) >= 3:
        if stem[:-1] == target[:-1]:
            return True
        if len(stem) >= 4 and stem[:-2] == target[:-1]:
            return True
        if len(target) >= 4 and target[:-2] == stem[:-1]:
            return True
        if len(stem) >= 4 and len(target) >= 4 and stem[:-2] == target[:-2]:
            return True
    return False


def unregistered_named_actors(text: str, world) -> list[str]:
    """Имена новых пронумерованных участников, отсутствующих в текущей сцене.

    Не выводим сущности из текста и не раскрываем существ из других комнат.
    """
    active = {e.name.casefold() for e in world.in_scene_entities()}
    active.update(ch.name.casefold() for ch in world.characters.values())
    places = {e.name.casefold() for e in world.entities.values() if e.kind == "location"}
    known = active | places

    known_numbered: list[tuple[str, str]] = []
    for k in known:
        parts = k.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            known_numbered.append((parts[0], parts[1]))

    found = set()
    for match in NUMBERED_NAME.finditer(text):
        name = match.group(1)
        stem, num = name.rsplit(" ", 1)
        stem_cf = stem.casefold()
        if stem_cf in NON_ACTORS:
            continue
        if name.casefold() in known:
            continue
        if any(num == k_num and _stem_matches(stem_cf, k_stem) for k_stem, k_num in known_numbered):
            continue
        found.add(name)
    return sorted(found)
