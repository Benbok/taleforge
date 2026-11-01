"""The master's story threads: what the story is leaning towards after what the heroes did. They live in the
campaign's secrets next to the plot and the cast, and are refreshed every few turns, so the story answers the players
instead of waiting for them on the author's road."""

THREAD_LIMIT = 3
REFRESH_EVERY = 5  # hero actions between two refreshes
FIELDS = ("hook", "who", "reveals")


def threads_of(secret) -> list[dict]:
    return [t for t in ((secret.setting or {}).get("threads") if secret else None) or [] if isinstance(t, dict)]


def clean(raw) -> list[dict]:
    """The model's threads, trimmed to what is used: a hook, who carries it, what can be learned from it."""
    items = raw.get("threads") if isinstance(raw, dict) else raw
    result = []
    for item in items or []:
        if not isinstance(item, dict) or not str(item.get("hook") or "").strip():
            continue
        result.append({key: str(item.get(key) or "").strip()[:300] for key in FIELDS})
        if len(result) == THREAD_LIMIT:
            break
    return result


def note_action(setting: dict) -> dict:
    """The setting with one more hero action counted since the threads were last refreshed."""
    return {**setting, "threads_age": int(setting.get("threads_age", 0)) + 1}


def due(setting: dict) -> bool:
    return not setting.get("threads") or int(setting.get("threads_age", 0)) >= REFRESH_EVERY


def renewed(setting: dict, threads: list[dict]) -> dict:
    return {**setting, "threads": threads, "threads_age": 0}
