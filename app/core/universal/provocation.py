"""Действия, на которые враг отвечает в обмене."""

from app.rules.universal.exploration import ExplorationAction

QUIET_KINDS = frozenset({"speak", "observe", "wait", "hold_breath"})
QUIET_SECONDS = 60


def provokes(action: ExplorationAction) -> bool:
    return not (
        action.operations
        and all(op.kind in QUIET_KINDS for op in action.operations)
        and action.elapsed_game_seconds <= QUIET_SECONDS
    )
