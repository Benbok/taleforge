"""World revision, turn checkpoint and preparation request time (scene generation spec, §6.1, §6.2, §6.4).

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("campaigns") as batch:
        batch.add_column(sa.Column("world_revision", sa.Integer(), nullable=False, server_default="0"))
    # Nullable: finished turns of older versions have no checkpoint and are never resumed.
    with op.batch_alter_table("master_turns") as batch:
        batch.add_column(sa.Column("generation_checkpoint", JSON, nullable=True))
    with op.batch_alter_table("world_generation_states") as batch:
        batch.add_column(sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("world_generation_states") as batch:
        batch.drop_column("requested_at")
    with op.batch_alter_table("master_turns") as batch:
        batch.drop_column("generation_checkpoint")
    with op.batch_alter_table("campaigns") as batch:
        batch.drop_column("world_revision")
