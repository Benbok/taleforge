"""Coordinate linked library/game image requests under the same durable pending key."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0013"
down_revision = "universal_0012"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("equipment_artworks", sa.Column("pending_scope", sa.String(80), nullable=False, server_default=""))
    op.execute(
        sa.text(
            "UPDATE equipment_artworks SET pending_scope = CASE WHEN campaign_id IS NOT NULL "
            "THEN 'campaign:' || campaign_id ELSE 'owner:' || owner_user_id END"
        )
    )
    op.create_index(
        "uq_equipment_shared_pending",
        "equipment_artworks",
        ["pending_scope", "source_digest"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    op.drop_index("uq_equipment_shared_pending", table_name="equipment_artworks")
    op.drop_column("equipment_artworks", "pending_scope")
