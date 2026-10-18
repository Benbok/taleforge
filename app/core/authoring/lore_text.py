"""Authored world lore as text for other prompts. No imports from agents: the architect uses it too."""


def _lines(items, fmt) -> list[str]:
    return [fmt(x) for x in items or [] if isinstance(x, dict)]


def render_lore(lore: dict | None, limit: int = 6000) -> str:
    """Readable digest of the structured lore; the legacy one-line shape is rendered as well."""
    if not lore:
        return ""
    out: list[str] = []
    for key, title in (("overview", "Мир"), ("world", "Мир"), ("era_and_magic", "Эпоха и магия")):
        if lore.get(key):
            out.append(f"{title}: {lore[key]}")
    regions = _lines(lore.get("regions"), lambda r: f"- {r.get('name')}: {r.get('description', '')}")
    if regions:
        out += ["Области:", *regions]
    history = lore.get("history")
    if isinstance(history, str) and history:
        out.append(f"История: {history}")
    elif history:
        out += ["Хронология:", *_lines(history, lambda h: f"- {h.get('when', '')}: {h.get('event', '')}")]
    factions = lore.get("factions") or []
    if factions:
        out.append("Фракции:")
        for f in factions:
            if isinstance(f, str):
                out.append(f"- {f}")
            elif isinstance(f, dict):
                parts = [f.get("goal"), f.get("resources") and f"ресурсы: {f['resources']}", f.get("relations")]
                out.append(f"- {f.get('name')}: " + "; ".join(p for p in parts if p))
    figures = _lines(lore.get("figures"), lambda p: f"- {p.get('name')} ({p.get('role', '')}): {p.get('motive', '')}")
    if figures:
        out += ["Ключевые фигуры:", *figures]
    if lore.get("current_situation"):
        out.append(f"Сейчас: {lore['current_situation']}")
    if lore.get("mysteries"):
        out.append("Тайны мира: " + "; ".join(str(m) for m in lore["mysteries"]))
    if lore.get("tone"):
        out.append(f"Тон: {lore['tone']}")
    if lore.get("taboos"):
        out.append("Не использовать: " + ", ".join(str(t) for t in lore["taboos"]))
    return "\n".join(out)[:limit]
