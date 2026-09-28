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


class MasterIn(BaseModel):
    type: Literal["owner", "agent"] = "agent"
    provider: Literal["claude", "gemini", "local"] | None = "claude"
    model: str | None = None
    temperature: float = Field(default=0.8, ge=0, le=2)
    style: str | None = Field(default=None, max_length=2000)


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
    creation_rules: CreationRulesIn = CreationRulesIn()
    test_mode: bool = Field(default=False, description="тестовая кампания: видны черновые записи пакета")


class CampaignPatchIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    public_intro: str | None = Field(default=None, max_length=10000)
    difficulty: Literal["easy", "normal", "hard", "deadly"] | None = None
    turn_timeout_sec: int | None = Field(default=None, ge=30, le=300)
    spend_limit_usd: float | None = Field(default=None, ge=0)
    collect_window_sec: int | None = Field(default=None, ge=0, le=300)
    excluded_themes: list[str] | None = Field(default=None, max_length=20)


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
