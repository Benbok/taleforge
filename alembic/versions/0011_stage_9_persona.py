"""stage 9 persona and chronicle

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-29 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("characters") as batch:
        batch.add_column(sa.Column("persona", JSON, nullable=False, server_default="{}"))
    op.create_table(
        "persona_notes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=32), nullable=False),
        sa.Column("character_id", sa.String(length=32), nullable=True),
        sa.Column("session_id", sa.String(length=32), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_persona_notes_campaign_id", "persona_notes", ["campaign_id"])
    op.create_index("ix_persona_notes_character_id", "persona_notes", ["character_id"])


def downgrade() -> None:
    op.drop_index("ix_persona_notes_character_id", table_name="persona_notes")
    op.drop_index("ix_persona_notes_campaign_id", table_name="persona_notes")
    op.drop_table("persona_notes")
    with op.batch_alter_table("characters") as batch:
        batch.drop_column("persona")
