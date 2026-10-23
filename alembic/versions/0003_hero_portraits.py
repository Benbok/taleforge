"""Persist portrait media references and generation receipts without changing existing heroes."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0003"
down_revision = "universal_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hero_portraits",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("owner_user_id", sa.String(32), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("target_id", sa.String(32), nullable=False),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(32)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "request_key"),
    )
    for table in ("characters", "library_characters"):
        op.add_column(table, sa.Column("portrait_id", sa.String(32)))
        op.add_column(table, sa.Column("portrait_job_id", sa.String(32)))


def downgrade():
    for table in ("characters", "library_characters"):
        op.drop_column(table, "portrait_job_id")
        op.drop_column(table, "portrait_id")
    op.drop_table("hero_portraits")
