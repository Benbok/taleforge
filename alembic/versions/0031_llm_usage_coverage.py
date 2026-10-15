"""Cache usage, price coverage and content-free prompt diagnostics.

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.add_column(sa.Column("tokens_cached", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cost_known", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("diagnostics", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.drop_column("diagnostics")
        batch.drop_column("cost_known")
        batch.drop_column("tokens_cached")
