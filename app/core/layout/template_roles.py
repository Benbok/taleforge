"""Conservative role inference for adapting model-authored location parts."""

from __future__ import annotations


def infer_role(ref: str, name: str, purpose: str) -> str | None:
    strong_text = f"{ref} {name}".casefold()
    purpose_text = purpose.casefold()
    checks = (
        ("prison_cell", ("prison", "prisoner", "jail", "holding_cell", "тюремн", "заключенн", "заключённ")),
        ("corridor", ("corridor", "коридор")),
        ("bedroom", ("bedroom", "спальн", "спален", "guest_room")),
        ("library", ("library", "библиотек", "study", "кабинет")),
        ("chapel", ("chapel", "shrine", "часовн", "святилищ")),
        ("smithy", ("smithy", "forge", "кузниц")),
        ("kitchen", ("kitchen", "кухн")),
        ("crypt", ("crypt", "крипт", "склеп", "гробниц")),
        ("warehouse", ("warehouse", "склад", "пакгауз", "контрабанд")),
        ("market", ("market", "рынок", "прилав")),
        ("cache", ("cache", "тайник", "схрон")),
        ("harbor", ("harbor", "акватор", "вода", "затоплен", "flooded", "гавань")),
        ("pier", ("pier", "причал", "пирс", "лодк")),
        ("quay", ("quay", "набереж", "пристан")),
    )
    strong_matches = [role for role, words in checks if any(word in strong_text for word in words)]
    if any(word in strong_text for word in ("акватор", "water", "flooded", "затоплен", "гавань")):
        return "harbor"
    if len(strong_matches) == 1:
        return strong_matches[0]
    if strong_matches:
        return None
    purpose_matches = [role for role, words in checks if any(word in purpose_text for word in words)]
    return purpose_matches[0] if len(purpose_matches) == 1 else None
