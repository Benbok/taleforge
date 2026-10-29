"""Encountered NPC portrait candidates and explicit selection."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0015"
down_revision = "universal_0014"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "npc_portraits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("npc_id", sa.String(32), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(64)),
        sa.Column("error", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "request_key", name="uq_npc_portrait_request"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_npc_portrait_status"),
    )
    op.create_index("ix_npc_portraits_campaign_id", "npc_portraits", ["campaign_id"])
    op.create_index("ix_npc_portraits_npc_id", "npc_portraits", ["npc_id"])
    op.create_index(
        "uq_npc_portrait_pending",
        "npc_portraits",
        ["npc_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "npc_portrait_selections",
        sa.Column("npc_id", sa.String(32), sa.ForeignKey("entities.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_digest", sa.String(64), primary_key=True),
        sa.Column("image_id", sa.String(32), sa.ForeignKey("npc_portraits.id", ondelete="CASCADE"), nullable=False),
    )


def downgrade():
    op.drop_table("npc_portrait_selections")
    op.drop_table("npc_portraits")
