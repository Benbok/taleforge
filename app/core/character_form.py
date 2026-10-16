"""Persisted physical form, independent of cosmetic disguises and narration."""

from app.db.models import Character


def current_form(character: Character, game_time: int) -> dict | None:
    form = (character.resources or {}).get("current_form")
    if not isinstance(form, dict):
        return None
    expires_at = form.get("expires_at")
    if expires_at is not None and game_time >= expires_at:
        return None
    return form
