"""stage 8 stand-in player

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-29 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("seats") as batch:
        batch.add_column(sa.Column("stand_in_user_id", sa.String(length=32), nullable=True))
        batch.create_foreign_key(
            "fk_seats_stand_in_user_id", "users", ["stand_in_user_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("seats") as batch:
        batch.drop_constraint("fk_seats_stand_in_user_id", type_="foreignkey")
        batch.drop_column("stand_in_user_id")
