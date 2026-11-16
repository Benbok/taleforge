"""One attempt per way: failed approaches remembered per target."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0018"
down_revision = "universal_0017"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "attempt_locks",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.String(64), nullable=False),
        sa.Column("attribute", sa.String(8), nullable=False),
        sa.Column("actor_id", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "target_id", "attribute", name="uq_attempt_lock"),
    )
    op.create_index("ix_attempt_locks_campaign_id", "attempt_locks", ["campaign_id"])


def downgrade():
    op.drop_index("ix_attempt_locks_campaign_id", table_name="attempt_locks")
    op.drop_table("attempt_locks")
