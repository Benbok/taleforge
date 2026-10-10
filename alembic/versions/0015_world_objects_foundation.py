"""World Objects: inventory identity, materialization state, and plot bindings.

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    # Nullable: existing inventory rows keep their legacy stack semantics.
    op.add_column(
        "inventory",
        sa.Column(
            "world_entity_id",
            sa.String(length=32),
            sa.ForeignKey("entities.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index("uq_inventory_world_entity_id", "inventory", ["world_entity_id"], unique=True)

    op.create_table(
        "world_generation_states",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("campaign_id", sa.String(length=32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_entity_id", sa.String(length=32), sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phase", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("quality", sa.String(length=32), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("generator_version", sa.String(length=64), nullable=True),
        sa.Column("profile_ref", sa.String(length=128), nullable=True),
        sa.Column("source_versions", JSON, nullable=False),
        sa.Column("context_digest", sa.String(length=64), nullable=True),
        sa.Column("reservation", JSON, nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("result_digest", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("campaign_id", "target_entity_id", "phase", name="uq_world_generation_scope"),
        sa.CheckConstraint(
            "phase IN ('location_initial', 'container_contents')", name="ck_world_generation_phase"
        ),
        sa.CheckConstraint(
            "status IN ('unprepared', 'preparing', 'ready', 'blocked')", name="ck_world_generation_status"
        ),
        sa.CheckConstraint(
            "quality IS NULL OR quality IN ('normal', 'fallback', 'legacy_preserved')",
            name="ck_world_generation_quality",
        ),
    )
    op.create_index("ix_world_generation_states_campaign_id", "world_generation_states", ["campaign_id"])

    op.create_table(
        "world_plot_bindings",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column("campaign_id", sa.String(length=32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("anchor_id", sa.String(length=128), nullable=False),
        sa.Column("plot_ref", sa.String(length=128), nullable=False),
        sa.Column(
            "holder_entity_id", sa.String(length=32), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column(
            "target_location_id", sa.String(length=32), sa.ForeignKey("entities.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("source_snapshot", JSON, nullable=False),
        sa.Column("replacement_ref", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "anchor_id", name="uq_world_plot_anchor"),
        sa.CheckConstraint(
            "state IN ('reserved', 'materialized', 'revealed', 'lost', 'replaced_by_story')",
            name="ck_world_plot_binding_state",
        ),
    )
    op.create_index("ix_world_plot_bindings_campaign_id", "world_plot_bindings", ["campaign_id"])


def downgrade() -> None:
    op.drop_index("ix_world_plot_bindings_campaign_id", table_name="world_plot_bindings")
    op.drop_table("world_plot_bindings")
    op.drop_index("ix_world_generation_states_campaign_id", table_name="world_generation_states")
    op.drop_table("world_generation_states")
    op.drop_index("uq_inventory_world_entity_id", table_name="inventory")
    op.drop_column("inventory", "world_entity_id")
