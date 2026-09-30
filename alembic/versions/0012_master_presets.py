"""master presets for ai master

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-30 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "master_presets",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("model_profile_id", sa.String(length=32), nullable=True),
        sa.Column("persona_id", sa.String(length=32), nullable=True),
        sa.Column("persona_preset", sa.String(length=64), nullable=True),
        sa.Column("persona_settings", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("style", sa.Text(), nullable=True),
        sa.Column("character", JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name"),
    )
    op.create_index(op.f("ix_master_presets_user_id"), "master_presets", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_master_presets_user_id"), table_name="master_presets")
    op.drop_table("master_presets")
