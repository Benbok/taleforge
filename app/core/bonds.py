"""Связи героев (проект «Подготовка кампании», раздел 7.1): перед игрой мастер задаёт каждому игроку 2–3 вопроса
о завязке и других героях. Ответы лежат в листе героя (``sheet.bonds``): открытые видят все, личные — только игрок
и мастер. По ответам мастер тайно привязывает героя к узлу или NPC каркаса (личный крючок).
"""

from __future__ import annotations

from typing import Any

from app.db.models import Character

MIN_QUESTIONS, MAX_QUESTIONS = 2, 3
MAX_QUESTION = 300
MAX_ANSWER = 600
DEFAULT_QUESTIONS = [
    "Что связывает тебя с событиями завязки? Почему тебе не всё равно?",
    "Кому из отряда ты чем-то обязан — или кто обязан тебе? Если отряда ещё нет, кого ты ищешь?",
    "Что ты боишься потерять, пока всё это не кончится?",
]


class BondsError(Exception):
    """Неверные вопросы или ответы; текст уходит игроку или модели."""


def bonds_of(ch: Character) -> dict[str, Any]:
    return dict((ch.sheet or {}).get("bonds") or {})


def _save(ch: Character, bonds: dict) -> None:
    ch.sheet = {**(ch.sheet or {}), "bonds": bonds}


def set_questions(ch: Character, questions: list[str], source: str) -> dict:
    qs = [str(q).strip()[:MAX_QUESTION] for q in questions if str(q).strip()]
    if not MIN_QUESTIONS <= len(qs) <= MAX_QUESTIONS:
        raise BondsError(f"вопросов от {MIN_QUESTIONS} до {MAX_QUESTIONS}")
    b = bonds_of(ch)
    b["questions"] = [{"id": f"q{i + 1}", "text": q} for i, q in enumerate(qs)]
    b["answers"] = {}  # новые вопросы — прежние ответы к ним не относятся
    b["source"] = source
    _save(ch, b)
    return b


def ensure_questions(ch: Character) -> bool:
    """Вопросы по умолчанию, пока мастер не задал своих. True — если лист изменился."""
    if bonds_of(ch).get("questions"):
        return False
    set_questions(ch, DEFAULT_QUESTIONS, "default")
    return True


def answer(ch: Character, answers: list[dict]) -> dict:
    b = bonds_of(ch)
    ids = {q["id"] for q in b.get("questions") or []}
    if not ids:
        raise BondsError("вопросов пока нет")
    got = dict(b.get("answers") or {})
    for a in answers:
        qid = a.get("id")
        if qid not in ids:
            raise BondsError(f"нет вопроса {qid}")
        text = str(a.get("text") or "").strip()
        if len(text) > MAX_ANSWER:
            raise BondsError(f"ответ длиннее {MAX_ANSWER} знаков")
        if text:
            got[qid] = {"text": text, "private": bool(a.get("private"))}
        else:
            got.pop(qid, None)
    b["answers"] = got
    _save(ch, b)
    return b


def public_bonds(ch: Character) -> list[dict]:
    b = bonds_of(ch)
    ans = b.get("answers") or {}
    return [
        {"question": q["text"], "answer": ans[q["id"]]["text"]}
        for q in b.get("questions") or []
        if q["id"] in ans and not ans[q["id"]].get("private")
    ]


def render(ch: Character, *, private: bool) -> str:
    """Ответы героя текстом: для мастера — все (личные помечены), для общих сцен — только открытые."""
    b = bonds_of(ch)
    ans = b.get("answers") or {}
    lines = []
    for q in b.get("questions") or []:
        a = ans.get(q["id"])
        if not a or (a.get("private") and not private):
            continue
        mark = " (лично, другим игрокам не раскрывать)" if a.get("private") else ""
        lines.append(f"  — {q['text']} {a['text']}{mark}")
    return "\n".join(lines)
