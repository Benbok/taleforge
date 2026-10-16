"""Integrated master behavior; campaign settings cannot disable these features.

The internal policy map is retained as an offline evaluator seam for historical
comparisons. There are no runtime, environment or campaign switches.
"""

FLAGS = ("action_refs", "tool_profiles", "role_context", "early_finish", "compact_voice", "compact_review")

# Completion skipping is kept behind an internal quality gate.  The context
# optimizations are production behavior, while early completion is evaluated
# separately until paired prose tests prove that it cannot consume a pending
# narration/reaction response.
EARLY_FINISH_ENABLED = False


def optimization_flags(settings: dict) -> dict[str, bool]:
    # Ignore old persisted values, including explicit false and malformed data.
    return dict.fromkeys(FLAGS, True)
