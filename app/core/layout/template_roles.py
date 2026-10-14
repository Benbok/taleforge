"""Conservative role inference for adapting model-authored location parts."""
from __future__ import annotations


def infer_role(ref: str, name: str, purpose: str) -> str | None:
    text = f"{ref} {name} {purpose}".casefold()
    if any(word in text for word in ("акватор", "water", "flooded", "затоплен", "гавань")):
        return "harbor"
    checks = (
        ("warehouse", ("warehouse", "склад", "пакгауз", "контрабанд")),
        ("market", ("market", "рынок", "прилав")),
        ("cache", ("cache", "тайник", "схрон")),
        ("harbor", ("harbor", "акватор", "вода", "затоплен", "flooded", "гавань")),
        ("pier", ("pier", "причал", "пирс", "лодк")),
        ("quay", ("quay", "набереж", "пристан")),
    )
    matches = [role for role, words in checks if any(word in text for word in words)]
    return matches[0] if len(matches) == 1 else None
