"""Personal remembered location-map geometry."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "map_memories",
        sa.Column("character_id", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.String(length=32), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=True),
        sa.Column("discovered_passages", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("character_id", "entity_id"),
    )
    op.create_index("ix_map_memories_character_id", "map_memories", ["character_id"])
    op.create_index("ix_map_memories_entity_id", "map_memories", ["entity_id"])


def downgrade() -> None:
    op.drop_index("ix_map_memories_entity_id", table_name="map_memories")
    op.drop_index("ix_map_memories_character_id", table_name="map_memories")
    op.drop_table("map_memories")
