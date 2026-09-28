"""Поиск по правилам и лору (ТЗ, раздел 9): мастер каждый ход получает несколько релевантных фрагментов,
а не весь пакет.

Корпус — записи пакетов кампании: фрагменты правил (``rule_section``), описания состояний и опасностей, факты лора
с уровнем знания, локации и фракции. Поиск — BM25 по основам слов с грубым русским стеммингом, индекс строится
один раз на цепочку пакетов и живёт в памяти (записи пакета неизменны в пределах версии). Семантический поиск
по эмбеддингам (pgvector) подключается поверх этого же интерфейса, когда появится модель эмбеддингов.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

from app.content.catalog import CatalogView

RULE_KINDS = ("rule_section", "effect_template", "hazard_template")
LORE_KINDS = ("lore_fact", "location_template", "faction")
# уровни знания лора: common — все, initiated — посвящённые, hidden — правда, только мастер
KNOWLEDGE = ("common", "initiated", "hidden")

WORD = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
STOP = set(
    "и в во на с со к ко по о об от до за из у же ли не ни но а да то это как что чтобы при для над под или "
    "его её ее их он она они оно мы вы я ты мой твой свой наш ваш всё все весь был была были быть есть уже "
    "еще ещё так там тут где когда если бы только очень себя себе меня мне тебя тебе нас вам".split()
)
ENDINGS = sorted(
    (
        "иями ями ами ией ией иях ях ах ов ев ей ий ый ой ая яя ое ее ые ие ую юю ом ем ам им ым их ых ого его "
        "ому ему ешь ет ют ут ит ат ят ишь ть ться тся лся ла ло ли ет ов ом ей ия ие ью ии а я о е ы и у ю ь й"
    ).split(),
    key=len,
    reverse=True,
)


def stem(word: str) -> str:
    """Грубая основа русского слова: срезаем самое длинное окончание, оставляя не меньше 4 букв."""
    w = word.lower().replace("ё", "е")
    for end in ENDINGS:
        if w.endswith(end) and len(w) - len(end) >= 4:
            return w[: -len(end)]
    return w


def terms(text: str) -> list[str]:
    return [stem(w) for w in WORD.findall(text or "") if w.lower() not in STOP and len(w) > 1]


@dataclass
class Section:
    id: str
    kind: str
    title: str
    body: str
    visibility: str = "common"  # common | initiated | hidden (только мастер)
    tags: list[str] = field(default_factory=list)

    def render(self) -> str:
        mark = {"hidden": " [только мастер]", "initiated": " [знание посвящённых]"}.get(self.visibility, "")
        return f"{self.title}{mark}: {self.body}"


def _section(e) -> Section | None:
    d = e.data
    if e.kind == "rule_section":
        body = d.get("text", "")
    elif e.kind in ("effect_template", "hazard_template"):
        body = d.get("description", "")
    elif e.kind == "lore_fact":
        body = d.get("text", "")
    elif e.kind == "location_template":
        body = d.get("description") or d.get("text") or ""
    elif e.kind == "faction":
        body = " ".join(str(x) for x in (d.get("description"), d.get("goal")) if x)
    else:
        return None
    if not body:
        return None
    vis = str(d.get("knowledge") or "common")
    if vis not in KNOWLEDGE:
        vis = "hidden"
    name = d.get("name") or e.id
    tags = [str(t) for t in d.get("tags") or []] + str(d.get("keywords") or "").split()
    return Section(e.id, e.kind, str(name), " ".join(str(body).split()), vis, tags)


class Index:
    """BM25 по заголовку, тегам и тексту. Заголовок весит вдвое."""

    K1, B = 1.4, 0.75

    def __init__(self, sections: list[Section]):
        self.sections = sections
        self.docs: list[Counter] = []
        for s in sections:
            words = terms(s.title) * 2 + terms(" ".join(s.tags)) + terms(s.body)
            self.docs.append(Counter(words))
        self.avg = sum(sum(d.values()) for d in self.docs) / max(1, len(self.docs))
        df: Counter = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4, *, visible: tuple[str, ...] = KNOWLEDGE) -> list[Section]:
        q = set(terms(query))
        if not q:
            return []
        scored = []
        for i, d in enumerate(self.docs):
            s = self.sections[i]
            if s.visibility not in visible:
                continue
            length = sum(d.values())
            score = 0.0
            for t in q:
                f = d.get(t)
                if f:
                    score += self.idf[t] * f * (self.K1 + 1) / (f + self.K1 * (1 - self.B + self.B * length / self.avg))
            if score > 0:
                scored.append((-score, s.id, s))
        return [s for _, _, s in sorted(scored)[:k]]


def index_for(catalog: CatalogView, scope: str) -> Index:
    """Индекс правил (``rules``) или лора (``lore``) для каталога кампании; строится один раз на каталог."""
    cache = catalog.catalog.__dict__.setdefault("_knowledge", {})  # живёт столько же, сколько каталог в кэше
    if scope not in cache:
        kinds = RULE_KINDS if scope == "rules" else LORE_KINDS
        secs = []
        for kind in kinds:
            for e in catalog.by_kind(kind):
                s = _section(e)
                if s is None:
                    continue
                secs.append(s)
        cache[scope] = Index(secs)
    return cache[scope]


def rules_for(catalog: CatalogView, query: str, k: int = 4) -> list[Section]:
    return index_for(catalog, "rules").search(query, k)


def lore_for(catalog: CatalogView, query: str, k: int = 4, *, visible: tuple[str, ...] = KNOWLEDGE) -> list[Section]:
    return index_for(catalog, "lore").search(query, k, visible=visible)
