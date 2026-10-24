"""Add campaign runtime profiles and successful ability discoveries."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0004"
down_revision = "universal_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runtime_profiles",
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("ref", sa.String(128), primary_key=True),
        sa.Column("revision", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
    )
    op.create_table(
        "hero_abilities",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("character_id", sa.String(32), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("profile_ref", sa.String(128), nullable=False),
        sa.Column("profile_revision", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("source_event_id", sa.String(32), sa.ForeignKey("events.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("character_id", "profile_ref"),
    )
    op.create_index("ix_hero_abilities_character_id", "hero_abilities", ["character_id"])
    op.create_index("ix_hero_abilities_campaign_id", "hero_abilities", ["campaign_id"])


def downgrade():
    op.drop_table("hero_abilities")
    op.drop_table("runtime_profiles")
