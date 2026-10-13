"""LLM call accounting by preparation phase (generative location maps spec, §8).

Revision ID: 0026
Revises: 0025
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.add_column(sa.Column("generation_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("tokens_reasoning", sa.Integer(), nullable=False, server_default="0"))
        batch.create_index("ix_llm_calls_generation_id", ["generation_id"])


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.drop_index("ix_llm_calls_generation_id")
        batch.drop_column("tokens_reasoning")
        batch.drop_column("generation_id")
