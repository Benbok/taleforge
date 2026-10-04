"""Эмоции мастера в живой игре: одно состояние на кампанию в scene.state["gm_mood"].

Каждый ход мастера: затухание по характеру, затем дельта от бросков героев (натуральные 1 и 20) и от оценки
реплик игроков технической моделью. Итог превращается в строку для системного промпта повествования.
"""

from __future__ import annotations

from typing import Any

from app.emotion.analyzers import PERSONAS
from app.emotion.injector import SystemPromptInjector
from app.emotion.schemas import EmotionState, GMPersona

MOOD_KEY = "gm_mood"
FIELDS = ("anger", "joy", "suspicion", "boredom")


def persona_of(persona_id: str | None) -> GMPersona:
    return PERSONAS.get(persona_id or "", PERSONAS["tired_mentor"])


def load(scene_state: dict[str, Any] | None) -> EmotionState:
    raw = (scene_state or {}).get(MOOD_KEY) or {}
    return EmotionState(**{k: float(raw.get(k, 0.0)) for k in FIELDS})


def dump(state: EmotionState) -> dict[str, float]:
    return {k: round(getattr(state, k), 2) for k in FIELDS}


def crit_delta(persona: GMPersona, successes: int, failures: int) -> EmotionState:
    """Реакция характера на натуральные 20 и 1 героев за ход."""
    out = EmotionState()
    for k in FIELDS:
        v = successes * getattr(persona.on_crit_success, k) + failures * getattr(persona.on_crit_fail, k)
        setattr(out, k, v)
    return out


def step(state: EmotionState, persona: GMPersona, *deltas: EmotionState) -> EmotionState:
    """Затухание за ход, затем сумма дельт; каждая эмоция в пределах 0–10."""
    out = EmotionState()
    for k in FIELDS:
        v = max(0.0, getattr(state, k) - getattr(persona.decay_rates, k))
        v += sum(getattr(d, k) for d in deltas)
        setattr(out, k, max(0.0, min(10.0, v)))
    return out


def instruction(state: EmotionState) -> str:
    return SystemPromptInjector().inject(state)


def hero_naturals(events, hero_ids: set[str]) -> tuple[int, int]:
    """Сколько натуральных 20 и 1 выбросили герои за ход (атаки, проверки, спасброски, заклинания)."""
    hi = lo = 0

    def walk(x: Any) -> None:
        nonlocal hi, lo
        if isinstance(x, dict):
            nat = x.get("natural")
            if isinstance(nat, int) and not isinstance(nat, bool):
                hi += nat == 20
                lo += nat == 1
            for v in x.values():
                if isinstance(v, dict | list):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    for ev in events:
        if getattr(ev, "actor_id", None) in hero_ids:
            walk(getattr(ev, "payload", None))
    return hi, lo
