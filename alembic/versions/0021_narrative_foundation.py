"""Narrative foundation: states, facts, and threads.

Revision ID: 0021
Revises: 0020
Create Date: 2026-10-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "narrative_states",
        sa.Column(
            "campaign_id",
            sa.String(length=32),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("mode", sa.String(length=16), nullable=False, server_default="strict"),
        sa.Column("recent_boundaries", JSON, nullable=False),
        sa.Column("budget_counters", JSON, nullable=False),
        sa.Column("initialized_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "narrative_facts",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(length=32),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("namespace", sa.String(length=16), nullable=False),
        sa.Column("subject_id", sa.String(length=64), nullable=False),
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("temporal_semantics", sa.String(length=16), nullable=False),
        sa.Column("freedom", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("audience", JSON, nullable=False),
        sa.Column("depends_on", JSON, nullable=False),
        sa.Column("source_refs", JSON, nullable=False),
        sa.Column("snapshot_ref", JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "namespace", "subject_id", "key", name="uq_narrative_facts_address"),
    )
    op.create_index("ix_narrative_facts_campaign_id", "narrative_facts", ["campaign_id"])
    op.create_index("ix_narrative_facts_subject", "narrative_facts", ["campaign_id", "namespace", "subject_id"])

    op.create_table(
        "narrative_threads",
        sa.Column("id", sa.String(length=32), primary_key=True),
        sa.Column(
            "campaign_id",
            sa.String(length=32),
            sa.ForeignKey("campaigns.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="offered"),
        sa.Column("audience", JSON, nullable=False),
        sa.Column("subject_refs", JSON, nullable=False),
        sa.Column("plan_refs", JSON, nullable=False),
        sa.Column("parent_id", sa.String(length=64), nullable=True),
        sa.Column("source_refs", JSON, nullable=False),
        sa.Column("last_developed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "thread_id", name="uq_narrative_threads_id"),
    )
    op.create_index("ix_narrative_threads_campaign_id", "narrative_threads", ["campaign_id"])
    op.create_index(
        "ix_narrative_threads_status",
        "narrative_threads",
        ["campaign_id", "status", "last_developed_at"],
    )


def downgrade() -> None:
    op.drop_table("narrative_threads")
    op.drop_table("narrative_facts")
    op.drop_table("narrative_states")
