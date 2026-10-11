"""World generation runtime: retry schedule, attempt counters and result manifest (scene generation spec, §4.4).

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    with op.batch_alter_table("world_generation_states") as batch:
        batch.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("llm_attempt_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("conflict_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("result_manifest", JSON, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("world_generation_states") as batch:
        batch.drop_column("result_manifest")
        batch.drop_column("conflict_count")
        batch.drop_column("llm_attempt_count")
        batch.drop_column("next_attempt_at")
