"""Store personal application menu music preferences.

Revision ID: 0023
Revises: 0022
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("menu_music_enabled", sa.Boolean(), nullable=False, server_default=sa.text("1")))
    op.add_column("users", sa.Column("menu_music_volume", sa.Float(), nullable=False, server_default=sa.text("0.2")))


def downgrade() -> None:
    op.drop_column("users", "menu_music_volume")
    op.drop_column("users", "menu_music_enabled")
