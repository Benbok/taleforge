"""Persist party-wide map exploration independently of characters."""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "party_map_memories",
        sa.Column("campaign_id", sa.String(length=32), nullable=False),
        sa.Column("root_id", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("discovered_passages", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["root_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "root_id", "entity_id"),
    )
    op.create_index("ix_party_map_memories_campaign_root", "party_map_memories", ["campaign_id", "root_id"])
    op.create_index("ix_party_map_memories_entity_id", "party_map_memories", ["entity_id"])


def downgrade():
    op.drop_index("ix_party_map_memories_entity_id", table_name="party_map_memories")
    op.drop_index("ix_party_map_memories_campaign_root", table_name="party_map_memories")
    op.drop_table("party_map_memories")
