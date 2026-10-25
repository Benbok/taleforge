"""Stable public failures; private exceptions are never fictional world events."""

from typing import Literal

from app.rules.universal.contracts import ClosedModel

FailureKind = Literal[
    "invalid_proposal",
    "unsupported_capability",
    "not_allowed",
    "target_unavailable",
    "insufficient_resources",
    "stale_profile",
    "world_denial",
    "roll_failed",
    "internal_error",
]


class ActionFailure(ClosedModel):
    category: FailureKind
    code: str
    message: str
    retryable: bool = False


_FAILURES = {
    "missing_check_outcomes": (
        "invalid_proposal",
        "Мастер не определил конкретные последствия проверки. Бросок не выполнен; ресурсы не потрачены.",
    ),
    "invalid_proposal": (
        "invalid_proposal",
        "Мастер предложил некорректные параметры действия. Ничего не применено; ресурсы не потрачены.",
    ),
    "unsupported_duration": (
        "unsupported_capability",
        "Длительные эффекты пока не поддерживаются движком. Это техническое ограничение; ресурсы не потрачены.",
    ),
    "unsupported_item": (
        "unsupported_capability",
        "Этот способ применения предмета пока не поддерживается движком. Ресурсы не потрачены.",
    ),
    "unsupported_profile": (
        "unsupported_capability",
        "Этот эффект пока не поддерживается движком. Ресурсы не потрачены.",
    ),
    "not_allowed": ("not_allowed", "Нет права выполнять действие за этого героя."),
    "invalid_targets": ("invalid_proposal", "Мастер указал некорректные цели действия. Ресурсы не потрачены."),
    "target_unavailable": ("target_unavailable", "Цель недоступна в текущей сцене. Ресурсы не потрачены."),
    "insufficient_resources": (
        "insufficient_resources",
        "Для этого действия недостаточно энергии. Ресурсы не потрачены.",
    ),
    "stale_profile": (
        "stale_profile",
        "Правила действия изменились; требуется новое подтверждение. Ресурсы не потрачены.",
    ),
    "internal_error": ("internal_error", "Не удалось обработать действие из-за технического сбоя. Повторите попытку."),
    "provider_error": (
        "internal_error",
        "Провайдер модели не смог ответить. Действие сохранено; попробуйте повторить позже.",
    ),
    "narration_unavailable": (
        "internal_error",
        "Результат действия сохранён, но ответ мастера задержан из-за технического сбоя. "
        "Повтор восстанавливает ответ без повторного применения действия.",
    ),
}


def action_failure(code: str) -> ActionFailure:
    category, message = _FAILURES[code]
    return ActionFailure(
        category=category,
        code=code,
        message=message,
        retryable=category in {"invalid_proposal", "internal_error", "stale_profile"},
    )


class ActionValidationError(ValueError):
    def __init__(self, code: str):
        self.failure = action_failure(code)
        super().__init__(code)


class ActionModelError(RuntimeError):
    def __init__(self):
        self.failure = action_failure("provider_error")
        super().__init__("provider_error")


def reject(code: str):
    raise ActionValidationError(code)
