"""Saved hero/enemy exchange checkpoints; existing clocks and effects retained."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0006"
down_revision = "universal_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "universal_exchanges",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("proposal", sa.JSON(), nullable=False),
        sa.Column("hero_outcome", sa.JSON(), nullable=True),
        sa.Column("enemy_outcome", sa.JSON(), nullable=True),
        sa.Column("hero_event_id", sa.String(32), nullable=True),
        sa.Column("enemy_actor_id", sa.String(32), nullable=True),
        sa.Column("enemy_target_id", sa.String(32), nullable=True),
        sa.Column("selection_attempted", sa.Boolean(), nullable=False),
        sa.Column("selection_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequence", sa.Text(), nullable=False),
        sa.Column("started_seconds", sa.Text(), nullable=False),
        sa.Column("elapsed_seconds", sa.Text(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "source_key"),
    )
    op.create_index("ix_universal_exchanges_campaign_id", "universal_exchanges", ["campaign_id"])


def downgrade():
    op.drop_table("universal_exchanges")
