"""Narrative work: durable director jobs and leases.

Revision ID: 0022
Revises: 0021
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "narrative_work",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(length=32),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_key", sa.String(length=128), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False, server_default="future"),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=64), nullable=False),
        sa.Column("audience", JSON, nullable=False),
        sa.Column("focus", sa.String(length=128), nullable=True),
        sa.Column("session_budget_ref", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_refs", JSON, nullable=False),
        sa.Column("base", JSON, nullable=True),
        sa.Column("proposal_id", sa.String(length=64), nullable=False),
        sa.Column("draft", JSON, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("capacity_slot", sa.Integer(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resnapshots", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_event_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "source_key", name="uq_narrative_work_source"),
    )
    op.create_index("ix_narrative_work_campaign_id", "narrative_work", ["campaign_id"])
    op.create_index(
        "ix_narrative_work_status",
        "narrative_work",
        ["status", "retry_after", "lease_until"],
    )
    op.create_index(
        "ix_narrative_work_campaign_created",
        "narrative_work",
        ["campaign_id", "created_at"],
    )
    op.create_index(
        "ix_narrative_work_capacity_slot",
        "narrative_work",
        ["capacity_slot"],
        unique=True,
        sqlite_where=sa.text("capacity_slot IS NOT NULL"),
        postgresql_where=sa.text("capacity_slot IS NOT NULL"),
    )
    op.create_index(
        "ix_narrative_work_campaign_preparing",
        "narrative_work",
        ["campaign_id"],
        unique=True,
        sqlite_where=sa.text("status = 'preparing'"),
        postgresql_where=sa.text("status = 'preparing'"),
    )


def downgrade() -> None:
    op.drop_table("narrative_work")
