"""Keep request receipts when serving existing equipment artwork."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0011"
down_revision = "universal_0010"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("equipment_artworks") as batch:
        batch.add_column(sa.Column("reused_from", sa.String(32)))
        batch.create_foreign_key(
            "fk_equipment_artwork_reused_from",
            "equipment_artworks",
            ["reused_from"],
            ["id"],
            ondelete="CASCADE",
        )


def downgrade():
    with op.batch_alter_table("equipment_artworks") as batch:
        batch.drop_constraint("fk_equipment_artwork_reused_from", type_="foreignkey")
        batch.drop_column("reused_from")
