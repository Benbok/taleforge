"""Create the cyclic campaign/version FK deferred by PostgreSQL table creation."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0002"
down_revision = "universal_0001"
branch_labels = None
depends_on = None

CONSTRAINT = "fk_campaign_adventure_version"


def upgrade():
    bind = op.get_bind()
    # SQLite includes this constraint inline; PostgreSQL omits use_alter=True
    # during CREATE TABLE and needs the referenced tables to exist first.
    if bind.dialect.name == "postgresql":
        existing = sa.inspect(bind).get_foreign_keys("campaigns")
        if not any(key["name"] == CONSTRAINT for key in existing):
            op.create_foreign_key(CONSTRAINT, "campaigns", "adventure_versions", ["adventure_version_id"], ["id"])


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.drop_constraint(CONSTRAINT, "campaigns", type_="foreignkey")
