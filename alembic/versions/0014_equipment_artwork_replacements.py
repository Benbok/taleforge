"""Version successful equipment images independently of cache-hit receipt timestamps."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0014"
down_revision = "universal_0013"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "equipment_artworks", sa.Column("regenerate", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("equipment_artworks", sa.Column("selected_at", sa.DateTime(timezone=True)))
    op.execute(sa.text("UPDATE equipment_artworks SET selected_at = created_at WHERE status = 'ready'"))
    op.execute(
        sa.text(
            "UPDATE equipment_artworks SET selected_at = "
            "(SELECT original.created_at FROM equipment_artworks AS original "
            "WHERE original.id = equipment_artworks.reused_from) "
            "WHERE reused_from IS NOT NULL"
        )
    )


def downgrade():
    op.drop_column("equipment_artworks", "selected_at")
    op.drop_column("equipment_artworks", "regenerate")
