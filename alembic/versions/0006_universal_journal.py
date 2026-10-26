"""Add the journal of unusual requests."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0006"
down_revision = "universal_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "universal_journal",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "kind", "source_key"),
    )
    op.create_index("ix_universal_journal_campaign_id", "universal_journal", ["campaign_id"])


def downgrade():
    op.drop_index("ix_universal_journal_campaign_id", table_name="universal_journal")
    op.drop_table("universal_journal")
