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
    # Some deployments applied these columns under the colliding revision.
    existing = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("llm_calls")}
    with op.batch_alter_table("llm_calls") as batch:
        for name, kind in (("tokens_cached", sa.Integer()), ("cost_known", sa.Boolean()), ("diagnostics", sa.JSON())):
            if name not in existing:
                batch.add_column(sa.Column(name, kind, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("llm_calls") as batch:
        batch.drop_column("diagnostics")
        batch.drop_column("cost_known")
        batch.drop_column("tokens_cached")
