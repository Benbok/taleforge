"""Источник и причина наложенного эффекта: их видят игрок в листе героя и мастер в таблице сцены."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("active_effects", sa.Column("source", sa.String(120)))
    op.add_column("active_effects", sa.Column("reason", sa.String(200)))


def downgrade() -> None:
    with op.batch_alter_table("active_effects") as batch:  # SQLite не умеет DROP COLUMN без пересоздания таблицы
        batch.drop_column("reason")
        batch.drop_column("source")
