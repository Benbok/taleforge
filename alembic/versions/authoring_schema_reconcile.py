"""Repair deployments stamped 0031 with either of its historical schemas.

The stamp alone cannot tell whether usage columns or JSONB conversion ran.
0032 reapplies the lossless JSONB conversion; this revision fills missing usage
columns. No application database needs restamping or dropping existing rows.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"]: column for column in sa.inspect(bind).get_columns("llm_calls")}
    with op.batch_alter_table("llm_calls") as batch:
        for name, kind in (("tokens_cached", sa.Integer()), ("cost_known", sa.Boolean()), ("diagnostics", sa.JSON())):
            if name not in columns:
                batch.add_column(sa.Column(name, kind, nullable=True))
    if bind.dialect.name == "postgresql":
        op.alter_column("llm_calls", "diagnostics", type_=postgresql.JSONB(), postgresql_using="diagnostics::jsonb")


def downgrade() -> None:
    # The repaired columns belong to 0031 and must remain until its downgrade.
    if op.get_bind().dialect.name == "postgresql":
        op.alter_column("llm_calls", "diagnostics", type_=sa.JSON(), postgresql_using="diagnostics::json")
