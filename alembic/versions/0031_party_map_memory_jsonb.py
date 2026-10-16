"""Align party map memory JSON columns with the JSONB ORM mapping.

Revision ID: 0031
Revises: 0030
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "party_map_memories",
        "snapshot",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=True,
        postgresql_using="snapshot::jsonb",
    )
    op.alter_column(
        "party_map_memories",
        "discovered_passages",
        existing_type=sa.JSON(),
        type_=postgresql.JSONB(),
        existing_nullable=False,
        existing_server_default=sa.text("'[]'"),
        postgresql_using="discovered_passages::jsonb",
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.alter_column(
        "party_map_memories",
        "snapshot",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=True,
        postgresql_using="snapshot::json",
    )
    op.alter_column(
        "party_map_memories",
        "discovered_passages",
        existing_type=postgresql.JSONB(),
        type_=sa.JSON(),
        existing_nullable=False,
        existing_server_default=sa.text("'[]'"),
        postgresql_using="discovered_passages::json",
    )
