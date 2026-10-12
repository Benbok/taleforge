"""Location layout phases: complex structure and area geometry (generative location maps spec, §8).

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD = "phase IN ('location_initial', 'container_contents')"
NEW = "phase IN ('location_initial', 'container_contents', 'location_layout', 'location_geometry')"


def _replace(check: str) -> None:
    with op.batch_alter_table("world_generation_states") as batch:
        batch.drop_constraint("ck_world_generation_phase", type_="check")
        batch.create_check_constraint("ck_world_generation_phase", check)


def upgrade() -> None:
    _replace(NEW)


def downgrade() -> None:
    op.execute("DELETE FROM world_generation_states WHERE phase IN ('location_layout', 'location_geometry')")
    _replace(OLD)
