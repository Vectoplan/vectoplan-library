"""reusable manufacturer master data and ownership transfers

Revision ID: c842d6a71e53
Revises: b731c5f09a42
Create Date: 2026-08-13
"""

from alembic import op
import sqlalchemy as sa


revision = "c842d6a71e53"
down_revision = "b731c5f09a42"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manufacturer_organizations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("organization_key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=True),
        sa.Column("website", sa.String(length=1024), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="DE"),
        sa.Column("owner_subject", sa.String(length=160), nullable=False),
        sa.Column("owner_account_id", sa.String(length=160), nullable=True),
        sa.Column("created_by_subject", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="active"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
        sa.UniqueConstraint("organization_key"),
    )
    for column in ("uid", "organization_key", "name", "brand", "country_code", "owner_subject", "owner_account_id", "created_by_subject", "status", "active"):
        op.create_index(f"ix_manufacturer_organizations_{column}", "manufacturer_organizations", [column])

    op.create_table(
        "manufacturer_locations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("roles_json", sa.JSON(), nullable=False),
        sa.Column("address", sa.String(length=1024), nullable=False),
        sa.Column("formatted_address", sa.String(length=1024), nullable=True),
        sa.Column("mapbox_feature_id", sa.String(length=255), nullable=True),
        sa.Column("country_code", sa.String(length=2), nullable=False, server_default="DE"),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("coverage_mode", sa.String(length=40), nullable=False, server_default="radius"),
        sa.Column("radius_km", sa.Float(), nullable=True),
        sa.Column("territory_codes_json", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["manufacturer_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    for column in ("uid", "organization_id", "mapbox_feature_id", "country_code", "latitude", "longitude", "coverage_mode", "radius_km", "active"):
        op.create_index(f"ix_manufacturer_locations_{column}", "manufacturer_locations", [column])

    op.create_table(
        "manufacturer_family_links",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("family_db_id", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("linked_by_subject", sa.String(length=160), nullable=True),
        sa.Column("variant_assignments_json", sa.JSON(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["manufacturer_organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["family_db_id"], ["creative_library_items.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
        sa.UniqueConstraint("organization_id", "family_db_id", name="uq_manufacturer_family_link"),
    )
    for column in ("uid", "organization_id", "family_db_id", "active"):
        op.create_index(f"ix_manufacturer_family_links_{column}", "manufacturer_family_links", [column])

    op.create_table(
        "manufacturer_access_grants",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("subject_type", sa.String(length=40), nullable=False),
        sa.Column("subject_id", sa.String(length=160), nullable=False),
        sa.Column("access_role", sa.String(length=40), nullable=False, server_default="editor"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("granted_by_subject", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["manufacturer_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
        sa.UniqueConstraint("organization_id", "subject_type", "subject_id", name="uq_manufacturer_access_grant"),
    )
    for column in ("uid", "organization_id", "subject_type", "subject_id", "access_role", "active"):
        op.create_index(f"ix_manufacturer_access_grants_{column}", "manufacturer_access_grants", [column])

    op.create_table(
        "manufacturer_ownership_transfers",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.String(length=80), nullable=False),
        sa.Column("organization_id", sa.BigInteger(), nullable=False),
        sa.Column("previous_owner_subject", sa.String(length=160), nullable=True),
        sa.Column("new_owner_subject", sa.String(length=160), nullable=False),
        sa.Column("new_owner_account_id", sa.String(length=160), nullable=True),
        sa.Column("transferred_by_subject", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="completed"),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["manufacturer_organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("uid"),
    )
    for column in ("uid", "organization_id", "new_owner_subject", "new_owner_account_id", "status"):
        op.create_index(f"ix_manufacturer_ownership_transfers_{column}", "manufacturer_ownership_transfers", [column])


def downgrade():
    op.drop_table("manufacturer_ownership_transfers")
    op.drop_table("manufacturer_access_grants")
    op.drop_table("manufacturer_family_links")
    op.drop_table("manufacturer_locations")
    op.drop_table("manufacturer_organizations")
