"""Подсказки сервера мастеру внутри хода: то, что системный промпт модель теряет, а событие хода точно знает."""

from __future__ import annotations

import re

from app.core import adventure

_ASKS_NAME = re.compile(
    r"как\s+(?:тебя|вас)\s+(?:зовут|звать|величать|называть|называют)|(?:твоё|твое|ваше)\s+(?:настоящее\s+)?имя|"
    r"(?:назови|скажи)\s+(?:своё|свое|мне\s+своё|мне\s+свое)?\s*имя|как\s+(?:тебя|вас)\s+на\s+самом\s+деле",
    re.IGNORECASE,
)


def _stem(word: str) -> str:
    return word[:-1] if len(word) > 4 else word


def asks_name(text: str) -> bool:
    return bool(_ASKS_NAME.search(text))


def name_hint(ctx, new, char_by_seat) -> str:
    """Игрок спросил NPC, как его зовут: безымянному NPC мастер обязан дать имя инструментом, а не отложить ответ."""
    if adventure.is_module(ctx.campaign):
        return ""
    asked = [m for m in new if m.kind in ("action", "speech") and asks_name(m.content or "")]
    if not asked:
        return ""
    creatures = [
        e
        for e in ctx.world.in_scene_entities()
        if e.kind == "creature" and not (e.state or {}).get("dead") and (e.state or {}).get("attitude") != "hostile"
    ]
    unnamed = [e for e in creatures if not (e.state or {}).get("given_name")]
    if not unnamed:
        return ""
    text = " ".join((m.content or "").casefold() for m in asked)
    called = [e for e in unnamed if any(_stem(w) in text for w in re.findall(r"\w{4,}", e.name.casefold()))]
    targets = called or (unnamed if len(unnamed) == 1 else [])
    if not targets:
        return ""
    names = "; ".join(f"{e.name} ({e.id})" for e in targets[:3])
    return (
        "\n\nИгрок спрашивает имя NPC: " + names + ". Если у него нет собственного имени (название — должность или "
        "описание), придумай подходящее миру и ДО рассказа вызови update_entity(entity_id=…, name=…): "
        "без вызова имени нет. "
        "Потом опиши ответ NPC: он называется или по характеру отказывается, но не откладывает ответ на потом."
    )
