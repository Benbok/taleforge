"""Allow privately owned equipment artwork outside a campaign."""

import sqlalchemy as sa
from alembic import op

revision = "universal_0012"
down_revision = "universal_0011"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_rebuild(True)
        return
    with op.batch_alter_table("equipment_artworks") as batch:
        batch.alter_column("campaign_id", existing_type=sa.String(32), nullable=True)
        batch.add_column(sa.Column("owner_user_id", sa.String(32)))
        batch.create_foreign_key("fk_equipment_artwork_owner", "users", ["owner_user_id"], ["id"], ondelete="CASCADE")
        batch.create_check_constraint("ck_equipment_artwork_scope", "(campaign_id IS NULL) <> (owner_user_id IS NULL)")
        batch.create_unique_constraint("uq_equipment_artwork_owner_request", ["owner_user_id", "request_key"])
    op.create_index("ix_equipment_artwork_owner_source", "equipment_artworks", ["owner_user_id", "source_digest"])
    op.create_index(
        "uq_equipment_artwork_owner_pending",
        "equipment_artworks",
        ["owner_user_id", "source_digest"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM equipment_artworks WHERE campaign_id IS NULL")):
        raise RuntimeError("Export library equipment artwork before downgrading; no images were deleted")
    if op.get_bind().dialect.name == "sqlite":
        _sqlite_rebuild(False)
        return
    op.drop_index("uq_equipment_artwork_owner_pending", table_name="equipment_artworks")
    op.drop_index("ix_equipment_artwork_owner_source", table_name="equipment_artworks")
    with op.batch_alter_table("equipment_artworks") as batch:
        batch.drop_constraint("uq_equipment_artwork_owner_request", type_="unique")
        batch.drop_constraint("ck_equipment_artwork_scope", type_="check")
        batch.drop_constraint("fk_equipment_artwork_owner", type_="foreignkey")
        batch.drop_column("owner_user_id")
        batch.alter_column("campaign_id", existing_type=sa.String(32), nullable=False)


def _sqlite_rebuild(library):
    # Reference the new table itself during copying. A reference to the OLD table would
    # cascade-delete copied receipts when the old table is dropped with foreign_keys=ON.
    temporary = "equipment_artworks_v12"
    columns = [
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("campaign_id", sa.String(32), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=library),
        sa.Column("request_key", sa.String(128), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("mime", sa.String(64)),
        sa.Column(
            "reused_from",
            sa.String(32),
            sa.ForeignKey(f"{temporary}.id", ondelete="CASCADE", name="fk_equipment_artwork_reused_from"),
        ),
        sa.Column("error", sa.String(64)),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("campaign_id", "request_key", name="uq_equipment_artwork_request"),
        sa.CheckConstraint("status IN ('pending', 'ready', 'failed')", name="ck_equipment_artwork_status"),
    ]
    if library:
        columns.extend(
            [
                sa.Column(
                    "owner_user_id",
                    sa.String(32),
                    sa.ForeignKey("users.id", ondelete="CASCADE", name="fk_equipment_artwork_owner"),
                ),
                sa.CheckConstraint(
                    "(campaign_id IS NULL) <> (owner_user_id IS NULL)", name="ck_equipment_artwork_scope"
                ),
                sa.UniqueConstraint("owner_user_id", "request_key", name="uq_equipment_artwork_owner_request"),
            ]
        )
    op.create_table(temporary, *columns)
    names = "id,campaign_id,request_key,source_digest,status,mime,reused_from,error,lease_until,created_at"
    op.execute(sa.text(f"INSERT INTO {temporary} ({names}) SELECT {names} FROM equipment_artworks"))
    op.drop_table("equipment_artworks")
    op.rename_table(temporary, "equipment_artworks")
    op.create_index("ix_equipment_artwork_source", "equipment_artworks", ["campaign_id", "source_digest"])
    op.create_index(
        "uq_equipment_artwork_pending",
        "equipment_artworks",
        ["campaign_id", "source_digest"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
    )
    if library:
        op.create_index("ix_equipment_artwork_owner_source", "equipment_artworks", ["owner_user_id", "source_digest"])
        op.create_index(
            "uq_equipment_artwork_owner_pending",
            "equipment_artworks",
            ["owner_user_id", "source_digest"],
            unique=True,
            sqlite_where=sa.text("status = 'pending'"),
        )
