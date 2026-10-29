"""Keep rejected portrait candidates hidden after an explicit choice."""

from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision = "universal_0016"
down_revision = "universal_0015"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("npc_portrait_selections", sa.Column("chosen_at", sa.DateTime(timezone=True)))
    selections = sa.table("npc_portrait_selections", sa.column("chosen_at", sa.DateTime(timezone=True)))
    op.execute(selections.update().values(chosen_at=datetime.now(UTC)))


def downgrade():
    op.drop_column("npc_portrait_selections", "chosen_at")
