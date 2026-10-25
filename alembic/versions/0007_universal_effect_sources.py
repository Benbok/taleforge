"""Runtime effect sources may be saved heroes or saved NPC entities."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0007"
down_revision = "universal_0006"
branch_labels = None
depends_on = None


def upgrade():
    constraints = sa.inspect(op.get_bind()).get_foreign_keys("universal_effects")
    for constraint in constraints:
        if constraint["constrained_columns"] == ["source_actor_id"]:
            name = constraint["name"] or "fk_universal_effects_source_actor_id_characters"
            with op.batch_alter_table(
                "universal_effects",
                naming_convention={"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"},
            ) as batch:
                batch.drop_constraint(name, type_="foreignkey")


def downgrade():
    connection = op.get_bind()
    orphan = connection.execute(
        sa.text(
            "SELECT 1 FROM universal_effects e WHERE NOT EXISTS "
            "(SELECT 1 FROM characters c WHERE c.id=e.source_actor_id) LIMIT 1"
        )
    ).first()
    if orphan:
        raise RuntimeError("Cannot downgrade while NPC-sourced effects exist; saved effects were preserved")
    with op.batch_alter_table("universal_effects") as batch:
        batch.create_foreign_key(
            "fk_universal_effects_source_actor_id_characters",
            "characters",
            ["source_actor_id"],
            ["id"],
            ondelete="CASCADE",
        )
