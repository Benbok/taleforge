"""Persist protected location illustrations and durable generation receipts."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0009"
down_revision = "universal_0008"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "location_artworks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("location_id", sa.String(32), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(64)),
        sa.Column("error", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "request_key", name="uq_location_artwork_request"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_location_artwork_status"),
    )
    op.create_index("ix_location_artworks_campaign_id", "location_artworks", ["campaign_id"])
    op.create_index("ix_location_artworks_location_id", "location_artworks", ["location_id"])
    op.create_index(
        "uq_location_artwork_pending",
        "location_artworks",
        ["location_id"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_table("location_artworks")
