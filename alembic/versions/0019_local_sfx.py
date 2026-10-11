"""Durable local SFX cache, revisions, queue and playback outbox."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None
JSON = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "sfx_sounds",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=False),
        sa.Column("parameters", JSON, nullable=False),
        sa.Column("current_asset_id", sa.String(32)),
        sa.Column("pinned", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "cache_key"),
    )
    op.create_index("ix_sfx_sounds_campaign_id", "sfx_sounds", ["campaign_id"])
    op.create_table(
        "sfx_assets",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sound_id", sa.String(32), sa.ForeignKey("sfx_sounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("parameters", JSON, nullable=False),
        sa.Column("cache_key", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sfx_assets_sound_id", "sfx_assets", ["sound_id"])
    op.create_index("ix_sfx_assets_cache_key", "sfx_assets", ["cache_key"])
    op.create_table(
        "sfx_jobs",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("sound_id", sa.String(32), sa.ForeignKey("sfx_sounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("parameters", JSON, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.Float(), nullable=False),
        sa.Column("next_attempt_at", sa.Float(), nullable=False),
        sa.Column("error", sa.String(500)),
        sa.Column("asset_id", sa.String(32)),
        sa.Column("elapsed_seconds", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_sfx_jobs_sound_id", "sfx_jobs", ["sound_id"])
    op.create_index("ix_sfx_jobs_status", "sfx_jobs", ["status"])
    op.create_index(
        "uq_sfx_jobs_active_sound",
        "sfx_jobs",
        ["sound_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('staged', 'queued', 'running')"),
        postgresql_where=sa.text("status IN ('staged', 'queued', 'running')"),
    )
    op.create_table(
        "sfx_playbacks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sound_id", sa.String(32), sa.ForeignKey("sfx_sounds.id", ondelete="CASCADE"), nullable=False),
        sa.Column("turn_id", sa.String(32)),
        sa.Column("asset_id", sa.String(32)),
        sa.Column("audience", JSON, nullable=False),
        sa.Column("context", JSON, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "turn_id"),
    )
    op.create_index("ix_sfx_playbacks_campaign_id", "sfx_playbacks", ["campaign_id"])
    op.create_index("ix_sfx_playbacks_status", "sfx_playbacks", ["status"])
    lock = op.create_table(
        "sfx_lock",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("lease_token", sa.String(32)),
        sa.Column("lease_until", sa.Float(), nullable=False),
    )
    op.bulk_insert(lock, [{"id": 1, "lease_until": 0}])


def downgrade() -> None:
    for table in ("sfx_lock", "sfx_playbacks", "sfx_jobs", "sfx_assets", "sfx_sounds"):
        op.drop_table(table)
