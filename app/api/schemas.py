"""Схемы REST API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

Name = Field(min_length=2, max_length=64, pattern=r"^[\w .\-]+$")
Password = Field(min_length=6, max_length=128)


class LoginIn(BaseModel):
    name: str
    password: str


class SignupIn(BaseModel):
    name: str = Name
    password: str = Password


class RegisterByInviteIn(BaseModel):
    name: str = Name
    password: str = Password


class TokenOut(BaseModel):
    token: str
    user: UserOut


class UserOut(BaseModel):
    id: str
    name: str
    platform_role: str


class UserCreateIn(BaseModel):
    name: str = Name
    password: str = Password
    platform_role: Literal["admin", "player"] = "admin"


Provider = Literal["claude", "gemini", "local"]


Amount = Literal["low", "mid", "high"]


class BriefIn(BaseModel):
    """Анкета кампании (app/core/brief.py). Все поля необязательны: без ответа генератор решает сам."""

    length: Literal["oneshot", "short", "long"] | None = None
    pillars: dict[Literal["combat", "exploration", "social", "mystery", "puzzles"], Amount] = Field(
        default_factory=dict
    )
    emotions: list[Literal["heroism", "fear", "mystery", "tragedy", "humor", "adventure", "moral"]] = Field(
        default_factory=list, max_length=3
    )
    threat: Literal["personal", "regional", "world"] | None = None
    wishes: str = Field(default="", max_length=1000)


class PersonaSettingsIn(BaseModel):
    """Характер подачи ИИ-мастера (app/core/personas.py). Механику и сложность не меняет."""

    seriousness: int = Field(default=4, ge=1, le=5)
    humor: Literal["none", "dry", "light", "absurd"] = "dry"
    darkness: int = Field(default=3, ge=1, le=5)
    verbosity: Literal["short", "medium", "long"] = "medium"
    pace: Literal["fast", "even", "slow"] = "even"
    manner: Literal["narrator", "theatrical", "chronicler", "referee"] = "narrator"
    harshness: int = Field(default=3, ge=1, le=5)
    notes: str = Field(default="", max_length=500)


class MasterPersonaIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    settings: PersonaSettingsIn = PersonaSettingsIn()


class MasterPersonaPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    settings: PersonaSettingsIn | None = None


class MasterPersonaOut(BaseModel):
    id: str
    name: str
    settings: dict
    style: str
    updated_at: datetime | None = None


class PersonaChoiceIn(BaseModel):
    """Выбор персоны мастера: своя из профиля (persona_id), встроенная (preset) или настройки напрямую.
    style — дополнение своими словами поверх персоны."""

    persona_id: str | None = None
    preset: str | None = None
    settings: PersonaSettingsIn | None = None
    style: str | None = Field(default=None, max_length=2000)


class CampaignPersonaOut(BaseModel):
    name: str | None
    source: str | None  # profile | preset | custom | legacy
    settings: dict | None
    style: str | None


class MasterIn(BaseModel):
    """ИИ-мастер: профиль модели из админки (model_profile_id) или явные провайдер и модель.
    Без того и другого берётся профиль по умолчанию, а если его нет — Claude."""

    type: Literal["owner", "agent"] = "agent"
    model_profile_id: str | None = None
    provider: Provider | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    style: str | None = Field(default=None, max_length=2000)
    persona_id: str | None = None
    persona_preset: str | None = None
    persona: PersonaSettingsIn | None = None


class MasterModelIn(BaseModel):
    """Смена модели ИИ-мастера у существующей кампании."""

    model_profile_id: str | None = None
    provider: Provider | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)


class MasterModelOut(BaseModel):
    provider: str
    model: str
    resolved_model: str | None
    temperature: float
    api_base: str | None
    model_profile_id: str | None
    model_profile_name: str | None


class ModelProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    provider: Provider
    model: str = Field(default="", max_length=128)
    api_base: str | None = Field(default=None, max_length=255, pattern=r"^https?://\S+$")
    temperature: float = Field(default=0.8, ge=0, le=2)
    is_default: bool = False


class ModelProfilePatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    provider: Provider | None = None
    model: str | None = Field(default=None, max_length=128)
    api_base: str | None = Field(default=None, max_length=255, pattern=r"^https?://\S+$")
    temperature: float | None = Field(default=None, ge=0, le=2)
    is_default: bool | None = None


class ModelProfileOut(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    resolved_model: str | None
    api_base: str | None
    temperature: float
    is_default: bool
    created_by_name: str | None
    last_check: dict
    campaigns: int
    updated_at: datetime


class ModelCheckIn(BaseModel):
    """Проверка ещё не сохранённой модели из формы."""

    provider: Provider
    model: str = Field(default="", max_length=128)
    api_base: str | None = Field(default=None, max_length=255, pattern=r"^https?://\S+$")


class ProviderOut(BaseModel):
    id: str
    title: str
    key_env: str | None
    key_set: bool | None
    default_model: str | None
    api_base: str | None


class ProfileOut(BaseModel):
    user: UserOut
    created_at: datetime
    stats: dict
    can_manage_models: bool
    can_manage_users: bool


class MePatchIn(BaseModel):
    name: str = Name


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Password


class UserRoleIn(BaseModel):
    platform_role: Literal["super_admin", "admin", "player"]


class CreationRulesIn(BaseModel):
    """Настройки создания персонажа (раздел 5.1)."""

    ability_methods: list[Literal["standard_array", "point_buy", "roll"]] = Field(
        default=["standard_array", "point_buy", "roll"], min_length=1
    )
    start_level: int = Field(default=1, ge=1, le=20)
    review: Literal["master", "auto"] = "master"


class CampaignCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    pack_id: str | None = None
    pack_version: str | None = None
    difficulty: Literal["easy", "normal", "hard", "deadly"] = "normal"
    players: int | None = Field(default=None, ge=1, le=6)
    master: MasterIn = MasterIn()
    public_intro: str = Field(default="", max_length=10000)
    turn_timeout_sec: int = Field(default=300, ge=30, le=300)
    spend_limit_usd: float | None = Field(default=None, ge=0)
    collect_window_sec: int = Field(default=60, ge=0, le=300, description="окно сбора реплик до ответа мастера")
    excluded_themes: list[str] = Field(default_factory=list, max_length=20)
    brief: BriefIn = BriefIn()
    creation_rules: CreationRulesIn = CreationRulesIn()
    test_mode: bool = Field(default=False, description="тестовая кампания: видны черновые записи пакета")
    owner_plays: bool = Field(default=True, description="владелец, если он не мастер, сразу занимает место игрока")


class CampaignPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    public_intro: str | None = Field(default=None, max_length=10000)
    difficulty: Literal["easy", "normal", "hard", "deadly"] | None = None
    turn_timeout_sec: int | None = Field(default=None, ge=30, le=300)
    spend_limit_usd: float | None = Field(default=None, ge=0)
    collect_window_sec: int | None = Field(default=None, ge=0, le=300)
    excluded_themes: list[str] | None = Field(default=None, max_length=20)
    audio_enabled: bool | None = None  # звуковое сопровождение ИИ-мастера
    brief: BriefIn | None = None


class SeatOut(BaseModel):
    id: str
    role: str
    position: int
    occupant_type: str
    user_id: str | None
    user_name: str | None
    agent_provider: str | None = None


class CampaignOut(BaseModel):
    id: str
    name: str
    status: str
    owner_id: str
    is_owner: bool
    my_seat_id: str | None
    my_role: str | None
    ruleset_id: str
    ruleset_version: str
    pack_id: str | None
    pack_version: str | None
    difficulty: str
    party_size_recommended: int
    public_intro: str
    settings: dict
    brief: dict | None = None  # анкета: только владельцу и мастеру, в пожеланиях могут быть спойлеры
    seats: list[SeatOut]
    created_at: datetime


class InviteCreateIn(BaseModel):
    expires_in_hours: int | None = Field(default=72, ge=1, le=24 * 90)
    max_uses: int | None = Field(default=None, ge=1, le=6)


class InviteOut(BaseModel):
    token: str
    url: str
    campaign_id: str
    expires_at: datetime | None
    max_uses: int | None
    uses: int
    revoked: bool


class InvitePreviewOut(BaseModel):
    campaign_name: str
    public_intro: str
    free_seats: int
    valid: bool
    problem: str | None


class PackOut(BaseModel):
    id: str
    version: str
    name: str
    party_size: dict
    counts: dict
    imported_at: datetime


class SecretsIn(BaseModel):
    setting: dict | None = None
    plot: dict | None = None


TokenOut.model_rebuild()
