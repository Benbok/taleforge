"""Backfill party map memories from existing character-owned snapshots."""

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        INSERT INTO party_map_memories
            (campaign_id, root_id, entity_id, snapshot, discovered_passages, revision, observed_at, updated_at)
        SELECT c.campaign_id,
               (m.snapshot ->> 'root_id'),
               m.entity_id,
               m.snapshot,
               m.discovered_passages,
               m.revision,
               m.updated_at,
               m.updated_at
        FROM map_memories AS m
        JOIN characters AS c ON c.id = m.character_id
        WHERE m.snapshot IS NOT NULL
          AND (m.snapshot ->> 'root_id') IS NOT NULL
        ON CONFLICT (campaign_id, root_id, entity_id) DO NOTHING
        """
    )


def downgrade():
    # The rows may contain discoveries made after the migration; do not delete them.
    pass
