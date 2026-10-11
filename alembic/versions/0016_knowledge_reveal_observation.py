"""Knowledge: explicit physical discovery and observed snapshot (scene generation spec, §8.2).

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # Nullable: old knowledge rows are neither a discovery nor an observation.
    with op.batch_alter_table("knowledge") as batch:
        batch.add_column(sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("observed_snapshot", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("knowledge") as batch:
        batch.drop_column("observed_snapshot")
        batch.drop_column("revealed_at")
