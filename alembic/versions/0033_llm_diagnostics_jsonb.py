"""Align LLM diagnostics with the JSONB ORM mapping on PostgreSQL.

Revision ID: 0033
Revises: 0032
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "llm_calls",
        "diagnostics",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="diagnostics::jsonb",
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "llm_calls",
        "diagnostics",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using="diagnostics::json",
    )
