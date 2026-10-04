"""party split: which master turn took a player's message

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-04 09:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("turn_id", sa.String(length=32), nullable=True))
    op.create_index("ix_messages_campaign_turn", "messages", ["campaign_id", "turn_id"], unique=False)
    # реплики, которые уже взяли прежние ходы мастера (по номеру upto_seq), считаются взятыми
    op.execute(
        """
        UPDATE messages SET turn_id = 'legacy'
        WHERE kind IN ('action', 'speech', 'whisper')
          AND seq <= COALESCE(
            (SELECT MAX(t.upto_seq) FROM master_turns t WHERE t.campaign_id = messages.campaign_id), 0)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_messages_campaign_turn", table_name="messages")
    op.drop_column("messages", "turn_id")
