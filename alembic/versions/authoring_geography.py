"""authoring_geography

Revision ID: 0035
Revises: 0034
Create Date: 2026-10-18 15:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0035"
down_revision: str | None = "0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSONType = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "geography_nodes",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=32), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("plot_ref", sa.String(length=64), nullable=True),
        sa.Column("entity_id", sa.String(length=32), nullable=True),
        sa.Column("parent_id", sa.String(length=32), nullable=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["parent_id"], ["geography_nodes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "ref", name="uq_geography_node_ref"),
    )
    op.create_index(op.f("ix_geography_nodes_campaign_id"), "geography_nodes", ["campaign_id"], unique=False)
    for name, column in (("uq_geography_node_plot_ref", "plot_ref"), ("uq_geography_node_entity", "entity_id")):
        op.create_index(
            name,
            "geography_nodes",
            ["campaign_id", column],
            unique=True,
            sqlite_where=sa.text(f"{column} IS NOT NULL"),
            postgresql_where=sa.text(f"{column} IS NOT NULL"),
        )
    op.create_table(
        "geography_links",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("campaign_id", sa.String(length=32), nullable=False),
        sa.Column("ref", sa.String(length=64), nullable=False),
        sa.Column("from_node_id", sa.String(length=32), nullable=False),
        sa.Column("to_node_id", sa.String(length=32), nullable=False),
        sa.Column("from_area_ref", sa.String(length=64), nullable=True),
        sa.Column("to_area_ref", sa.String(length=64), nullable=True),
        sa.Column("bidirectional", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("kind", sa.String(length=32), server_default="path", nullable=False),
        sa.Column("state", sa.String(length=16), server_default="open", nullable=False),
        sa.Column("hidden", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("constraints", JSONType, nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_node_id"], ["geography_nodes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_node_id"], ["geography_nodes.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", "ref", name="uq_geography_link_ref"),
    )
    op.create_index(op.f("ix_geography_links_campaign_id"), "geography_links", ["campaign_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_geography_links_campaign_id"), table_name="geography_links")
    op.drop_table("geography_links")
    op.drop_index("uq_geography_node_entity", table_name="geography_nodes")
    op.drop_index("uq_geography_node_plot_ref", table_name="geography_nodes")
    op.drop_index(op.f("ix_geography_nodes_campaign_id"), table_name="geography_nodes")
    op.drop_table("geography_nodes")
