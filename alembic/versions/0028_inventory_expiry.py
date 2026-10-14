"""Track expiration of temporary consumable batches."""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("inventory", sa.Column("expires_at", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("inventory", "expires_at")
