"""Allow one generated sound playback per action in a turn."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _unique_name(bind):
    for item in sa.inspect(bind).get_unique_constraints("sfx_playbacks"):
        if set(item.get("column_names") or ()) == {"campaign_id", "turn_id"}:
            return item.get("name")
    return None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite cannot drop an anonymous table constraint in place. Rebuild this small outbox table.
        op.execute(
            """
            CREATE TABLE sfx_playbacks_new (
                id VARCHAR(32) NOT NULL PRIMARY KEY,
                campaign_id VARCHAR(32) NOT NULL,
                sound_id VARCHAR(32) NOT NULL,
                turn_id VARCHAR(32),
                asset_id VARCHAR(32),
                audience JSON NOT NULL,
                context JSON NOT NULL,
                status VARCHAR(16) NOT NULL,
                expires_at FLOAT NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(campaign_id) REFERENCES campaigns (id) ON DELETE CASCADE,
                FOREIGN KEY(sound_id) REFERENCES sfx_sounds (id) ON DELETE CASCADE
            )
            """
        )
        op.execute(
            "INSERT INTO sfx_playbacks_new "
            "(id,campaign_id,sound_id,turn_id,asset_id,audience,context,status,expires_at,created_at) "
            "SELECT id,campaign_id,sound_id,turn_id,asset_id,audience,context,status,expires_at,created_at "
            "FROM sfx_playbacks"
        )
        op.drop_table("sfx_playbacks")
        op.rename_table("sfx_playbacks_new", "sfx_playbacks")
        op.create_index("ix_sfx_playbacks_campaign_id", "sfx_playbacks", ["campaign_id"])
        op.create_index("ix_sfx_playbacks_status", "sfx_playbacks", ["status"])
        return
    name = _unique_name(bind)
    if not name:
        return
    op.drop_constraint(name, "sfx_playbacks", type_="unique")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("sfx_playbacks", recreate="always") as batch_op:
            batch_op.create_unique_constraint(
                "uq_sfx_playbacks_campaign_id_turn_id",
                ["campaign_id", "turn_id"],
            )
        return
    op.create_unique_constraint("uq_sfx_playbacks_campaign_id_turn_id", "sfx_playbacks", ["campaign_id", "turn_id"])
