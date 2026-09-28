"""Модель данных этапа 2 (ТЗ, раздел 4): пользователи, пакеты контента, кампании, места,
приглашения, сеансы и чат. Персонажи, сущности, события и память — следующими этапами."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JSONType = JSON().with_variant(JSONB(), "postgresql")


def now() -> datetime:
    return datetime.now(UTC)


def as_utc(dt: datetime | None) -> datetime | None:
    """SQLite возвращает время без пояса; всё время в базе — UTC."""
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSONType, list[Any]: JSONType}


# --- Пользователи и агенты ---


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("u"))
    name: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    platform_role: Mapped[str] = mapped_column(String(16), default="player")  # super_admin | admin | player
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AgentConfig(Base):
    """Настройки агента на месте: провайдер, модель, персона. Ключи провайдеров — только в окружении."""

    __tablename__ = "agent_configs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ag"))
    provider: Mapped[str] = mapped_column(String(16))  # claude | gemini | local
    model: Mapped[str] = mapped_column(String(128))
    temperature: Mapped[float] = mapped_column(Float, default=0.8)
    persona: Mapped[str | None] = mapped_column(Text)
    persona_source: Mapped[str | None] = mapped_column(String(64))  # ссылка на персонажа ИИ-игрока (раздел 5.2)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)


# --- Пакеты контента (раздел 3.2) ---


class ContentPack(Base):
    __tablename__ = "content_packs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    manifest: Mapped[dict[str, Any]] = mapped_column()
    checksum: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    import_report: Mapped[dict[str, Any]] = mapped_column(default=dict)


class ContentRecord(Base):
    """Запись пакета любого вида. Одна таблица на все виды: пакет может принести и свои виды записей,
    а числа для движка лежат в ``data`` так же, как в YAML. Старые версии пакета не удаляются."""

    __tablename__ = "content_records"
    __table_args__ = (Index("ix_content_records_kind", "pack_id", "pack_version", "kind"),)

    pack_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    pack_version: Mapped[str] = mapped_column(String(32), primary_key=True)
    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # canon | proposal
    name: Mapped[str] = mapped_column(String(255))
    data: Mapped[dict[str, Any]] = mapped_column()


# --- Кампания ---


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("c"))
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default="lobby")  # lobby | active | paused | ended
    ruleset_id: Mapped[str] = mapped_column(String(32), default="dnd5e")
    ruleset_version: Mapped[str] = mapped_column(String(32))
    pack_id: Mapped[str | None] = mapped_column(String(64))
    pack_version: Mapped[str | None] = mapped_column(String(32))
    public_intro: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[str] = mapped_column(String(16), default="normal")  # easy | normal | hard | deadly
    party_size_recommended: Mapped[int] = mapped_column(Integer, default=4)
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    seats: Mapped[list[Seat]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Seat.position", lazy="selectin"
    )


class CampaignSecret(Base):
    """Скрытый лор и тайны сюжета. Сервер отдаёт их только месту мастера (раздел 2)."""

    __tablename__ = "campaign_secrets"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    setting: Mapped[dict[str, Any]] = mapped_column(default=dict)
    plot: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Seat(Base):
    """Место мастера или игрока. Занимает человек (user_id) или агент (agent_config_id)."""

    __tablename__ = "seats"
    __table_args__ = (UniqueConstraint("campaign_id", "position"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("s"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    role: Mapped[str] = mapped_column(String(16))  # master | player
    position: Mapped[int] = mapped_column(Integer)  # 0 — мастер, 1..6 — игроки
    occupant_type: Mapped[str] = mapped_column(String(16), default="empty")  # empty | human | agent
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    agent_config_id: Mapped[str | None] = mapped_column(ForeignKey("agent_configs.id", ondelete="SET NULL"))
    delegated_from: Mapped[str | None] = mapped_column(String(32))  # кто владел местом до замещения (раздел 11)
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="seats")
    user: Mapped[User | None] = relationship(lazy="selectin")


class Invite(Base):
    __tablename__ = "invites"

    token: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: secrets.token_urlsafe(24))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_uses: Mapped[int | None] = mapped_column(Integer)
    uses: Mapped[int] = mapped_column(Integer, default=0)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


# --- Живое состояние ---


class GameSession(Base):
    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("gs"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    started_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(16))  # paused | ended


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("campaign_id", "seq"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("m"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    seq: Mapped[int] = mapped_column(Integer)
    seat_id: Mapped[str | None] = mapped_column(ForeignKey("seats.id", ondelete="SET NULL"))
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # action | speech | whisper | ooc | narration | system
    visible_to: Mapped[list[Any] | None] = mapped_column(JSONType)  # None — все; иначе id мест
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
