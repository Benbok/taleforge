"""Модель данных (ТЗ, раздел 4): пользователи, пакеты контента, кампании, места, приглашения, сеансы и чат
(этап 2); персонажи, сущности мира, сцена, эффекты, журнал событий, ходы мастера и лог обращений к моделям
(этап 3). Сводки, голосования и база знаний — следующими этапами."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
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
    menu_music_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true(), nullable=False)
    menu_music_volume: Mapped[float] = mapped_column(Float, default=0.2, server_default=text("0.2"), nullable=False)
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


class ModelProfile(Base):
    """Модель ИИ, настроенная админом: провайдер, имя модели, адрес локального сервера. Кампания при создании
    копирует профиль в AgentConfig мастера. Ключи провайдеров — только в окружении сервера, не здесь."""

    __tablename__ = "model_profiles"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mp"))
    name: Mapped[str] = mapped_column(String(64), unique=True)
    provider: Mapped[str] = mapped_column(String(16))  # claude | gemini | local
    model: Mapped[str] = mapped_column(String(128), default="")
    api_base: Mapped[str | None] = mapped_column(String(255))  # только local: адрес LM Studio
    temperature: Mapped[float] = mapped_column(Float, default=0.8)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    last_check: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {ok, at, latency_ms, reply, error, model}
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MasterPersona(Base):
    """Персона ИИ-мастера в профиле Admin: характер подачи (app/core/personas.py). Кампания получает копию."""

    __tablename__ = "master_personas"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("per"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    settings: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class MasterPreset(Base):
    """Пресет настроек и характера ИИ-мастера (модель, тон, анкета характера). Используется для создания кампаний."""

    __tablename__ = "master_presets"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mpre"))
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    model_profile_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    persona_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    persona_preset: Mapped[str | None] = mapped_column(String(64), nullable=True)
    persona_settings: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    style: Mapped[str | None] = mapped_column(Text, nullable=True)
    character: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


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


class AdventureModule(Base):
    """Готовое приключение в библиотеке (app/core/modules.py): книга, разбор переводчика, карты и статус.
    После публикации модуль — пакет ``pack_id`` версии ``pack_version``; файлы лежат в media/modules/<id>/."""

    __tablename__ = "adventure_modules"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("mod"))
    title: Mapped[str] = mapped_column(String(255))
    slug: Mapped[str | None] = mapped_column(String(64))
    # reading | translating | mapping | review | published | failed
    status: Mapped[str] = mapped_column(String(16), default="reading")
    error: Mapped[str | None] = mapped_column(Text)
    source_name: Mapped[str] = mapped_column(String(255), default="")
    pages: Mapped[int] = mapped_column(Integer, default=0)
    text_chars: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")  # пожелание админа к разбору
    draft: Mapped[dict[str, Any]] = mapped_column(default=dict)  # сдача переводчика с проверенным каркасом
    warnings: Mapped[list[Any]] = mapped_column(default=list)
    # [{id, file, name, location_id, marks: [{number, x, y}], missing, status, error}]
    maps: Mapped[list[Any]] = mapped_column(default=list)
    pack_id: Mapped[str | None] = mapped_column(String(64))
    pack_version: Mapped[str | None] = mapped_column(String(32))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


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
    brief: Mapped[dict[str, Any]] = mapped_column(default=dict)  # анкета кампании (app/core/brief.py)
    last_seq: Mapped[int] = mapped_column(Integer, default=0)
    # Версия мира кампании: растёт на каждой защищённой записи (app/core/world_tx.py)
    world_revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Цепочка пакетов кампании от базового к верхнему: [[id, version], ...]. Фиксируется при создании,
    # новая версия пакета идущую кампанию не меняет (раздел 3.2).
    content_chain: Mapped[list[Any]] = mapped_column(default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    seats: Mapped[list[Seat]] = relationship(
        back_populates="campaign", cascade="all, delete-orphan", order_by="Seat.position", lazy="selectin"
    )


class SfxSound(Base):
    """Campaign-scoped named cache entry; current_asset_id changes only after a successful render."""

    __tablename__ = "sfx_sounds"
    __table_args__ = (UniqueConstraint("campaign_id", "cache_key"),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sf"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    cache_key: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(String(300))
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    current_asset_id: Mapped[str | None] = mapped_column(String(32))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SfxAsset(Base):
    __tablename__ = "sfx_assets"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sa"))
    sound_id: Mapped[str] = mapped_column(ForeignKey("sfx_sounds.id", ondelete="CASCADE"), index=True)
    duration_seconds: Mapped[float] = mapped_column(Float)
    size_bytes: Mapped[int] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(Integer)
    digest: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    cache_key: Mapped[str] = mapped_column(String(64), default="", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SfxJob(Base):
    __tablename__ = "sfx_jobs"
    __table_args__ = (
        Index(
            "uq_sfx_jobs_active_sound",
            "sound_id",
            unique=True,
            sqlite_where=text("status IN ('staged', 'queued', 'running')"),
            postgresql_where=text("status IN ('staged', 'queued', 'running')"),
        ),
    )
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sj"))
    sound_id: Mapped[str] = mapped_column(ForeignKey("sfx_sounds.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    seed: Mapped[int] = mapped_column(Integer, default=0)
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_until: Mapped[float] = mapped_column(Float, default=0)
    next_attempt_at: Mapped[float] = mapped_column(Float, default=0)
    error: Mapped[str | None] = mapped_column(String(500))
    asset_id: Mapped[str | None] = mapped_column(String(32))
    elapsed_seconds: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SfxPlayback(Base):
    """Persistent outbox; pending until the turn's text has been published."""

    __tablename__ = "sfx_playbacks"
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sp"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    sound_id: Mapped[str] = mapped_column(ForeignKey("sfx_sounds.id", ondelete="CASCADE"))
    turn_id: Mapped[str | None] = mapped_column(String(32))
    asset_id: Mapped[str | None] = mapped_column(String(32))
    audience: Mapped[list[Any]] = mapped_column(default=list)
    context: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    expires_at: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class SfxLock(Base):
    """Single short SQL lock for admission/claim; a lease excludes overlapping subprocesses."""

    __tablename__ = "sfx_lock"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lease_token: Mapped[str | None] = mapped_column(String(32))
    lease_until: Mapped[float] = mapped_column(Float, default=0)


class CampaignSecret(Base):
    """Скрытый лор и тайны сюжета. Сервер отдаёт их только месту мастера (раздел 2)."""

    __tablename__ = "campaign_secrets"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    setting: Mapped[dict[str, Any]] = mapped_column(default=dict)
    plot: Mapped[dict[str, Any]] = mapped_column(default=dict)


class CampaignPlan(Base):
    """Версии каркаса кампании (app/core/plot.py). Текущая копия лежит в campaign_secrets.plot."""

    __tablename__ = "campaign_plans"
    __table_args__ = (UniqueConstraint("campaign_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pl"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


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
    # живой игрок, который ведёт героя этого места, пока его игрок офлайн (голосование, раздел 11)
    stand_in_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    campaign: Mapped[Campaign] = relationship(back_populates="seats")
    user: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[user_id])
    stand_in: Mapped[User | None] = relationship(lazy="selectin", foreign_keys=[stand_in_user_id])


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
    __table_args__ = (
        UniqueConstraint("campaign_id", "seq"),
        Index("ix_messages_campaign_turn", "campaign_id", "turn_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("m"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"))
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    seq: Mapped[int] = mapped_column(Integer)
    seat_id: Mapped[str | None] = mapped_column(ForeignKey("seats.id", ondelete="SET NULL"))
    author_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # action | speech | whisper | ooc | narration | system | roll
    visible_to: Mapped[list[Any] | None] = mapped_column(JSONType)  # None — все; иначе id мест
    content: Mapped[str] = mapped_column(Text)
    intent: Mapped[dict[str, Any] | None] = mapped_column(JSONType)
    data: Mapped[dict[str, Any] | None] = mapped_column(JSONType)  # данные карточки броска (app/core/rolls.py)
    # ход ИИ-мастера, взявший реплику игрока; пусто — реплика ждёт мастера (design/party-split.md)
    turn_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Мир кампании (этап 3) ---


class Character(Base):
    """Персонаж игрока. Механика в ``sheet`` (выборы конструктора), текущие ресурсы в ``resources``;
    производные величины (КД, хиты, модификаторы) считает движок правил при каждом чтении."""

    __tablename__ = "characters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ch"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    seat_id: Mapped[str | None] = mapped_column(ForeignKey("seats.id", ondelete="SET NULL"))
    owner_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(64))
    # draft | submitted | approved | active | dead | retired (раздел 5.1); premade — заготовка владельца без игрока
    status: Mapped[str] = mapped_column(String(16), default="draft")
    creation_method: Mapped[str] = mapped_column(String(16), default="builder")  # builder | pregen
    sheet: Mapped[dict[str, Any]] = mapped_column(default=dict)
    resources: Mapped[dict[str, Any]] = mapped_column(default=dict)
    public_bio: Mapped[str] = mapped_column(Text, default="")
    private_backstory: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[dict[str, Any]] = mapped_column(default=dict)
    # анкета характера (этап 9б): свободный текст, поля-подсказки и ядро — поля, которые летопись не трогает
    persona: Mapped[dict[str, Any]] = mapped_column(default=dict)
    review_comment: Mapped[str | None] = mapped_column(Text)
    location_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class LibraryCharacter(Base):
    """Герой в профиле игрока, вне кампаний. В кампанию уходит копия: дальше она развивается отдельно,
    поэтому одним героем можно играть в нескольких кампаниях."""

    __tablename__ = "library_characters"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("lc"))
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    sheet: Mapped[dict[str, Any]] = mapped_column(default=dict)
    public_bio: Mapped[str] = mapped_column(Text, default="")
    private_backstory: Mapped[str] = mapped_column(Text, default="")
    personality: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class InventoryItem(Base):
    __tablename__ = "inventory"
    __table_args__ = (Index("uq_inventory_world_entity_id", "world_entity_id", unique=True),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("inv"))
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    item_template_id: Mapped[str] = mapped_column(String(128))
    display_name: Mapped[str | None] = mapped_column(String(128))  # имя от мастера, статы — из шаблона
    qty: Mapped[int] = mapped_column(Integer, default=1)
    equipped: Mapped[bool] = mapped_column(Boolean, default=False)
    # Только уникальные экземпляры сохраняют Entity.id при переносе в инвентарь.
    # У старых и обычных стаковых предметов ссылка остаётся NULL.
    world_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))


class Entity(Base):
    """Всё, с чем можно взаимодействовать, кроме персонажей игроков: существа, NPC, локации, объекты.
    Нет записи — нет сущности (раздел 8.1). Состояние экземпляра (хиты, отношение, жив ли) — в ``state``."""

    __tablename__ = "entities"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("en"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # creature | location | object
    name: Mapped[str] = mapped_column(String(128))
    template_id: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)
    location_id: Mapped[str | None] = mapped_column(String(32))
    # Зона дальности относительно отряда (раздел 7.1): melee — вплотную, near — близко, far — далеко
    zone: Mapped[str] = mapped_column(String(16), default="near")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class WorldGenerationState(Base):
    """Состояние однократной материализации локации/контейнера; не запускает генерацию само по себе."""

    __tablename__ = "world_generation_states"
    __table_args__ = (
        UniqueConstraint("campaign_id", "target_entity_id", "phase", name="uq_world_generation_scope"),
        CheckConstraint(
            "phase IN ('location_initial', 'container_contents', 'location_layout', 'location_geometry')",
            name="ck_world_generation_phase",
        ),
        CheckConstraint("status IN ('unprepared', 'preparing', 'ready', 'blocked')", name="ck_world_generation_status"),
        CheckConstraint(
            "quality IS NULL OR quality IN ('normal', 'fallback', 'legacy_preserved')",
            name="ck_world_generation_quality",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("wg"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    target_entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default="unprepared")
    quality: Mapped[str | None] = mapped_column(String(32))
    revision: Mapped[int] = mapped_column(Integer, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    generator_version: Mapped[str | None] = mapped_column(String(64))
    profile_ref: Mapped[str | None] = mapped_column(String(128))
    source_versions: Mapped[list[Any]] = mapped_column(default=list)
    context_digest: Mapped[str | None] = mapped_column(String(64))
    reservation: Mapped[dict[str, Any]] = mapped_column(default=dict)
    seed: Mapped[int | None] = mapped_column(Integer)
    result_digest: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # запрос активировал резерв
    # исполнение (docs/world-objects-delivery3.md): когда снова пробовать, сколько было вызовов модели и
    # конфликтов мира; закрытый результат с назначенными id, неизменный после ready
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    llm_attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    conflict_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    result_manifest: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)


class PlotAnchorBinding(Base):
    """Стабильная привязка сюжетной зацепки к физическому объекту или месту."""

    __tablename__ = "world_plot_bindings"
    __table_args__ = (
        UniqueConstraint("campaign_id", "anchor_id", name="uq_world_plot_anchor"),
        CheckConstraint(
            "state IN ('reserved', 'materialized', 'revealed', 'lost', 'replaced_by_story')",
            name="ck_world_plot_binding_state",
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pab"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    anchor_id: Mapped[str] = mapped_column(String(128))
    plot_ref: Mapped[str] = mapped_column(String(128))
    holder_entity_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    target_location_id: Mapped[str | None] = mapped_column(ForeignKey("entities.id", ondelete="SET NULL"))
    state: Mapped[str] = mapped_column(String(32), default="reserved")
    source_snapshot: Mapped[dict[str, Any]] = mapped_column(default=dict)
    replacement_ref: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class ActiveEffect(Base):
    """Наложенный эффект или состояние на персонаже или сущности. Снимает его сервер по игровым часам."""

    __tablename__ = "active_effects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ef"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[str] = mapped_column(String(32), index=True)  # ch_… или en_…
    effect_template_id: Mapped[str] = mapped_column(String(128))
    stacks: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[int | None] = mapped_column(Integer)  # игровое время, секунды; None — пока не снимут
    source_event_id: Mapped[str | None] = mapped_column(String(32))
    source: Mapped[str | None] = mapped_column(String(120))  # кто или что наложил: имя существа или явление
    reason: Mapped[str | None] = mapped_column(String(200))  # почему — видят игрок и мастер


class Knowledge(Base):
    """Что персонаж знает о сущности: 0 — видел, 1 — наслышан, 2 — изучил, 3 — знает всё (раздел 10)."""

    __tablename__ = "knowledge"

    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    level: Mapped[int] = mapped_column(Integer, default=0)
    # Явное обнаружение физического объекта этим героем (спецификация генерации сцен, §8.2): только оно делает
    # hidden/secret объект видимым герою. Упоминания и learn_fact его не заполняют; уровень знаний — не видимость.
    revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Что герой видел при последнем разрешённом наблюдении: {schema_version, name, description, observed_at}.
    # Карточка «по памяти» строится из него, а не из нынешнего Entity.description.
    observed_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType)


class MapMemory(Base):
    """Персональный снимок геометрии участка и выданных проходов."""

    __tablename__ = "map_memories"
    __table_args__ = (
        Index("ix_map_memories_character_id", "character_id"),
        Index("ix_map_memories_entity_id", "entity_id"),
    )

    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True)
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    discovered_passages: Mapped[list[Any]] = mapped_column(JSONType, default=list, server_default="[]")
    revision: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class KnownFact(Base):
    """Факт, который герой узнал о сущности, месте или другом герое (просьба Arty, этап 7): карточка по клику
    показывает ровно то, что этот герой знает. Пишет мастер инструментом ``learn_fact``."""

    __tablename__ = "known_facts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("kf"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[str] = mapped_column(String(32))  # en_… или ch_…
    text: Mapped[str] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Scene(Base):
    """Текущая сцена кампании: режим, локация, очередь инициативы. Ход по очереди — этап 4."""

    __tablename__ = "scenes"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default="free")  # free | combat
    location_id: Mapped[str | None] = mapped_column(String(32))
    round: Mapped[int] = mapped_column(Integer, default=0)
    turn_order: Mapped[list[Any]] = mapped_column(default=list)  # [{id, initiative}]
    # Игровые часы кампании, секунды от начала (раздел 7.2). Живут в сцене, а не в кампании: ход мастера
    # держит изменённые строки до конца транзакции, а строку кампании нужна чату для порядковых номеров.
    game_time: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[dict[str, Any]] = mapped_column(default=dict)  # служебное: время последнего долгого отдыха


class MasterTurn(Base):
    """Один ход мастера: какие реплики он закрыл, вызовы инструментов, повествование, срабатывания проверок."""

    __tablename__ = "master_turns"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("t"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(16), default="running")  # running | done | failed
    upto_seq: Mapped[int] = mapped_column(Integer, default=0)  # реплики игроков до этого seq закрыты ходом
    trace: Mapped[dict[str, Any]] = mapped_column(default=dict)
    narration_message_id: Mapped[str | None] = mapped_column(String(32))
    # Граница хода: действия зафиксированы, дальше подготовка и повествование (docs/world-objects-delivery2.md)
    generation_checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PersonaNote(Base):
    """Летопись характера (этап 9б): как герой или ИИ-мастер изменился и почему. ``character_id`` пуст — запись
    о мастере кампании. Откаченная запись хранится, но в подсказку модели не идёт."""

    __tablename__ = "persona_notes"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("pn"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    character_id: Mapped[str | None] = mapped_column(ForeignKey("characters.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)  # что изменилось
    cause: Mapped[str] = mapped_column(Text, default="")  # почему
    source: Mapped[str] = mapped_column(String(16))  # session | event | owner
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Summary(Base):
    """Сводка кампании (раздел 9): прошлая сводка + новые сообщения → новая версия; старые версии хранятся.
    ``rolling`` — каждые N сообщений, ``session`` — в конце сессии (по ней мастер открывает следующую)."""

    __tablename__ = "summaries"
    __table_args__ = (UniqueConstraint("campaign_id", "version"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("sm"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(16))  # rolling | session
    version: Mapped[int] = mapped_column(Integer)
    upto_seq: Mapped[int] = mapped_column(Integer)  # сообщения до этого seq учтены
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)  # квесты, события, NPC, нити, обещания, пересказ
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    """Журнал изменений состояния. Любое изменение мира — событие с кубиками и обратной дельтой."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("campaign_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("ev"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[str | None] = mapped_column(ForeignKey("sessions.id", ondelete="SET NULL"))
    turn_id: Mapped[str | None] = mapped_column(String(32), index=True)
    tool: Mapped[str] = mapped_column(String(32))
    actor_id: Mapped[str | None] = mapped_column(String(32))  # кто действовал: ch_…, en_… или место мастера
    target_id: Mapped[str | None] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    dice: Mapped[list[Any]] = mapped_column(default=list)
    inverse: Mapped[list[Any]] = mapped_column(default=list)  # как откатить: [{table, id, field, before}]
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)  # скрытый бросок: видят мастер и журнал
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    game_time: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class LlmCall(Base):
    """Каждое обращение к модели: токены, стоимость, задержка (раздел 13)."""

    __tablename__ = "llm_calls"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("llm"))
    campaign_id: Mapped[str | None] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    seat_id: Mapped[str | None] = mapped_column(String(32))
    turn_id: Mapped[str | None] = mapped_column(String(32))
    purpose: Mapped[str] = mapped_column(String(32))  # decide | narrate | review
    model: Mapped[str] = mapped_column(String(128))
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    tokens_reasoning: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )  # часть tokens_out у большинства провайдеров
    cost: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    generation_id: Mapped[str | None] = mapped_column(String(32), index=True)  # строка WorldGenerationState
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


# --- Повествовательная адаптация ---


class NarrativeState(Base):
    """Повествовательное состояние кампании: режим, ревизия, счетчики и границы."""

    __tablename__ = "narrative_states"

    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    mode: Mapped[str] = mapped_column(String(16), default="strict")  # strict | adaptive
    recent_boundaries: Mapped[list[Any]] = mapped_column(default=list)
    budget_counters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    initialized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class NarrativeFact(Base):
    """Текущее состояние метаданных фактов: истинность, временная семантика, закрепленность и аудитория."""

    __tablename__ = "narrative_facts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "namespace", "subject_id", "key"),
        Index("ix_narrative_facts_subject", "campaign_id", "namespace", "subject_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("nf"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    namespace: Mapped[str] = mapped_column(String(16))  # plan | module | campaign
    subject_id: Mapped[str] = mapped_column(String(64))
    key: Mapped[str] = mapped_column(String(32))  # role | motivation | relationship | secret_truth | situation_premise
    version: Mapped[int] = mapped_column(Integer, default=1)
    kind: Mapped[str] = mapped_column(String(16))  # truth | testimony | intent
    temporal_semantics: Mapped[str] = mapped_column(String(16))  # historical | current_state
    freedom: Mapped[str] = mapped_column(String(16))  # draft | committed
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    audience: Mapped[list[Any]] = mapped_column(default=list)
    depends_on: Mapped[list[Any]] = mapped_column(default=list)
    source_refs: Mapped[list[Any]] = mapped_column(default=list)
    snapshot_ref: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)


class NarrativeThread(Base):
    """Сюжетная нить кампании: жизненный цикл, внимание и связи."""

    __tablename__ = "narrative_threads"
    __table_args__ = (
        UniqueConstraint("campaign_id", "thread_id"),
        Index("ix_narrative_threads_status", "campaign_id", "status", "last_developed_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("nth"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    thread_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(16), default="offered"
    )  # offered | active | resolved | abandoned | dormant | hidden
    audience: Mapped[list[Any]] = mapped_column(default=list)
    subject_refs: Mapped[list[Any]] = mapped_column(default=list)
    plan_refs: Mapped[list[Any]] = mapped_column(default=list)
    parent_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_refs: Mapped[list[Any]] = mapped_column(default=list)
    last_developed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class NarrativeWork(Base):
    """Устойчивые задания фонового режиссёра (spec §15.1)."""

    __tablename__ = "narrative_work"
    __table_args__ = (
        UniqueConstraint("campaign_id", "source_key", name="uq_narrative_work_source"),
        Index("ix_narrative_work_status", "status", "retry_after", "lease_until"),
        Index("ix_narrative_work_campaign_created", "campaign_id", "created_at"),
        Index(
            "ix_narrative_work_capacity_slot",
            "capacity_slot",
            unique=True,
            sqlite_where=text("capacity_slot IS NOT NULL"),
            postgresql_where=text("capacity_slot IS NOT NULL"),
        ),
        Index(
            "ix_narrative_work_campaign_preparing",
            "campaign_id",
            unique=True,
            sqlite_where=text("status = 'preparing'"),
            postgresql_where=text("status = 'preparing'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=lambda: new_id("nw"))
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id", ondelete="CASCADE"), index=True)
    source_key: Mapped[str] = mapped_column(String(128))
    scope: Mapped[str] = mapped_column(String(16), default="future")
    kind: Mapped[str] = mapped_column(String(32))
    source_id: Mapped[str] = mapped_column(String(64))
    audience: Mapped[list[Any]] = mapped_column(default=list)
    focus: Mapped[str | None] = mapped_column(String(128), nullable=True)
    session_budget_ref: Mapped[str] = mapped_column(String(64))
    policy_version: Mapped[int] = mapped_column(Integer, default=1)
    evidence_refs: Mapped[list[Any]] = mapped_column(default=list)
    base: Mapped[dict[str, Any] | None] = mapped_column(default=dict, nullable=True)
    proposal_id: Mapped[str] = mapped_column(String(64))
    draft: Mapped[dict[str, Any] | None] = mapped_column(default=dict, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    capacity_slot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    resnapshots: Mapped[int] = mapped_column(Integer, default=0)
    retry_after: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    receipt_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
