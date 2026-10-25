"""Add game clock, once-only steps and persistent noncombat effects."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0005"
down_revision = "universal_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "universal_clocks",
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("game_seconds", sa.Text(), nullable=False),
        sa.Column("step_index", sa.Text(), nullable=False),
    )
    op.create_table(
        "universal_steps",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("sequence", sa.Text(), nullable=False),
        sa.Column("started_seconds", sa.Text(), nullable=False),
        sa.Column("ended_seconds", sa.Text(), nullable=False),
        sa.Column("elapsed_seconds", sa.Text(), nullable=False),
        sa.Column("changes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "source_key"),
    )
    op.create_index("ix_universal_steps_campaign_id", "universal_steps", ["campaign_id"])
    op.create_table(
        "universal_effects",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_actor_id", sa.String(32), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_event_id", sa.String(32), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.String(32), nullable=False),
        sa.Column("component", sa.String(64), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("starts_seconds", sa.Text(), nullable=False),
        sa.Column("ends_seconds", sa.Text(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.UniqueConstraint("campaign_id", "source_event_id", "target_id", "component"),
    )
    for column in ["campaign_id", "target_id", "status"]:
        op.create_index("ix_universal_effects_" + column, "universal_effects", [column])


def downgrade():
    op.drop_table("universal_effects")
    op.drop_table("universal_steps")
    op.drop_table("universal_clocks")
