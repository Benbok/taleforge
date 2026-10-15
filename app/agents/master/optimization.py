"""Validated, independently switchable decision optimizations."""

FLAGS = ("action_refs", "tool_profiles", "role_context", "early_finish", "compact_voice", "compact_review")


def optimization_flags(settings: dict) -> dict[str, bool]:
    values = settings.get("llm_optimization", {})
    if not isinstance(values, dict) or any(
        key not in FLAGS or type(value) is not bool for key, value in values.items()
    ):
        raise ValueError("llm_optimization must contain only known boolean flags")
    return {key: values.get(key, False) for key in FLAGS}
