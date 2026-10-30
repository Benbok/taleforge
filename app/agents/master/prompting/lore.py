"""Small deterministic lore blocks and lexical retrieval, without external services."""

import re
from dataclasses import dataclass

LORE_FIELDS = ("laws", "powers", "world", "inhabitants", "history")
_ENDINGS = tuple(
    sorted(
        {
            "иями",
            "ями",
            "ами",
            "его",
            "ого",
            "ему",
            "ому",
            "ыми",
            "ими",
            "ией",
            "иям",
            "ием",
            "иях",
            "ия",
            "ья",
            "ью",
            "ий",
            "ый",
            "ой",
            "ей",
            "ая",
            "яя",
            "ое",
            "ее",
            "ие",
            "ые",
            "ых",
            "их",
            "ам",
            "ям",
            "ах",
            "ях",
            "ом",
            "ем",
            "ов",
            "ев",
            "ую",
            "юю",
            "ть",
            "ти",
            "ы",
            "и",
            "а",
            "я",
            "у",
            "ю",
            "е",
            "о",
            "ь",
        },
        key=lambda suffix: (-len(suffix), suffix),
    )
)


@dataclass(frozen=True)
class LoreBlock:
    id: str
    title: str
    summary: str
    text: str


def stems(text: str) -> set[str]:
    result = set()
    for word in re.findall(r"[a-zа-яё]+", text.lower().replace("ё", "е")):
        if len(word) < 3:
            continue
        for ending in _ENDINGS:
            if word.endswith(ending) and len(word) - len(ending) >= 3:
                word = word[: -len(ending)]
                break
        result.add(word)
    return result


def split_lore(world: dict) -> list[LoreBlock]:
    blocks = []
    for field in LORE_FIELDS:
        value = world.get(field)
        if not isinstance(value, str):
            continue
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", value) if paragraph.strip()]
        for index, paragraph in enumerate(paragraphs):
            title = " ".join(paragraph.split()[:6])
            summary = re.split(r"(?<=[.!?])\s", paragraph, maxsplit=1)[0][:120]
            blocks.append(LoreBlock(f"{field}:{index}", title, summary, paragraph))
    return blocks


def select_blocks(blocks: list[LoreBlock], query: str, budget: int) -> tuple[list[dict], list[LoreBlock]]:
    index = [{"id": block.id, "title": block.title, "summary": block.summary} for block in blocks]
    words = stems(query)
    scores = [(len(stems(block.text) & words), position, block) for position, block in enumerate(blocks)]
    selected = []
    remaining = max(0, budget)
    for score, _, block in sorted(scores, key=lambda item: (-item[0], item[1])):
        if score and len(block.text) <= remaining:
            selected.append(block)
            remaining -= len(block.text)
    return index, selected
